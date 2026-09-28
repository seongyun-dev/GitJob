import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from github.contracts import RepoCollectionStatus
from github.public_analysis import (
    ArtifactAnalysis,
    LanguageAnalysis,
    PublicBatchResult,
    PublicRepoResult,
    TechnologyObservation,
)
from registry.contracts import TechnologyRegistry
from registry.mapper import MatchStatus
from trend.archive import (
    ArchiveActivityMetadata,
    ArchivePeriodInput,
    PeriodGranularity,
    archive_trend,
    iter_bounded_activity_file,
    iter_bounded_activity_stream,
)
from trend.contracts import TrendStatus
from worker.store import digest


@pytest.fixture
def registry() -> TechnologyRegistry:
    return TechnologyRegistry.model_validate_json(
        Path("registry/data/technology_registry_v1.json").read_text(encoding="utf-8")
    )


def _artifact(path: str = "package.json") -> ArtifactAnalysis:
    return ArtifactAnalysis(
        path=path,
        uri=f"hdfs://trusted/public/{path}",
        content_hash="a" * 64,
        size_bytes=20,
        status=TrendStatus.READY,
    )


def _observation(tech_id: str, path: str = "package.json") -> TechnologyObservation:
    return TechnologyObservation(
        tech_id=tech_id,
        basis="PACKAGE",
        raw_value=tech_id,
        scope="dependencies",
        path=path,
        uri=f"hdfs://trusted/public/{path}",
        content_hash="a" * 64,
    )


def _record(
    repo_id: int,
    *,
    tech_ids: tuple[str, ...] = (),
    collection_status: RepoCollectionStatus = RepoCollectionStatus.COMPLETE,
    included: bool = True,
    partial: bool = False,
    exclusion_reasons: tuple[str, ...] = (),
    unresolved: bool = False,
    language_tech_ids: tuple[str, ...] = (),
) -> PublicRepoResult:
    eligible = included
    artifact = _artifact()
    if not included:
        artifact = artifact.model_copy(
            update={
                "status": TrendStatus.INSUFFICIENT_DATA,
                "reason": "COLLECTION_POLICY_EXCLUDED",
            }
        )
    return PublicRepoResult(
        repo_snapshot_id=f"repo-snapshot-{repo_id}",
        github_repo_id=repo_id,
        repo_full_name=f"owner/repo-{repo_id}",
        pinned_commit_sha=f"{repo_id:x}".rjust(40, "0"),
        tree_sha=None,
        activity_metric="gh_archive_event_count",
        activity_period_start="2026-08-01",
        activity_period_end="2026-08-31",
        activity_rank=repo_id,
        activity_count=repo_id,
        collection_status=collection_status,
        collection_issues=("FILE_LIMIT_REACHED",) if partial else (),
        tree_truncated=False,
        observed_tree_entries=10,
        checkpoint_uri=None,
        reused_from_snapshot_id=None,
        language_metadata=tuple(
            {
                "language": tech_id.title(),
                "file_count": 2,
                "representative_paths": (f"src/{tech_id}.one", f"src/{tech_id}.two"),
            }
            for tech_id in language_tech_ids
        ),
        language_observations=tuple(
            LanguageAnalysis(
                language=tech_id.title(),
                file_count=2,
                representative_paths=(f"src/{tech_id}.one", f"src/{tech_id}.two"),
                status=MatchStatus.MATCHED,
                tech_id=tech_id,
                candidates=(tech_id,),
            )
            for tech_id in language_tech_ids
        ),
        eligible=eligible,
        included_in_denominator=included,
        partial_included=partial,
        exclusion_reasons=exclusion_reasons,
        quality_reasons=(),
        status=(TrendStatus.INSUFFICIENT_DATA if unresolved else TrendStatus.READY),
        observations=tuple(_observation(tech_id) for tech_id in tech_ids),
        unresolved=(
            (
                {
                    "raw_value": "unknown-sdk",
                    "basis": "PACKAGE",
                    "status": "NOT_FOUND",
                    "candidates": (),
                    "path": "package.json",
                    "scope": "dependencies",
                },
            )
            if unresolved
            else ()
        ),
        artifacts=(artifact,),
    )


