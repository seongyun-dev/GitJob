"""Create a metadata-only corrected Repo Snapshot from an immutable Snapshot.

The correction reads the pinned commit tree from GitHub's commit endpoint and
copies the existing Snapshot records and Artifact references without fetching
or rewriting any Artifact bytes.  It is intentionally separate from the
normal bootstrap path: the source Snapshot remains immutable and the target
is published only after every eligible COMPLETE/PARTIAL record is corrected.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
TREE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_HDFS_CONTAINER = "gitjob-data-hdfs-namenode-1"
CORRECTABLE_STATUSES = {"COMPLETE", "PARTIAL"}
GRAPHQL_BATCH_SIZE = 10
GRAPHQL_WORKERS = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Correct Git tree metadata without re-fetching repository artifacts."
        )
    )
    parser.add_argument("--source-snapshot-id", required=True)
    parser.add_argument("--target-snapshot-id", required=True)
    parser.add_argument("--pipeline-run-id", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-path", type=Path, required=True)
    parser.add_argument("--token-env-file", type=Path, required=True)
    parser.add_argument("--execution-git-sha", required=True)
    parser.add_argument("--image-digest", default=None)
    parser.add_argument(
        "--hdfs-root", default="/gitjob/analysis_input/github/repo_snapshot"
    )
    parser.add_argument("--hdfs-container", default=DEFAULT_HDFS_CONTAINER)
    parser.add_argument("--state-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = _hdfs_path(args.hdfs_root, args.source_snapshot_id)
    target_root = _hdfs_path(args.hdfs_root, args.target_snapshot_id)
    if _hdfs_exists(args.hdfs_container, target_root):
        raise SystemExit(f"target Snapshot already exists: {target_root}")

    args.state_dir.mkdir(parents=True, exist_ok=True)
    source_snapshot = _read_hdfs_json(
        args.hdfs_container, f"{source_root}/snapshot.json"
    )
    source_summary = _read_hdfs_json(
        args.hdfs_container, f"{source_root}/run-summary.json"
    )
    source_failures = _read_hdfs_json(
        args.hdfs_container, f"{source_root}/failures.json"
    )
    records = source_snapshot.get("records")
    if not isinstance(records, list):
        raise TypeError("source snapshot records must be a list")

    correction_rows = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("collection_status") in CORRECTABLE_STATUSES
        and isinstance(row.get("pinned_commit_sha"), str)
    ]
    if len(correction_rows) != 13_392:
        print(
            f"eligible records={len(correction_rows)} (source run expected 13392)",
            flush=True,
        )

    token = _read_env_value(args.token_env_file, "GITHUB_API_TOKEN")
    candidate_sha = _sha256_file(args.candidate_path)
    image_digest = args.image_digest.strip() if args.image_digest else None
    candidate_payload = json.loads(args.candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate_payload, dict):
        raise TypeError("candidate payload must be an object")
    input_root = candidate_payload.get("input_root")
    if not isinstance(input_root, str) or not input_root.strip():
        raise ValueError("candidate input_root must not be blank")

    state_path = args.state_dir / "tree-map.json"
    state = _load_state(state_path, args, source_snapshot)
    trees: dict[str, dict[str, Any]] = state["trees"]
    rate_limit_wait_count = int(state.get("rate_limit_wait_count", 0))
    rate_limit_wait_seconds = float(state.get("rate_limit_wait_seconds", 0.0))
    started = time.monotonic()

    pending = [
        row for row in correction_rows if str(row["github_repo_id"]) not in trees
    ]
    with ThreadPoolExecutor(max_workers=GRAPHQL_WORKERS) as executor:
        group_size = GRAPHQL_BATCH_SIZE * GRAPHQL_WORKERS
        for offset in range(0, len(pending), group_size):
            group = [
                pending[index : index + GRAPHQL_BATCH_SIZE]
                for index in range(
                    offset,
                    min(offset + group_size, len(pending)),
                    GRAPHQL_BATCH_SIZE,
                )
            ]
            futures = [
                executor.submit(_fetch_commit_tree_batch, token=token, rows=batch)
                for batch in group
            ]
            for future in futures:
                results, waits, waited = future.result()
                trees.update(results)
                rate_limit_wait_count += waits
                rate_limit_wait_seconds += waited
            state["trees"] = trees
            state["rate_limit_wait_count"] = rate_limit_wait_count
            state["rate_limit_wait_seconds"] = rate_limit_wait_seconds
            state["updated_at"] = _utc_now()
            processed = len(correction_rows) - len(pending) + offset + sum(
                len(batch) for batch in group
            )
            _atomic_json_write(state_path, state)
            print(
                f"tree metadata {processed}/{len(correction_rows)} "
                f"waits={rate_limit_wait_count}",
                flush=True,
            )

    expected_ids = {str(row["github_repo_id"]) for row in correction_rows}
    if set(trees) != expected_ids:
        missing = sorted(expected_ids - set(trees))[:5]
        raise RuntimeError(f"tree correction incomplete; missing={missing}")

    generated_at = _utc_now()
    corrected_snapshot = copy.deepcopy(source_snapshot)
    corrected_snapshot["dataset_snapshot_id"] = args.target_snapshot_id
    corrected_snapshot["pipeline_run_id"] = args.pipeline_run_id
    corrected_snapshot["generated_at"] = generated_at
    for row in corrected_snapshot["records"]:
        if not isinstance(row, dict):
            raise TypeError("snapshot record must be an object")
        repo_id = str(row["github_repo_id"])
        row["repo_snapshot_id"] = (
            f"{args.target_snapshot_id}-repo-{row['github_repo_id']}-"
            f"{row['pinned_commit_sha'][:12]}"
        )
        if row.get("collection_status") in CORRECTABLE_STATUSES:
            row["tree_sha"] = trees[repo_id]["tree_sha"]
        else:
            # A pre-pin NOT_FOUND/FAILED row has no verified tree.  Do not
            # carry the legacy commit SHA forward as if it were a tree.
            row["tree_sha"] = None

    artifact_before = _artifact_signature(source_snapshot)
    artifact_after = _artifact_signature(corrected_snapshot)
    if artifact_before != artifact_after:
        raise RuntimeError("artifact metadata changed during tree correction")

    correction = {
        "type": "tree_sha_metadata_correction",
        "reason": (
            "The source bootstrap used the pinned commit SHA for the Tree API "
            "request and stored the response ref as tree_sha."
        ),
        "source_snapshot_id": args.source_snapshot_id,
        "source_pipeline_run_id": source_snapshot.get("pipeline_run_id"),
        "target_snapshot_id": args.target_snapshot_id,
        "target_pipeline_run_id": args.pipeline_run_id,
        "corrected_record_count": len(correction_rows),
        "resolved_record_count": sum(
            entry["tree_sha"] is not None for entry in trees.values()
        ),
        "unresolved_record_count": sum(
            entry["tree_sha"] is None for entry in trees.values()
        ),
        "eligible_statuses": sorted(CORRECTABLE_STATUSES),
        "artifact_refetch": False,
        "artifact_checksum_signature_before": artifact_before,
        "artifact_checksum_signature_after": artifact_after,
        "candidate_path": str(args.candidate_path),
        "candidate_sha256": candidate_sha,
        "input_root": input_root,
        "repo_activity_snapshot_uri": input_root,
        "repo_activity_period": {
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-09-01T00:00:00Z",
        },
        "gharchive_raw_input": "hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz",
        "execution_git_sha": args.execution_git_sha,
        "image_digest": image_digest,
        "tree_api_requests": len(correction_rows),
        "rate_limit_wait_count": rate_limit_wait_count,
        "rate_limit_wait_seconds": rate_limit_wait_seconds,
        "correction_runtime_seconds": time.monotonic() - started,
    }

    corrected_summary = copy.deepcopy(source_summary)
    corrected_summary["dataset_snapshot_id"] = args.target_snapshot_id
    corrected_summary["pipeline_run_id"] = args.pipeline_run_id
    corrected_summary["generated_at"] = generated_at
    corrected_summary["correction"] = correction

    corrected_failures = copy.deepcopy(source_failures)
    corrected_failures["dataset_snapshot_id"] = args.target_snapshot_id
    corrected_failures["correction"] = {
        "source_snapshot_id": args.source_snapshot_id,
        "source_pipeline_run_id": source_snapshot.get("pipeline_run_id"),
        "reason": correction["reason"],
    }

    payloads = {
        "snapshot": _json_bytes(corrected_snapshot),
        "summary": _json_bytes(corrected_summary),
        "failures": _json_bytes(corrected_failures),
    }
    _validate_snapshot(args.repo_root, corrected_snapshot)
    _publish(
        container=args.hdfs_container,
        target_root=target_root,
        target_snapshot_id=args.target_snapshot_id,
        payloads=payloads,
        correction=correction,
    )
    state["published"] = True
    state["published_snapshot_id"] = args.target_snapshot_id
    state["updated_at"] = _utc_now()
    _atomic_json_write(state_path, state)
    print(
        json.dumps(
            {
                "source_snapshot_id": args.source_snapshot_id,
                "target_snapshot_id": args.target_snapshot_id,
                "pipeline_run_id": args.pipeline_run_id,
                "corrected_record_count": len(correction_rows),
                "resolved_record_count": sum(
                    entry["tree_sha"] is not None for entry in trees.values()
                ),
                "unresolved_record_count": sum(
                    entry["tree_sha"] is None for entry in trees.values()
                ),
                "artifact_signature": artifact_after,
                "candidate_sha256": candidate_sha,
                "target_root": target_root,
                "tree_api_requests": len(correction_rows),
                "rate_limit_wait_count": rate_limit_wait_count,
                "rate_limit_wait_seconds": rate_limit_wait_seconds,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _fetch_commit_tree_batch(
    *, token: str, rows: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], int, float]:
    """Fetch one bounded commit/tree batch in a GraphQL request."""

    definitions: list[str] = []
    variables: dict[str, str] = {}
    aliases: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        repo_name = _required_text(row, "repo_full_name")
        pinned = _required_sha(row, "pinned_commit_sha")
        owner, name = repo_name.split("/", 1)
        owner_key = f"owner{index}"
        name_key = f"name{index}"
        expression_key = f"expression{index}"
        variables[owner_key] = owner
        variables[name_key] = name
        variables[expression_key] = pinned
        definitions.extend(
            [
                f"${owner_key}: String!",
                f"${name_key}: String!",
                f"${expression_key}: String!",
            ]
        )
        aliases.append((f"r{index}", row))

    fields = " ".join(
        f"{alias}: repository("
        f"owner: ${'owner' + alias[1:]}, name: ${'name' + alias[1:]}) "
        f"{{ object(expression: ${'expression' + alias[1:]}) "
        "{ ... on Commit { oid tree { oid } } } }"
        for alias, _ in aliases
    )
    query = (
        f"query({', '.join(definitions)}) {{ {fields} "
        "rateLimit { cost remaining resetAt } }"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gitjob-repo-snapshot-tree-correction/1",
        "Content-Type": "application/json",
    }
    waits = 0
    waited_seconds = 0.0
    while True:
        request = urllib.request.Request(
            GITHUB_GRAPHQL,
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            reset = _header_int(exc.headers, "X-RateLimit-Reset")
            if exc.code in {403, 429} and (
                exc.headers.get("Retry-After") or reset is not None
            ):
                delay = _rate_limit_delay(exc.headers, reset)
                waits += 1
                waited_seconds += delay
                print(
                    f"rate-limit wait {delay:.0f}s (GraphQL batch)",
                    flush=True,
                )
                time.sleep(delay)
                continue
            if exc.code in {500, 502, 503, 504}:
                time.sleep(5.0)
                continue
            raise RuntimeError(
                f"GitHub GraphQL tree lookup failed status={exc.code}"
            ) from exc
        if not isinstance(payload, dict):
            raise TypeError("GitHub GraphQL response is not an object")
        errors = payload.get("errors")
        error_by_alias: dict[str, str] = {}
        if errors:
            if not isinstance(errors, list):
                raise RuntimeError("GitHub GraphQL errors must be a list")
            for error in errors:
                path = error.get("path") if isinstance(error, dict) else None
                alias = path[0] if isinstance(path, list) and path else None
                if not isinstance(alias, str) or alias not in {
                    item[0] for item in aliases
                }:
                    raise RuntimeError(
                        f"GitHub GraphQL tree lookup errors: {errors!r}"
                    )
                error_by_alias[alias] = str(
                    error.get("type") or error.get("message") or "GRAPHQL_ERROR"
                )
        data = payload.get("data")
        if data is None and error_by_alias:
            data = {}
        if not isinstance(data, dict):
            raise TypeError("GitHub GraphQL response has no data")
        rate = data.get("rateLimit")
        remaining = rate.get("remaining") if isinstance(rate, dict) else None
        reset_at = rate.get("resetAt") if isinstance(rate, dict) else None
        results: dict[str, dict[str, Any]] = {}
        for alias, row in aliases:
            repo_id = str(row["github_repo_id"])
            pinned = _required_sha(row, "pinned_commit_sha")
            if alias in error_by_alias:
                results[repo_id] = {
                    "repo_full_name": _required_text(row, "repo_full_name"),
                    "pinned_commit_sha": pinned,
                    "tree_sha": None,
                    "lookup_error": error_by_alias[alias],
                }
                continue
            alias_payload = data.get(alias)
            object_payload = (
                alias_payload.get("object") if isinstance(alias_payload, dict) else None
            )
            tree = (
                object_payload.get("tree") if isinstance(object_payload, dict) else None
            )
            tree_sha = tree.get("oid") if isinstance(tree, dict) else None
            lookup_error = None
            object_oid = (
                object_payload.get("oid")
                if isinstance(object_payload, dict)
                else None
            )
            if object_oid != pinned:
                lookup_error = "COMMIT_SHA_MISMATCH"
                tree_sha = None
            elif not isinstance(tree_sha, str) or not TREE_SHA_PATTERN.fullmatch(
                tree_sha
            ):
                lookup_error = "TREE_SHA_MISSING"
                tree_sha = None
            elif tree_sha == pinned:
                lookup_error = "TREE_SHA_EQUALS_COMMIT"
                tree_sha = None
            results[repo_id] = {
                "repo_full_name": _required_text(row, "repo_full_name"),
                "pinned_commit_sha": pinned,
                "tree_sha": tree_sha,
                "lookup_error": lookup_error,
            }
        if isinstance(remaining, int) and remaining <= 0:
            delay = _graphql_rate_limit_delay(reset_at)
            waits += 1
            waited_seconds += delay
            print(f"rate-limit wait {delay:.0f}s (GraphQL)", flush=True)
            time.sleep(delay)
        return results, waits, waited_seconds


def _publish(
    *,
    container: str,
    target_root: str,
    target_snapshot_id: str,
    payloads: dict[str, bytes],
    correction: dict[str, Any],
) -> None:
    if _hdfs_exists(container, target_root):
        raise RuntimeError(f"target Snapshot appeared during correction: {target_root}")
    staging_root = f"{target_root}.staging"
    if _hdfs_exists(container, staging_root):
        raise RuntimeError(f"staging Snapshot already exists: {staging_root}")
    _hdfs_run(container, "-mkdir", "-p", staging_root)
    uris = {
        name: f"hdfs://{staging_root}/{filename}"
        for name, filename in (
            ("snapshot", "snapshot.json"),
            ("summary", "run-summary.json"),
            ("failures", "failures.json"),
        )
    }
    names = {
        "snapshot": "snapshot.json",
        "summary": "run-summary.json",
        "failures": "failures.json",
    }
    for name, content in payloads.items():
        path = f"{staging_root}/{names[name]}"
        _hdfs_put(container, path, content)
        if _hdfs_cat(container, path) != content:
            raise RuntimeError(f"HDFS read-back mismatch: {name}")

    manifest = {
        "schema_version": "github-repo-snapshot-publish-manifest/v1",
        "dataset_snapshot_id": target_snapshot_id,
        "source_snapshot_id": correction["source_snapshot_id"],
        "correction": correction,
        "objects": {
            name: {
                "uri": uri.replace(staging_root, target_root),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, (uri, content) in (
                (name, (uris[name], payloads[name])) for name in payloads
            )
        },
    }
    manifest_bytes = _json_bytes(manifest)
    _hdfs_put(container, f"{staging_root}/_SUCCESS.json", manifest_bytes)
    if _hdfs_cat(container, f"{staging_root}/_SUCCESS.json") != manifest_bytes:
        raise RuntimeError("HDFS read-back mismatch: success manifest")
    _hdfs_run(container, "-mv", staging_root, target_root)


def _validate_snapshot(repo_root: Path, payload: dict[str, Any]) -> None:
    sys.path.insert(0, str(repo_root / "AI"))
    try:
        from github.contracts import (  # pylint: disable=import-outside-toplevel
            GitHubRepoSnapshotBatch,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "pydantic":
            raise
        _validate_snapshot_shape(payload)
        return

    GitHubRepoSnapshotBatch.model_validate(payload)


def _validate_snapshot_shape(payload: dict[str, Any]) -> None:
    """Validate the v1 fields when the remote runner lacks pydantic."""

    if payload.get("schema_version") != "github-repo-snapshot/v1":
        raise ValueError("unsupported Snapshot schema_version")
    records = payload.get("records")
    if not isinstance(records, list):
        raise TypeError("Snapshot records must be a list")
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Snapshot record must be an object")
        repo_id = record.get("github_repo_id")
        if not isinstance(repo_id, int) or isinstance(repo_id, bool) or repo_id < 1:
            raise ValueError("Snapshot github_repo_id must be a positive integer")
        for key in ("pinned_commit_sha", "tree_sha"):
            value = record.get(key)
            if value is not None and (
                not isinstance(value, str) or not TREE_SHA_PATTERN.fullmatch(value)
            ):
                raise ValueError(f"Snapshot {key} must be a Git SHA or null")
        if record.get("collection_status") not in {
            "COMPLETE",
            "PARTIAL",
            "FAILED",
            "REUSED",
        }:
            raise ValueError("Snapshot collection_status is invalid")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            raise TypeError("Snapshot artifacts must be a list")
        paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise TypeError("Snapshot artifact must be an object")
            path = artifact.get("path")
            content_hash = artifact.get("content_hash")
            if not isinstance(path, str) or not path or path in paths:
                raise ValueError("Snapshot artifact paths must be unique/non-blank")
            if (
                not isinstance(content_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", content_hash)
            ):
                raise ValueError("Snapshot artifact content_hash is invalid")
            paths.add(path)


def _artifact_signature(payload: dict[str, Any]) -> str:
    rows: list[tuple[Any, ...]] = []
    for record in payload.get("records", []):
        for artifact in record.get("artifacts", []):
            rows.append(
                (
                    record.get("github_repo_id"),
                    artifact.get("artifact_type"),
                    artifact.get("path"),
                    artifact.get("uri"),
                    artifact.get("content_hash"),
                    artifact.get("size_bytes"),
                )
            )
    serialized = json.dumps(sorted(rows), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_state(
    path: Path, args: argparse.Namespace, source: dict[str, Any]
) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("source_snapshot_id") != args.source_snapshot_id:
            raise ValueError("tree correction state source snapshot mismatch")
        if state.get("target_snapshot_id") != args.target_snapshot_id:
            raise ValueError("tree correction state target snapshot mismatch")
        return state
    return {
        "source_snapshot_id": args.source_snapshot_id,
        "source_pipeline_run_id": source.get("pipeline_run_id"),
        "target_snapshot_id": args.target_snapshot_id,
        "pipeline_run_id": args.pipeline_run_id,
        "trees": {},
        "rate_limit_wait_count": 0,
        "rate_limit_wait_seconds": 0.0,
        "published": False,
        "updated_at": _utc_now(),
    }


def _read_env_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if value:
                return value
    raise ValueError(f"missing {key} in {path}")


def _required_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-blank")
    return value


def _required_sha(row: dict[str, Any], key: str) -> str:
    value = _required_text(row, key)
    if not TREE_SHA_PATTERN.fullmatch(value):
        raise ValueError(f"{key} must be a lowercase Git SHA")
    return value


def _rate_limit_delay(headers: Any, reset: int | None) -> float:
    retry_after = _header_int(headers, "Retry-After")
    if retry_after is not None:
        return max(1.0, float(retry_after))
    if reset is None:
        raise RuntimeError("GitHub rate limit response has no reset time")
    return max(1.0, float(reset) - time.time() + 5.0)


def _graphql_rate_limit_delay(reset_at: object) -> float:
    if not isinstance(reset_at, str):
        raise TypeError("GitHub GraphQL rate limit response has no reset time")
    try:
        reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise RuntimeError("invalid GitHub GraphQL rate limit reset time") from exc
    return max(1.0, reset - time.time() + 5.0)


def _header_int(headers: Any, name: str) -> int | None:
    value = headers.get(name) if headers is not None else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hdfs_path(root: str, snapshot_id: str) -> str:
    return f"{root.rstrip('/')}/snapshot_id={snapshot_id}"


def _hdfs_exists(container: str, path: str) -> bool:
    return (
        subprocess.run(
            ["docker", "exec", container, "hdfs", "dfs", "-test", "-e", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _hdfs_run(container: str, *arguments: str) -> None:
    subprocess.run(
        ["docker", "exec", container, "hdfs", "dfs", *arguments],
        check=True,
    )


def _hdfs_cat(container: str, path: str) -> bytes:
    return subprocess.check_output(
        ["docker", "exec", container, "hdfs", "dfs", "-cat", path]
    )


def _hdfs_put(container: str, path: str, content: bytes) -> None:
    subprocess.run(
        ["docker", "exec", "-i", container, "hdfs", "dfs", "-put", "-", path],
        input=content,
        check=True,
    )


def _read_hdfs_json(container: str, path: str) -> dict[str, Any]:
    payload = json.loads(_hdfs_cat(container, path))
    if not isinstance(payload, dict):
        raise TypeError(f"HDFS JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
