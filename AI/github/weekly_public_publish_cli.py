"""Publish one week's PUBLIC bundle to HDFS and hand the exporter its repo-id source.

`weekly_cohort_snapshot` builds the four objects a weekly PUBLIC publication is
made of, but it stops at bytes in memory: it has no caller that puts them where
`github.snapshot_input.load_published_snapshot` will find them. The B1 weeks
(2026-03-09 .. 2026-03-30) were published on 2026-09-20 by a wrapper that lived
outside this repository and is gone, which is why the remaining weeks cannot be
published the same way. This module is that caller, written against the same
primitives the lost wrapper demonstrably used, and it is deliberately thin:
build, store, look up the head, write one file.

### Why the marker is stored last

`load_published_snapshot` reads `_SUCCESS.json` first and follows it to the
three objects it names. Storing it last is what makes its presence mean "every
byte this marker names is already there". A run that dies half way leaves no
marker, so the partial directory is not a publication and no reader will treat
it as one. `common.webhdfs.store_immutable` compares bytes when the destination
exists, so re-running with the same inputs re-stores nothing and re-running
with different inputs fails on the changed object -- before the marker, which
still describes the publication C may already have read.

### Why the repo-id source is the PUBLIC result and never the bundle

`export_c_archive_activity` filters rows by `included_in_denominator` only for
`c-public-published-result/v1` and `c-public-repo-analysis/v1|v2`. Handed a
`github-repo-snapshot/v1` bundle it takes every record id, and a bundle holds
the week's whole candidate cohort -- thousands of repositories C later excluded
from the denominator. Those ids reach the export, `WeeklyActivityConsumer`
rejects it with "weekly export rows are outside selected PUBLIC_GITHUB", and a
rejection commits the offset: the week is lost rather than retried.

So the source is whatever `ComputeStore.select_public_snapshot` returns for
that week. That is not merely a correct answer, it is the *same* answer the
consumer will compute when it reads the export, because it is the same call.

### What this module deliberately does not do

It does not edit `C_INTAKE_CONFIG`, restart the worker, or run Spark. A
publication becomes a `PUBLIC_GITHUB` head only once an operator declares its
root in the intake configuration (one entry per publication, at most eight) and
the worker restarts; and the export runs from the Spark image, which has none
of this package. Both belong to the runbook, and putting either behind a flag
here would let one command change a shared worker's configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from github.weekly_cohort_snapshot import (
    MARKER_FILE,
    PUBLISHED_OBJECTS,
    WeeklyCohortPublication,
    build_weekly_cohort_publication,
    select_cohort_records,
)

MAX_INPUT_BYTES = 256 * 1024 * 1024
PUBLIC_RESULT_SCHEMAS = frozenset(
    {
        "c-public-published-result/v1",
        "c-public-repo-analysis/v1",
        "c-public-repo-analysis/v2",
    }
)


class PublicHeadMissing(RuntimeError):
    """No PUBLIC_GITHUB head covers this week yet."""


@dataclass(frozen=True)
class PublishResult:
    """Where each object landed, and whether anything new was written."""

    stored_uris: dict[str, str]
    republished: bool


def _hdfs_path(publication_root: str) -> str:
    parsed = urlsplit(publication_root)
    if parsed.scheme != "hdfs" or not parsed.path.startswith("/"):
        raise ValueError("publication root must be an absolute hdfs:// URI")
    return parsed.path.rstrip("/")


def publish_publication(
    publication: WeeklyCohortPublication,
    *,
    publisher,
    dry_run: bool = False,
) -> PublishResult:
    """Store the three objects, then the marker, under the publication root."""

    root = _hdfs_path(publication.publication_root)
    if dry_run:
        return PublishResult(stored_uris={}, republished=False)
    names = [name for _, name in PUBLISHED_OBJECTS] + [MARKER_FILE]
    # Asked before the first write, so "nothing changed" is a statement about
    # the publication as the operator found it, not about what this run did.
    already = all(publisher.exists(f"{root}/{name}") for name in names)
    stored: dict[str, str] = {}
    for name in names:
        # The marker is last on purpose: its presence is the claim that every
        # object it names is already stored, so it must not appear while one of
        # them is still missing or being refused for changed bytes.
        stored[name] = publisher.store_immutable(
            f"{root}/{name}", publication.files[name]
        )
    return PublishResult(stored_uris=stored, republished=already)


def write_repo_id_source(
    store,
    destination: Path,
    *,
    week_start: str,
    registry_version: str,
    include_partial: bool,
) -> str:
    """Write the head the weekly consumer will select, for the exporter to read."""

    selection = store.select_public_snapshot(
        registry_version=registry_version,
        include_partial=include_partial,
        week_start=week_start,
    )
    if selection is None:
        raise PublicHeadMissing(
            f"no PUBLIC_GITHUB head covers {week_start} for registry "
            f"{registry_version} with include_partial={include_partial}"
        )
    snapshot_id, payload = selection
    if not isinstance(payload, Mapping):
        raise TypeError("stored PUBLIC payload must be an object")
    schema = payload.get("schema_version")
    if schema not in PUBLIC_RESULT_SCHEMAS:
        raise ValueError(
            "stored PUBLIC payload carries an unsupported schema_version: "
            f"{schema!r}; the exporter would not filter it by denominator"
        )
    # Written whole. The exporter needs `included_in_denominator` on every row
    # to drop the excluded ones itself; a pre-filtered id list would lose that
    # flag and silently widen the export.
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return snapshot_id


def _read_json(path: Path) -> object:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the bounded read budget: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _cohort_source(path: Path) -> tuple[list, object, object]:
    value = _read_json(path)
    records = value.get("records") if isinstance(value, dict) else value
    if not isinstance(records, list):
        raise TypeError("cohort snapshot must hold a records array: " + str(path))
    policy = value.get("collection_policy") if isinstance(value, dict) else None
    collector = value.get("collector_version") if isinstance(value, dict) else None
    return records, policy, collector


def _week_activity(path: Path, week_start: str) -> dict[int, int]:
    activity: dict[int, int] = {}
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError("activity row " + str(number) + " is not an object")
            if str(row.get("week_start")) != week_start:
                raise ValueError(
                    "activity row "
                    + str(number)
                    + " has week_start "
                    + str(row.get("week_start"))
                    + ", expected "
                    + week_start
                )
            repo_id, events = row.get("repo_id"), row.get("event_count")
            for value in (repo_id, events):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError("activity row " + str(number) + " is not numeric")
            if repo_id in activity:
                raise ValueError("duplicate repo_id in activity rows: " + str(repo_id))
            activity[repo_id] = events
    if not activity:
        raise ValueError("activity rows must not be empty")
    return activity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one week's PUBLIC bundle and write its export repo-id source"
    )
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--cohort-snapshot", required=True, action="append", type=Path)
    parser.add_argument("--week-activity", required=True, type=Path)
    parser.add_argument("--dataset-snapshot-id", required=True)
    parser.add_argument("--pipeline-run-id", required=True)
    parser.add_argument("--publication-root", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--artifact-uri-prefix", action="append", default=[])
    parser.add_argument("--webhdfs-url")
    parser.add_argument("--webhdfs-user", default="hadoop")
    parser.add_argument("--webhdfs-timeout", type=float, default=120.0)
    parser.add_argument(
        "--repo-ids-out",
        type=Path,
        help="write the selected PUBLIC head here for export_c_archive_activity",
    )
    parser.add_argument("--registry-version")
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _build(arguments) -> WeeklyCohortPublication:
    loaded = [_cohort_source(path) for path in arguments.cohort_snapshot]
    activity = _week_activity(arguments.week_activity, arguments.week_start)
    policy, collector = next(
        (
            (policy, collector)
            for _, policy, collector in loaded
            if isinstance(policy, dict) and isinstance(collector, str)
        ),
        (None, None),
    )
    if policy is None:
        raise ValueError(
            "a cohort snapshot must carry collection_policy and collector_version"
        )
    return build_weekly_cohort_publication(
        week_start=arguments.week_start,
        cohort_records=select_cohort_records([records for records, _, _ in loaded]),
        week_activity=activity,
        collection_policy=policy,
        collector_version=collector,
        dataset_snapshot_id=arguments.dataset_snapshot_id,
        pipeline_run_id=arguments.pipeline_run_id,
        generated_at=datetime.fromisoformat(arguments.generated_at),
        publication_root=arguments.publication_root,
        artifact_uri_prefixes=tuple(arguments.artifact_uri_prefix),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.dry_run and not arguments.webhdfs_url:
        print("--webhdfs-url is required unless --dry-run", file=sys.stderr)
        return 2
    if arguments.repo_ids_out is not None and not arguments.registry_version:
        print("--registry-version is required with --repo-ids-out", file=sys.stderr)
        return 2
    try:
        publication = _build(arguments)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2

    report = {
        "week_start": publication.week_start,
        "dataset_snapshot_id": publication.dataset_snapshot_id,
        "publication_root": publication.publication_root,
        "record_count": publication.record_count,
        "objects": {
            name: len(body) for name, body in sorted(publication.files.items())
        },
    }
    if arguments.dry_run:
        print(json.dumps({**report, "status": "DRY_RUN"}, ensure_ascii=False))
        return 0

    import os

    from common.webhdfs import WebHdfsClient, parse_datanode_hosts

    publisher = WebHdfsClient(
        arguments.webhdfs_url,
        user=arguments.webhdfs_user,
        timeout=arguments.webhdfs_timeout,
        datanode_hosts=parse_datanode_hosts(os.environ.get("WEBHDFS_DATANODE_HOSTS")),
    )
    try:
        result = publish_publication(publication, publisher=publisher)
    except FileExistsError as error:
        print(
            "publication root already holds different bytes; publish a new "
            f"--dataset-snapshot-id instead of overwriting: {error}",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(
            f"publication failed before the completion marker: {error}", file=sys.stderr
        )
        return 1
    report.update(status="PUBLISHED", republished=result.republished)

    if arguments.repo_ids_out is not None:
        from worker.api import configured_database_url
        from worker.store import ComputeStore

        store = ComputeStore(configured_database_url())
        try:
            snapshot_id = write_repo_id_source(
                store,
                arguments.repo_ids_out,
                week_start=arguments.week_start,
                registry_version=arguments.registry_version,
                include_partial=arguments.include_partial,
            )
        except PublicHeadMissing as error:
            report.update(status="PUBLISHED_HEAD_PENDING", head_reason=str(error))
            print(json.dumps(report, ensure_ascii=False))
            return 3
        report.update(
            public_snapshot_id=snapshot_id, repo_ids_out=str(arguments.repo_ids_out)
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