def _public(
    registry: TechnologyRegistry,
    records: tuple[PublicRepoResult, ...],
    *,
    include_partial: bool = False,
    registry_version: str | None = None,
    snapshot_id: str = "public-snapshot",
) -> PublicBatchResult:
    observed: dict[str, set[int]] = {}
    for record in records:
        if not record.included_in_denominator:
            continue
        for observation in record.observations:
            observed.setdefault(observation.tech_id, set()).add(record.github_repo_id)
        for observation in record.language_observations:
            if observation.status is MatchStatus.MATCHED:
                observed.setdefault(observation.tech_id, set()).add(
                    record.github_repo_id
                )
    sample_count = sum(row.included_in_denominator for row in records)
    technologies = [
        {
            "tech_id": tech_id,
            "observed_repo_count": len(repo_ids),
            "sample_repo_count": sample_count,
            "observation_ratio": len(repo_ids) / sample_count,
            "github_repo_ids": tuple(sorted(repo_ids)),
        }
        for tech_id, repo_ids in sorted(observed.items())
    ]
    eligible_count = sum(row.eligible for row in records)
    return PublicBatchResult.model_validate(
        {
            "dataset_snapshot_id": snapshot_id,
            "pipeline_run_id": "public-run",
            "collector_version": "collector-v1",
            "collection_policy_version": "policy-v1",
            "generated_at": "2026-09-10T00:00:00Z",
            "registry_version": registry_version or registry.registry_version,
            "status": "READY",
            "include_partial": include_partial,
            "total_repo_count": len(records),
            "eligible_repo_count": eligible_count,
            "sample_repo_count": sample_count,
            "analyzed_repo_count": sample_count,
            "excluded_repo_count": len(records) - sample_count,
            "records": records,
            "technologies": technologies,
        }
    )


def _metadata(
    period: str,
    *,
    granularity: PeriodGranularity = PeriodGranularity.MONTH,
    selected_repo_count: int = 2,
    selected_event_count: int = 12,
    valid_event_count: int = 24,
    top_n_limit: int = 10_000,
) -> ArchiveActivityMetadata:
    return ArchiveActivityMetadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id=f"activity-{period}",
        source_uri=f"hdfs:///gitjob/repo_activity/period={period}/snapshot=immutable",
        source_hash=hashlib.sha256(period.encode()).hexdigest(),
        period=period,
        granularity=granularity,
        top_n_limit=top_n_limit,
        selected_repo_count=selected_repo_count,
        selected_event_count=selected_event_count,
        valid_event_count=valid_event_count,
        total_active_repo_count=max(selected_repo_count, 20),
        selection_event_coverage=(
            selected_event_count / valid_event_count if valid_event_count else 0
        ),
    )


def _input(
    registry: TechnologyRegistry,
    period: str,
    rows: list[dict[str, object]],
    records: tuple[PublicRepoResult, ...],
    *,
    include_partial: bool = False,
    metadata: ArchiveActivityMetadata | None = None,
    registry_version: str | None = None,
) -> ArchivePeriodInput:
    public = _public(
        registry,
        records,
        include_partial=include_partial,
        registry_version=registry_version,
        snapshot_id=f"public-{period}",
    )
    public_payload = public.model_dump(mode="json")
    return ArchivePeriodInput(
        metadata=metadata
        or _metadata(
            period,
            selected_repo_count=len(rows),
            selected_event_count=sum(int(row["event_count"]) for row in rows),
            valid_event_count=max(1, sum(int(row["event_count"]) for row in rows) * 2),
        ),
        activity_rows=iter(rows),
        public_analysis=public,
        public_snapshot_payload=public_payload,
        public_snapshot_uri=(
            "c-compute://snapshot/c-"
            + digest(
                {
                    "kind": "PUBLIC_GITHUB",
                    "owner": None,
                    "payload": public_payload,
                }
            )
        ),
        public_snapshot_hash=digest(public_payload),
    )


def test_month_join_sums_activity_for_current_positive_observations(registry):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            },
            {
                "period": "2026-03",
                "repo_id": 2,
                "repo_name": "owner/repo-2",
                "event_count": 7,
            },
        ],
        (_record(1, tech_ids=("react",)), _record(2)),
    )

    result = archive_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity=PeriodGranularity.MONTH,
    )

    point = result.points[0]
    assert (point.event_count, point.active_repo_count) == (5, 1)
    assert (point.sample_repo_count, point.sample_event_count) == (2, 12)
    assert point.analyzed_repo_coverage == point.analyzed_event_coverage == 1
    assert point.evidence_lookup.matching_repo_count == 1
    assert point.evidence_examples[0].path == "package.json"
    assert point.evidence_examples[0].uri == "hdfs://trusted/public/package.json"
    assert result.observation_semantics == "CURRENT_PINNED_POSITIVE_OBSERVATIONS_ONLY"


