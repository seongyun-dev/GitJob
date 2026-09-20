"""Explicit one-shot validation and publication of the current job projection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from job.input_union import prepare_input_union
from job.projection import materialize_job_projection
from registry.mapper import RegistryMapper
from worker.api import configured_database_url, default_registry
from worker.intake import IntakeConfig, IntakeRunner, _read, load_job_output
from worker.job_hdfs_source import refresher
from worker.store import ComputeStore


def prepare_projection(config_path: Path):
    """Discover and verify the same immutable sources used by the intake runner."""

    config = IntakeConfig.model_validate_json(_read(config_path, 1024 * 1024))
    runner = IntakeRunner(config, job_sink=lambda *_: None)
    if config.job_hdfs_sources:
        runner.job_source_refresh = refresher(config.job_hdfs_sources, strict=True)
        report = {"completed": 0, "failed": 0, "blocked": 0, "pending": 0}
        runner._refresh_job_sources(report)
        if report["failed"]:
            raise RuntimeError("job source refresh failed")
        missing_sources = [
            source
            for configured in config.job_hdfs_sources
            for source in configured.sources
            if not any(
                configured.source_root(source).glob("*/manifest.json")
            )
        ]
        if missing_sources:
            raise RuntimeError(
                "job source coverage is incomplete: "
                + ", ".join(sorted(set(missing_sources)))
            )
    outputs = []
    for manifest, root in runner._manifests():
        output = load_job_output(manifest, root)
        if output.collection_issues:
            raise ValueError("verified input set contains blocked collector output")
        outputs.append(output)
    if not outputs:
        raise ValueError("no completed job inputs were discovered")
    runner._validate_job_set_capacity(outputs)
    criteria = next(iter(runner._latest_projection_criteria(outputs)), None)
    if criteria is None:
        raise ValueError("no active matching criteria is configured")
    registry = default_registry(dsn=configured_database_url())
    prepared = prepare_input_union(tuple(outputs), criteria, RegistryMapper(registry))
    return prepared, criteria, config


def build_projection(config_path: Path):
    prepared, _, _ = prepare_projection(config_path)
    return materialize_job_projection(prepared)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Intake config path; defaults to C_INTAKE_CONFIG",
    )
    args = parser.parse_args()
    config_path = args.config or (
        Path(value) if (value := os.environ.get("C_INTAKE_CONFIG")) else None
    )
    if config_path is None:
        parser.error("--config or C_INTAKE_CONFIG is required")
    projection = build_projection(config_path)
    result = {
        "mode": "dry-run" if args.dry_run else "publish",
        "projection_version_id": projection.projection_version_id,
        "job_count": len(projection.jobs),
        "fact_count": len(projection.facts),
        "source_counts": {
            source: sum(job.source_site == source for job in projection.jobs)
            for source in sorted({job.source_site for job in projection.jobs})
        },
        "build_stats": projection.build_stats,
    }
    if args.publish:
        dsn = os.environ.get("C_COMPUTE_DATABASE_URL")
        if not dsn:
            parser.error("C_COMPUTE_DATABASE_URL is required for --publish")
        ComputeStore(dsn).publish_job_projection(projection)
        result["published"] = True
    else:
        result["published"] = False
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
