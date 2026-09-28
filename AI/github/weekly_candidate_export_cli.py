"""Turn a bounded Weekly row export into the Weekly candidate contract.

`weekly_artifact_resolver.py` has always been able to build candidates —
`build_weekly_candidates()` is right there — but nothing called it outside
tests, so `--candidates` had no producer and the Weekly Artifact run could not
start (S15P21E102-276). This CLI is that producer.

## Why two steps

`Infra/spark/jobs/weekly_candidate_export.py` does the wide read because the
Spark image copies `Infra/spark` and cannot import this package. It emits rows
only. Ranking, the schema and every rejection rule stay here, on
`build_weekly_candidates()`, so there is exactly one place that decides what a
Weekly candidate is. This CLI deliberately writes no ranking logic of its own.

## Why the manifest is checked first

The rows are a read-back of a published week. `_SUCCESS.json` is what says
that week finished and names the bytes it finished with
(`weekly_activity_publish.build_manifest`). Exporting candidates from a week
whose manifest is missing would hand the resolver a pool drawn from a
half-written snapshot, and the resolver has no way to notice. Checking the
manifest is cheap and it is the only thing standing between a partial Spark
write and a full Artifact run.

## What this does not decide

Whether a repository is reachable, has artifacts, or is NOT_FOUND is the
resolver's judgement (S15P21E102-274). A candidate here is a ranked row and
nothing more.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from github.weekly_artifact_resolver import (
    WEEKLY_CANDIDATE_SCHEMA,
    build_weekly_candidates,
)

EXPORT_SCHEMA_VERSION = "repo-activity-weekly-candidate-rows/v1"
DEFAULT_CANDIDATE_POOL_LIMIT = 1_500


def load_export_rows(path: Path) -> tuple[list[dict[str, Any]], str, str]:
    """Read the Spark rows export, refusing anything that is not that export."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("weekly row export must be an object")
    if payload.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ValueError("unsupported weekly row export schema_version")
    input_root = payload.get("input_root")
    if not isinstance(input_root, str) or not input_root.strip():
        raise ValueError("weekly row export input_root must not be blank")
    week_start = payload.get("week_start")
    if not isinstance(week_start, str) or not week_start.strip():
        raise ValueError("weekly row export week_start must not be blank")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("weekly row export must contain rows")
    return list(rows), input_root, week_start


def assert_week_is_published(client: Any, manifest_uri: str) -> None:
    """The week must carry a readable `_SUCCESS.json` before it is exported."""

    raw = client.read(manifest_uri)
    manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"weekly manifest is not an object: {manifest_uri}")
    if not manifest.get("dataset_snapshot_id"):
        raise ValueError(f"weekly manifest has no dataset_snapshot_id: {manifest_uri}")


def render_candidate_document(candidate_set: Any) -> dict[str, Any]:
    """Serialise to exactly what `load_weekly_candidates()` accepts.

    `monthly_event_sha` is absent rather than null on purpose: the loader
    rejects the key even when it carries no value, which is what keeps a
    Historical-shaped payload out of the Weekly adapter.
    """

    return {
        "schema_version": WEEKLY_CANDIDATE_SCHEMA,
        "input_root": candidate_set.input_root,
        "week_start": candidate_set.week_start.isoformat(),
        "candidates": [
            {
                "rank": candidate.activity_rank,
                "repo_id": candidate.repo_id,
                "repo_name": candidate.repo_name,
                "event_count": candidate.activity_count,
            }
            for candidate in candidate_set.candidates
        ],
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError("value must be positive")
    return parsed


def _positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None else _positive_int(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build repo-activity-weekly-candidates/v1 from a bounded Weekly "
            "row export."
        )
    )
    parser.add_argument(
        "--rows",
        type=Path,
        required=True,
        help="Rows JSON written by Infra/spark/jobs/weekly_candidate_export.py.",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Destination candidate JSON."
    )
    parser.add_argument(
        "--candidate-pool-limit",
        type=_positive_int,
        default=_positive_env(
            "WEEKLY_CANDIDATE_POOL_LIMIT", DEFAULT_CANDIDATE_POOL_LIMIT
        ),
        help="Maximum rank-ordered candidates to emit.",
    )
    parser.add_argument(
        "--manifest-uri",
        help=(
            "`_SUCCESS.json` of the exported week. Checked before writing so a "
            "half-published week cannot become a candidate pool."
        ),
    )
    parser.add_argument("--webhdfs-url", default=os.environ.get("WEBHDFS_URL"))
    parser.add_argument("--webhdfs-user", default=os.environ.get("WEBHDFS_USER"))
    parser.add_argument("--webhdfs-timeout", type=float, default=120.0)
    parser.add_argument(
        "--skip-manifest-check",
        action="store_true",
        help="Only for a week whose manifest is verified out of band.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    rows, input_root, week_start = load_export_rows(arguments.rows)

    if not arguments.skip_manifest_check:
        if not arguments.manifest_uri:
            raise SystemExit(
                "--manifest-uri is required unless --skip-manifest-check is set"
            )
        if not arguments.webhdfs_url:
            raise SystemExit("--webhdfs-url or WEBHDFS_URL is required")
        from common.webhdfs import WebHdfsClient

        # `user` has a default on the client; passing None would replace it
        # with None rather than fall back to it.
        options: dict[str, Any] = {
            "base_url": arguments.webhdfs_url,
            "timeout": arguments.webhdfs_timeout,
        }
        if arguments.webhdfs_user:
            options["user"] = arguments.webhdfs_user
        client = WebHdfsClient(**options)
        assert_week_is_published(client, arguments.manifest_uri)

    candidate_set = build_weekly_candidates(
        rows,
        input_root=input_root,
        week_start=week_start,
        limit=arguments.candidate_pool_limit,
    )
    document = render_candidate_document(candidate_set)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "week_start": document["week_start"],
                "input_root": document["input_root"],
                "candidate_count": len(document["candidates"]),
                "candidate_pool_limit": arguments.candidate_pool_limit,
                "output": str(arguments.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI delegation
    raise SystemExit(main())