def test_current_trend_counts_matched_language_observations(registry):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 7,
            }
        ],
        (_record(1, language_tech_ids=("javascript",)),),
    )

    point = archive_trend(
        "javascript",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity=PeriodGranularity.MONTH,
    ).points[0]

    assert (point.event_count, point.active_repo_count) == (7, 1)
    assert point.evidence_lookup.matching_repo_count == 1
    assert point.evidence_examples[0].evidence_basis == "GITHUB_LANGUAGE"
    assert point.evidence_examples[0].language == "Javascript"


def test_complete_sample_actual_zero_is_not_a_nonuse_claim(registry):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1, unresolved=True),),
    )

    point = archive_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert (point.event_count, point.active_repo_count) == (0, 0)
    assert "ZERO_MEANS_NO_CURRENT_POSITIVE_OBSERVATION" in point.quality_reasons
    assert "UNRESOLVED_TECHNOLOGY_OBSERVATIONS" in point.quality_reasons
    assert point.status == TrendStatus.INSUFFICIENT_DATA


def test_failed_and_not_found_collections_never_become_zero_denominator(registry):
    failed = _record(
        1,
        collection_status=RepoCollectionStatus.FAILED,
        included=False,
        exclusion_reasons=("COLLECTION_FAILED",),
    )
    not_found = _record(
        2,
        collection_status=RepoCollectionStatus.FAILED,
        included=False,
        exclusion_reasons=("COLLECTION_NOT_FOUND",),
    )
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            },
            {
                "period": "2026-03",
                "repo_id": 2,
                "repo_name": "owner/repo-2",
                "event_count": 7,
            },
        ],
        (failed, not_found),
    )

    point = archive_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.event_count is point.active_repo_count is None
    assert point.sample_repo_count == point.sample_event_count == 0
    assert point.failed_repo_count == 2
    assert "NO_ELIGIBLE_PARSED_REPOSITORIES" in point.quality_reasons


def test_partial_requires_matching_explicit_opt_in_and_propagates_quality(registry):
    partial = _record(
        1,
        tech_ids=("react",),
        collection_status=RepoCollectionStatus.PARTIAL,
        included=True,
        partial=True,
    )
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (partial,),
        include_partial=True,
    )

    with pytest.raises(ValueError, match="include_partial"):
        archive_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )

    point = archive_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
        include_partial=True,
    ).points[0]
    assert point.event_count == 5
    assert point.partial_repo_count == 1
    assert "PARTIAL_COLLECTION_INCLUDED" in point.quality_reasons


@pytest.mark.parametrize("bad_id", [None, True, 0, "1"])
def test_null_or_non_strict_repo_id_is_rejected(registry, bad_id):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": bad_id,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1),),
    )
    with pytest.raises(ValueError, match="repo_id"):
        archive_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


def test_duplicate_repo_id_is_rejected(registry):
    rows = [
        {
            "period": "2026-03",
            "repo_id": 1,
            "repo_name": "owner/repo-1",
            "event_count": 2,
        },
        {
            "period": "2026-03",
            "repo_id": 1,
            "repo_name": "owner/renamed",
            "event_count": 3,
        },
    ]
    period_input = _input(registry, "2026-03", rows, (_record(1),))
    with pytest.raises(ValueError, match="duplicate repo_id"):
        archive_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


