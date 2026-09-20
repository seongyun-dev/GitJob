"""Compare 100 deterministic selectors before enabling projection reads."""

from __future__ import annotations

import argparse
import json
import os
from itertools import product
from pathlib import Path

from job.cohort import SUPPORTED_JOB_ROLES, CohortCriteria, CohortPurpose
from job.demand import aggregate_demand
from job.input_union import build_prepared_input_union
from job.projection import aggregate_projection_demand, materialize_job_projection
from worker.job_projection_backfill import prepare_projection
from worker.projection_shadow import compare_demands


def selector_matrix(as_of, *, market_sources=()) -> tuple[CohortCriteria, ...]:
    regions = ((), ("서울",), ("경기",), ("서울", "경기"))
    careers = ((), ("신입",), ("경력",), ("신입", "경력"), ("경력무관",))
    active = [
        CohortCriteria(
            target_role=role,
            as_of=as_of,
            regions=region,
            career_levels=career,
        )
        for role, region, career in product(SUPPORTED_JOB_ROLES, regions, careers)
    ]
    market = CohortCriteria(
        target_role=None,
        purpose=CohortPurpose.CURRENT_MARKET,
        as_of=as_of,
        sources=market_sources,
    )
    return (*active[:99], market)


def validate_selectors(prepared, projection, selectors) -> list[dict[str, object]]:
    mismatches = []
    for index, criteria in enumerate(selectors):
        cohort = build_prepared_input_union(prepared, criteria)
        legacy = aggregate_demand(cohort)
        projected = aggregate_projection_demand(projection, criteria)
        legacy_ids = (
            tuple(sorted(job.job_id for job in cohort.matching_jobs or ()))
            if criteria.purpose is CohortPurpose.ACTIVE_MATCHING
            else None
        )
        fields = compare_demands(
            legacy,
            projected.snapshot,
            legacy_job_ids=legacy_ids,
            projected_job_ids=projected.selected_job_ids,
        )
        if fields:
            mismatches.append(
                {
                    "index": index,
                    "criteria": criteria.model_dump(mode="json"),
                    "fields": fields,
                }
            )
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    config_path = args.config or (
        Path(value) if (value := os.environ.get("C_INTAKE_CONFIG")) else None
    )
    if config_path is None:
        parser.error("--config or C_INTAKE_CONFIG is required")
    prepared, criteria, config = prepare_projection(config_path)
    projection = materialize_job_projection(prepared)
    market_sources = next(
        (
            item.sources
            for item in config.criteria
            if item.purpose is CohortPurpose.CURRENT_MARKET
        ),
        (),
    )
    selectors = selector_matrix(criteria.as_of, market_sources=market_sources)
    mismatches = validate_selectors(prepared, projection, selectors)
    print(
        json.dumps(
            {
                "projection_version_id": projection.projection_version_id,
                "selector_count": len(selectors),
                "mismatch_count": len(mismatches),
                "mismatches": mismatches,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
