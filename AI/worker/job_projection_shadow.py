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
from job.projection import (
    aggregate_projection_demand,
    canonical_hash,
    materialize_job_projection,
)
from worker.job_projection_backfill import prepare_projection
from worker.job_projection_store import JobProjectionStore
from worker.postgres_env import dsn_from_postgres_env
from worker.projection_shadow import compare_demands


def selector_matrix(as_of, *, market_sources=()) -> tuple[CohortCriteria, ...]:
    # The rollout contract is deliberately stratified: 80 personalized selectors
    # plus 20 Current Market selectors. Nationwide and unknown-normalization cases
    # guard the SQL/Python prefilter boundary rather than relying on random inputs.
    active_filters = (
        ((), ()),
        (("서울",), ()),
        (("경기",), ()),
        (("서울", "경기"), ()),
        (("전국",), ()),
        (("원격",), ()),
        ((), ("신입",)),
        ((), ("경력",)),
        ((), ("신입", "경력")),
        ((), ("경력무관",)),
        ((), ("협의",)),
        (("서울",), ("신입",)),
        (("서울",), ("경력",)),
        (("서울", "경기"), ("신입", "경력")),
        (("전국",), ("경력무관",)),
        (("원격",), ("협의",)),
    )
    active = [
        CohortCriteria(
            target_role=role,
            as_of=as_of,
            regions=region,
            career_levels=career,
        )
        for role, (region, career) in product(SUPPORTED_JOB_ROLES, active_filters)
    ]
    market_regions = (
        (),
        ("서울",),
        ("서울", "경기"),
        ("전국",),
        ("원격",),
    )
    market_careers = ((), ("신입",), ("신입", "경력"), ("협의",))
    market = [
        CohortCriteria(
            target_role=None,
            purpose=CohortPurpose.CURRENT_MARKET,
            as_of=as_of,
            sources=market_sources,
            regions=region,
            career_levels=career,
        )
        for region, career in product(market_regions, market_careers)
    ]
    return (*active, *market)


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


def validate_persisted_selectors(
    store: JobProjectionStore,
    projection_version_id: str,
    selectors,
    *,
    completed: dict[str, dict[str, object]] | None = None,
    on_result=None,
) -> list[dict[str, object]]:
    """Compare full Python hydration with exact SQL on one pinned DB version."""

    mismatches = []
    completed = {} if completed is None else completed
    for index, criteria in enumerate(selectors):
        saved = completed.get(str(index))
        if saved is None:
            python_result = store.demand(
                criteria, projection_version_id=projection_version_id
            )
            sql_snapshot = store.summary(
                criteria, projection_version_id=projection_version_id
            )
            sql_job_ids = store.selected_job_keys(
                criteria, projection_version_id=projection_version_id
            )
            fields = compare_demands(
                python_result.snapshot,
                sql_snapshot,
                legacy_job_ids=python_result.selected_job_ids,
                projected_job_ids=sql_job_ids,
            )
            basis_fields = (
                "cohort_id",
                "dataset_snapshot_id",
                "pipeline_run_id",
                "collector_version",
                "registry_version",
                "parser_version",
                "quality_version",
                "aggregation_version",
                "projection_version_id",
            )
            fields = (
                *fields,
                *(
                    field
                    for field in basis_fields
                    if getattr(python_result.snapshot, field)
                    != getattr(sql_snapshot, field)
                ),
            )
            saved = {
                "criteria": criteria.model_dump(mode="json"),
                "fields": list(fields),
            }
            completed[str(index)] = saved
            if on_result is not None:
                on_result(index, completed)
        else:
            fields = tuple(saved.get("fields", ()))
        if fields:
            mismatches.append(
                {
                    "index": index,
                    "criteria": saved["criteria"],
                    "fields": fields,
                }
            )
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--persisted",
        action="store_true",
        help="Compare Python and SQL against the currently published DB head",
    )
    parser.add_argument(
        "--from-postgres-env",
        action="store_true",
        help="Build the persisted-mode DSN from explicit POSTGRES_* variables",
    )
    parser.add_argument(
        "--projection-version-id",
        help="Fail unless this exact version is still the published head",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Persist each selector result for audit and interrupted-run resume",
    )
    args = parser.parse_args()
    if args.persisted:
        if args.projection_version_id is None or args.checkpoint is None:
            parser.error(
                "persisted mode requires --projection-version-id and --checkpoint"
            )
        dsn = (
            dsn_from_postgres_env()
            if args.from_postgres_env
            else os.environ.get("C_COMPUTE_DATABASE_URL")
        )
        if not dsn:
            parser.error(
                "persisted mode requires C_COMPUTE_DATABASE_URL or "
                "--from-postgres-env"
            )
        store = JobProjectionStore(dsn)
        head = store.head()
        if head is None:
            parser.error("published job projection head is unavailable")
        projection_version_id = head["projection_version_id"]
        if (
            args.projection_version_id
            and args.projection_version_id != projection_version_id
        ):
            parser.error("published projection head changed before validation")
        selectors = selector_matrix(
            head["observed_at"], market_sources=("JOBKOREA", "SARAMIN")
        )
        selector_documents = [
            item.model_dump(mode="json") for item in selectors
        ]
        selector_hash = canonical_hash(selector_documents)
        completed: dict[str, dict[str, object]] = {}
        if args.checkpoint.exists():
            checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
            if (
                checkpoint.get("projection_version_id") != projection_version_id
                or checkpoint.get("selector_hash") != selector_hash
            ):
                parser.error("checkpoint belongs to another projection or selector set")
            completed = dict(checkpoint.get("completed", {}))

        def save_checkpoint(_index, results) -> None:
            payload = {
                "projection_version_id": projection_version_id,
                "selector_hash": selector_hash,
                "selectors": selector_documents,
                "completed": results,
            }
            args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.checkpoint.with_suffix(args.checkpoint.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(args.checkpoint)

        mismatches = validate_persisted_selectors(
            store,
            projection_version_id,
            selectors,
            completed=completed,
            on_result=save_checkpoint,
        )
        final_head = store.head()
        if (
            final_head is None
            or final_head["projection_version_id"] != projection_version_id
        ):
            parser.error(
                "published projection head changed during persisted validation"
            )
        print(
            json.dumps(
                {
                    "mode": "persisted-sql",
                    "projection_version_id": projection_version_id,
                    "selector_count": len(selectors),
                    "selector_hash": selector_hash,
                    "selectors": selector_documents,
                    "checkpoint": str(args.checkpoint),
                    "completed_count": len(completed),
                    "mismatch_count": len(mismatches),
                    "mismatches": mismatches,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if mismatches:
            raise SystemExit(1)
        return
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
                "mode": "prepared-python",
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