def test_registry_and_row_period_must_match_bound_inputs(registry):
    stale = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-04",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1),),
        registry_version="registry-20260101.1",
    )
    with pytest.raises(ValueError, match="registry_version"):
        archive_trend(
            "react", (stale,), registry, periods=("2026-03",), granularity="MONTH"
        )

    wrong_period = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-04",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1),),
    )
    with pytest.raises(ValueError, match="row period"):
        archive_trend(
            "react",
            (wrong_period,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


def test_missing_period_is_null_not_zero_and_samples_can_change(registry):
    march = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1, tech_ids=("react",)),),
    )
    may = _input(
        registry,
        "2026-05",
        [
            {
                "period": "2026-05",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 2,
            },
            {
                "period": "2026-05",
                "repo_id": 2,
                "repo_name": "owner/repo-2",
                "event_count": 8,
            },
        ],
        (_record(1, tech_ids=("react",)), _record(2, tech_ids=("react",))),
    )
    result = archive_trend(
        "react",
        (march, may),
        registry,
        periods=("2026-03", "2026-04", "2026-05"),
        granularity="MONTH",
    )

    assert result.points[0].sample_repo_count == 1
    assert result.points[1].event_count is None
    assert result.points[1].sample_repo_count is None
    assert result.points[1].quality_reasons == ("MISSING_PERIOD_INPUT",)
    assert result.points[2].sample_repo_count == 2
    assert result.points[2].event_count == 10
    assert result.status == TrendStatus.INSUFFICIENT_DATA


def test_week_requires_monday_and_period_granularity_cannot_mix(registry):
    with pytest.raises(ValueError, match="Monday"):
        archive_trend(
            "react", (), registry, periods=("2026-03-03",), granularity="WEEK"
        )
    with pytest.raises(ValueError, match="WEEK"):
        archive_trend(
            "react",
            (),
            registry,
            periods=("2026-03", "2026-03-02"),
            granularity="WEEK",
        )

    weekly_metadata = _metadata(
        "2026-03-02",
        granularity=PeriodGranularity.WEEK,
        selected_repo_count=1,
        selected_event_count=5,
        valid_event_count=10,
    )
    weekly = _input(
        registry,
        "2026-03-02",
        [
            {
                "week_start": "2026-03-02",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1, tech_ids=("react",)),),
        metadata=weekly_metadata,
    )
    point = archive_trend(
        "react",
        (weekly,),
        registry,
        periods=("2026-03-02",),
        granularity="WEEK",
    ).points[0]
    assert point.granularity == PeriodGranularity.WEEK
    assert point.event_count == 5


def test_activity_file_adapter_streams_with_a_hard_bound(tmp_path):
    path = tmp_path / "activity.ndjson"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "period": "2026-03",
                    "repo_id": index,
                    "repo_name": f"o/r-{index}",
                    "event_count": 1,
                }
            )
            for index in range(1, 4)
        ),
        encoding="utf-8",
    )
    rows = iter_bounded_activity_file(path, granularity="MONTH", max_rows=2)
    assert next(rows)["repo_id"] == 1
    assert next(rows)["repo_id"] == 2
    with pytest.raises(ValueError, match="max_rows"):
        next(rows)

    parquet = tmp_path / "activity.parquet"
    parquet.write_bytes(b"PAR1")
    with pytest.raises(ValueError, match="Spark"):
        next(iter_bounded_activity_file(parquet, granularity="MONTH", max_rows=10))


def test_verified_text_stream_can_be_parsed_without_reopening_a_path():
    stream = io.StringIO("period,repo_id,repo_name,event_count\n2026-03,1,o/one,5\n")
    rows = tuple(
        iter_bounded_activity_stream(
            stream, suffix=".csv", granularity="MONTH", max_rows=1
        )
    )
    assert rows == (
        {
            "period": "2026-03",
            "repo_id": 1,
            "repo_name": "o/one",
            "event_count": 5,
        },
    )


def test_activity_rows_cannot_smuggle_client_supplied_technology_sets(registry):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
                "tech_ids": ["react"],
            }
        ],
        (_record(1),),
    )
    with pytest.raises(ValueError, match="technology fields"):
        archive_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


@pytest.mark.parametrize("field", ["public_snapshot_uri", "public_snapshot_hash"])
def test_public_lineage_must_match_the_stored_c_artifact(registry, field):
    period_input = _input(
        registry,
        "2026-03",
        [
            {
                "period": "2026-03",
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "event_count": 5,
            }
        ],
        (_record(1),),
    )
    replacement = (
        "c-compute://snapshot/" + period_input.public_analysis.dataset_snapshot_id
        if field == "public_snapshot_uri"
        else "0" * 64
    )
    tampered = replace(period_input, **{field: replacement})
    with pytest.raises(ValueError, match=field):
        archive_trend(
            "react",
            (tampered,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )
