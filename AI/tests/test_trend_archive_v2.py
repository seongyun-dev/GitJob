import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from github.contracts import RepoCollectionStatus, RepoLanguageMetadata
from github.public_analysis import (
    ArtifactAnalysis,
    LanguageAnalysis,
    PublicBatchResult,
    PublicRepoResult,
    TechnologyObservation,
)
from registry.contracts import TechnologyRegistry
from registry.mapper import MatchStatus
from trend.archive import ArchiveActivityMetadata, PeriodGranularity
from trend.archive_v2 import (
    HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
    HISTORICAL_ARCHIVE_TREND_SCHEMA_VERSION,
    HistoricalArchivePeriodInput,
    archive_historical_trend,
)
from trend.contracts import TrendStatus
from worker.store import digest


@pytest.fixture
def registry() -> TechnologyRegistry:
    return TechnologyRegistry.model_validate_json(
        Path("registry/data/technology_registry_v1.json").read_text(encoding="utf-8")
    )


def _record(
    repo_id: int,
    *,
    tech_ids: tuple[str, ...] = (),
    language_tech_ids: tuple[str, ...] = (),
    pinned_commit_sha: str | None = None,
    collection_status: RepoCollectionStatus = RepoCollectionStatus.COMPLETE,
    included: bool = True,
    partial: bool = False,
    unresolved: bool = False,
) -> PublicRepoResult:
    commit_sha = pinned_commit_sha or f"{repo_id:x}".rjust(40, "0")
    artifact = ArtifactAnalysis(
        path="package.json",
        uri=f"hdfs://trusted/{repo_id}/{commit_sha}/package.json",
        content_hash=f"{repo_id:x}".rjust(64, "0"),
        size_bytes=20,
        status=TrendStatus.READY,
    )
    language_metadata = tuple(
        RepoLanguageMetadata(
            language=tech_id,
            file_count=1,
            representative_paths=(f"src/main.{tech_id}",),
        )
        for tech_id in language_tech_ids
    )
    return PublicRepoResult(
        repo_snapshot_id=f"repo-snapshot-{repo_id}",
        github_repo_id=repo_id,
        repo_full_name=f"owner/repo-{repo_id}",
        pinned_commit_sha=commit_sha,
        tree_sha=None,
        activity_metric="gh_archive_event_count",
        activity_period_start="2026-03-01",
        activity_period_end="2026-03-31",
        activity_rank=repo_id,
        activity_count=repo_id,
        collection_status=collection_status,
        collection_issues=("FILE_LIMIT_REACHED",) if partial else (),
        tree_truncated=False,
        observed_tree_entries=1,
        checkpoint_uri=None,
        reused_from_snapshot_id=None,
        eligible=included,
        included_in_denominator=included,
        partial_included=partial,
        exclusion_reasons=() if included else ("COLLECTION_FAILED",),
        quality_reasons=(),
        status=TrendStatus.INSUFFICIENT_DATA if unresolved else TrendStatus.READY,
        observations=tuple(
            TechnologyObservation(
                tech_id=tech_id,
                basis="PACKAGE",
                raw_value=tech_id,
                scope="dependencies",
                path=artifact.path,
                uri=artifact.uri,
                content_hash=artifact.content_hash,
            )
            for tech_id in tech_ids
        ),
        language_metadata=language_metadata,
        language_observations=tuple(
            LanguageAnalysis(
                language=row.language,
                file_count=row.file_count,
                representative_paths=row.representative_paths,
                status=MatchStatus.MATCHED,
                tech_id=row.language,
                candidates=(row.language,),
            )
            for row in language_metadata
        ),
        unresolved=(
            (
                {
                    "raw_value": "unknown-sdk",
                    "basis": "PACKAGE",
                    "status": "NOT_FOUND",
                    "candidates": (),
                    "path": artifact.path,
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
    period: str,
    records: tuple[PublicRepoResult, ...],
    *,
    include_partial: bool = False,
) -> PublicBatchResult:
    observed: dict[str, set[int]] = {}
    for record in records:
        if record.included_in_denominator:
            for observation in record.observations:
                observed.setdefault(observation.tech_id, set()).add(
                    record.github_repo_id
                )
            for observation in record.language_observations:
                if observation.status is MatchStatus.MATCHED:
                    observed.setdefault(observation.tech_id, set()).add(
                        record.github_repo_id
                    )
    sample_count = sum(record.included_in_denominator for record in records)
    return PublicBatchResult.model_validate(
        {
            "dataset_snapshot_id": f"a-snapshot-{period}",
            "pipeline_run_id": f"public-run-{period}",
            "collector_version": "gitjob-repo-fetch-orchestrator/v2",
            "collection_policy_version": "policy-v1",
            "generated_at": "2026-09-11T00:00:00Z",
            "registry_version": registry.registry_version,
            "status": "READY",
            "include_partial": include_partial,
            "total_repo_count": len(records),
            "eligible_repo_count": sample_count,
            "sample_repo_count": sample_count,
            "analyzed_repo_count": sample_count,
            "excluded_repo_count": len(records) - sample_count,
            "records": records,
            "technologies": [
                {
                    "tech_id": tech_id,
                    "observed_repo_count": len(repo_ids),
                    "sample_repo_count": sample_count,
                    "observation_ratio": len(repo_ids) / sample_count,
                    "github_repo_ids": tuple(sorted(repo_ids)),
                }
                for tech_id, repo_ids in sorted(observed.items())
            ],
        }
    )


def _lineage(
    repo_id: int,
    *,
    sha_source: str | None = "MONTH_EVENT_SHA",
    selected_commit_sha: str | None = None,
    monthly_event_sha: str | None = None,
    current_default_head: str | None = None,
    sha_fallback_reason: str | None = None,
    target_period: str | None = "2026-03-01/2026-03-31",
) -> dict[str, object]:
    commit_sha = f"{repo_id:x}".rjust(40, "0")
    if sha_source == "MONTH_EVENT_SHA":
        selected_commit_sha = selected_commit_sha or commit_sha
        monthly_event_sha = monthly_event_sha or commit_sha
    elif sha_source == "CURRENT_DEFAULT_HEAD":
        selected_commit_sha = selected_commit_sha or commit_sha
        current_default_head = current_default_head or commit_sha
        sha_fallback_reason = sha_fallback_reason or "MONTH_EVENT_SHA_NOT_AVAILABLE"
    return {
        "repo_snapshot_id": f"repo-snapshot-{repo_id}",
        "github_repo_id": repo_id,
        "pinned_commit_sha": commit_sha,
        "selected_commit_sha": selected_commit_sha,
        "sha_source": sha_source,
        "monthly_event_sha": monthly_event_sha,
        "current_default_head": current_default_head,
        "sha_fallback_reason": sha_fallback_reason,
        "target_period": target_period,
    }


def _row(repo_id: int, event_count: int, period: str = "2026-03") -> dict[str, object]:
    return {
        "period": period,
        "repo_id": repo_id,
        "repo_name": f"owner/repo-{repo_id}",
        "event_count": event_count,
    }


def _a_record(
    record: PublicRepoResult, lineage: dict[str, object]
) -> dict[str, object]:
    collection_issues = list(record.collection_issues)
    if (
        record.collection_status is RepoCollectionStatus.FAILED
        and not collection_issues
    ):
        collection_issues = ["REPOSITORY_UNAVAILABLE"]
    return {
        "repo_snapshot_id": record.repo_snapshot_id,
        "github_repo_id": record.github_repo_id,
        "repo_full_name": record.repo_full_name,
        "activity_metric": record.activity_metric,
        "activity_period_start": record.activity_period_start,
        "activity_period_end": record.activity_period_end,
        "activity_count": record.activity_count,
        "activity_rank": record.activity_rank,
        "pinned_commit_sha": record.pinned_commit_sha,
        "tree_sha": record.tree_sha,
        "collection_status": record.collection_status,
        "collection_issues": collection_issues,
        "checkpoint_uri": record.checkpoint_uri,
        "reused_from_snapshot_id": record.reused_from_snapshot_id,
        "tree_truncated": record.tree_truncated,
        "observed_tree_entries": record.observed_tree_entries,
        "artifacts": [],
        **lineage,
    }


def _input(
    registry: TechnologyRegistry,
    period: str,
    rows: list[dict[str, object]],
    records: tuple[PublicRepoResult, ...],
    lineages: list[dict[str, object]],
    *,
    corrupt_hash: str | None = None,
    include_partial: bool = False,
) -> HistoricalArchivePeriodInput:
    activity_bytes = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )
    public_by_id = {record.github_repo_id: record for record in records}
    a_snapshot = {
        "schema_version": "github-repo-snapshot/v1",
        "dataset_snapshot_id": f"a-snapshot-{period}",
        "pipeline_run_id": f"public-run-{period}",
        "collector_version": "gitjob-repo-fetch-orchestrator/v2",
        "generated_at": "2026-09-11T00:00:00Z",
        "collection_policy": {
            "policy_version": "policy-v1",
            "top_n_limit": 10_000,
            "max_api_calls": 30_000,
            "max_runtime_seconds": 3_600,
            "max_tree_entries": 100_000,
            "max_artifact_files": 100,
            "max_artifact_bytes": 10_485_760,
        },
        "records": [
            _a_record(public_by_id[int(lineage["github_repo_id"])], lineage)
            for lineage in lineages
        ],
    }
    a_snapshot_bytes = json.dumps(
        a_snapshot, sort_keys=True, separators=(",", ":")
    ).encode()
    public = _public(registry, period, records, include_partial=include_partial)
    public_payload = public.model_dump(mode="json")
    selected_events = sum(int(row["event_count"]) for row in rows)
    return HistoricalArchivePeriodInput(
        metadata=ArchiveActivityMetadata(
            source_schema_version="c-archive-activity-export/v1",
            source_version="spark-repo-activity/v2",
            dataset_snapshot_id=f"activity-{period}",
            source_uri=f"c-archive-activity://export/activity-{period}/activity.ndjson",
            source_hash=(
                "0" * 64
                if corrupt_hash == "activity"
                else hashlib.sha256(activity_bytes).hexdigest()
            ),
            upstream_source_uri=f"hdfs:///gitjob/repo_activity/period={period}/snapshot=immutable",
            upstream_source_hash="b" * 64,
            period=period,
            granularity=PeriodGranularity.MONTH,
            top_n_limit=10_000,
            selected_repo_count=len(rows),
            selected_event_count=selected_events,
            valid_event_count=max(1, selected_events * 2),
            total_active_repo_count=max(20, len(rows)),
            selection_event_coverage=(0.5 if selected_events else 0.0),
        ),
        activity_bytes=activity_bytes,
        activity_suffix=".ndjson",
        a_snapshot_bytes=a_snapshot_bytes,
        a_snapshot_uri=f"hdfs:///gitjob/repo_snapshot/{period}/snapshot.json",
        a_snapshot_hash=(
            "0" * 64
            if corrupt_hash == "a_snapshot"
            else hashlib.sha256(a_snapshot_bytes).hexdigest()
        ),
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
        public_snapshot_hash=(
            "0" * 64 if corrupt_hash == "public" else digest(public_payload)
        ),
    )


def test_v2_only_counts_observations_from_matching_monthly_push_heads(registry):
    rows = [_row(1, 5), _row(2, 7), _row(3, 11), _row(4, 13), _row(5, 17)]
    records = tuple(
        _record(
            repo_id,
            tech_ids=(("react",) if repo_id < 5 else ()),
            # Keep A's MONTH_EVENT_SHA state internally valid while exercising
            # the intended A/public pinned-head mismatch for repository 4.
            pinned_commit_sha=("f" * 40 if repo_id == 4 else None),
        )
        for repo_id in range(1, 6)
    )
    period_input = _input(
        registry,
        "2026-03",
        rows,
        records,
        [
            _lineage(1),
            _lineage(2, sha_source="CURRENT_DEFAULT_HEAD"),
            _lineage(3, sha_source=None, target_period=None),
            _lineage(4),
            _lineage(5),
        ],
    )

    result = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    )

    point = result.points[0]
    assert result.schema_version == HISTORICAL_ARCHIVE_TREND_SCHEMA_VERSION
    assert result.algorithm_version == HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION
    assert result.observation_semantics == (
        "HISTORICAL_MONTHLY_PUSH_HEAD_POSITIVE_OBSERVATIONS_ONLY"
    )
    assert (point.event_count, point.active_repo_count) == (5, 1)
    assert (point.sample_repo_count, point.sample_event_count) == (2, 22)
    assert point.historical_head_unavailable_repo_count == 2
    assert point.historical_head_mismatch_repo_count == 1
    assert point.analyzed_repo_coverage == pytest.approx(2 / 5)
    assert point.analyzed_event_coverage == pytest.approx(22 / 53)
    assert "HISTORICAL_HEAD_UNAVAILABLE" in point.quality_reasons
    assert "HISTORICAL_HEAD_MISMATCH" in point.quality_reasons


def test_current_default_head_is_excluded_even_when_it_matches_pinned_commit(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1, tech_ids=("react",)),),
        [_lineage(1, sha_source="CURRENT_DEFAULT_HEAD")],
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.event_count is point.active_repo_count is None
    assert point.sample_repo_count == point.sample_event_count == 0
    assert point.historical_head_unavailable_repo_count == 1
    assert point.historical_head_mismatch_repo_count == 0


def test_language_only_observation_contributes_without_fake_artifact_evidence(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1, language_tech_ids=("python",)),),
        [_lineage(1)],
    )

    point = archive_historical_trend(
        "python",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert (point.event_count, point.active_repo_count) == (5, 1)
    assert point.evidence_lookup is not None
    assert point.evidence_lookup.matching_repo_count == 1
    assert len(point.evidence_examples) == 1
    example = point.evidence_examples[0]
    assert example.evidence_basis == "GITHUB_LANGUAGE"
    assert example.language == "python"
    assert example.representative_paths == ("src/main.python",)
    assert "path" not in example.model_dump(mode="json")


@pytest.mark.parametrize("corrupt_hash", ["activity", "a_snapshot", "public"])
def test_v2_rejects_checksum_mismatch(registry, corrupt_hash):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1)],
        corrupt_hash=corrupt_hash,
    )

    with pytest.raises(ValueError, match="hash|checksum"):
        archive_historical_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dataset_snapshot_id", "other", "dataset_snapshot_id"),
        ("pipeline_run_id", "other", "pipeline_run_id"),
        ("collector_version", "other", "collector_version"),
        ("collection_policy", {"policy_version": "other"}, "policy versions"),
    ],
)
def test_v2_rejects_a_and_public_version_lineage_mismatch(
    registry, field, value, message
):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1)],
    )
    a_snapshot = json.loads(period_input.a_snapshot_bytes)
    a_snapshot[field] = value
    changed = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    period_input = replace(
        period_input,
        a_snapshot_bytes=changed,
        a_snapshot_hash=hashlib.sha256(changed).hexdigest(),
    )

    with pytest.raises(ValueError, match=message):
        archive_historical_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


def test_v2_rejects_abbreviated_a_snapshot_without_base_v1_fields(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1)],
    )
    a_snapshot = json.loads(period_input.a_snapshot_bytes)
    del a_snapshot["records"][0]["repo_full_name"]
    changed = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    period_input = replace(
        period_input,
        a_snapshot_bytes=changed,
        a_snapshot_hash=hashlib.sha256(changed).hexdigest(),
    )

    with pytest.raises(ValueError, match="repo_full_name"):
        archive_historical_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"sha_fallback_reason": "unexpected fallback"},
            "MONTH_EVENT_SHA must not have a fallback reason",
        ),
        (
            {
                "sha_source": None,
                "selected_commit_sha": "1".rjust(40, "0"),
                "monthly_event_sha": "1".rjust(40, "0"),
            },
            "commit lineage fields require sha_source",
        ),
    ],
)
def test_v2_rejects_invalid_additive_a_lineage_contract(registry, updates, message):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1)],
    )
    a_snapshot = json.loads(period_input.a_snapshot_bytes)
    a_snapshot["records"][0].update(updates)
    changed = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    period_input = replace(
        period_input,
        a_snapshot_bytes=changed,
        a_snapshot_hash=hashlib.sha256(changed).hexdigest(),
    )

    with pytest.raises(ValueError, match=message):
        archive_historical_trend(
            "react",
            (period_input,),
            registry,
            periods=("2026-03",),
            granularity="MONTH",
        )


def test_v2_marks_base_snapshot_activity_period_mismatch(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1)],
    )
    a_snapshot = json.loads(period_input.a_snapshot_bytes)
    a_snapshot["records"][0]["activity_period_start"] = "2026-02-01"
    changed = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    period_input = replace(
        period_input,
        a_snapshot_bytes=changed,
        a_snapshot_hash=hashlib.sha256(changed).hexdigest(),
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.sample_repo_count == 0
    assert point.historical_head_mismatch_repo_count == 1


def test_v2_preserves_a_commit_and_snapshot_lineage(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1, tech_ids=("react",)),),
        [_lineage(1)],
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.activity_source_hash == period_input.metadata.source_hash
    assert point.activity_upstream_source_hash == "b" * 64
    assert point.a_snapshot_hash == period_input.a_snapshot_hash
    assert point.public_snapshot_hash == period_input.public_snapshot_hash
    assert point.historical_head_repo_coverage == 1
    assert point.historical_head_event_coverage == 1
    example = point.evidence_examples[0]
    assert example.monthly_event_sha == example.selected_commit_sha
    assert example.selected_commit_sha == example.pinned_commit_sha
    assert example.sha_source == "MONTH_EVENT_SHA"
    assert example.target_period == "2026-03-01/2026-03-31"


def test_legacy_optional_v1_snapshot_is_current_observation_only(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1, tech_ids=("react",)),),
        [_lineage(1, sha_source=None, target_period=None)],
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.sample_repo_count == 0
    assert point.historical_head_unavailable_repo_count == 1
    assert "HISTORICAL_HEAD_UNAVAILABLE" in point.quality_reasons


def test_month_event_sha_with_wrong_target_period_is_a_mismatch(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5)],
        (_record(1),),
        [_lineage(1, target_period="2026-04-01/2026-04-30")],
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
    ).points[0]

    assert point.sample_repo_count == 0
    assert point.historical_head_mismatch_repo_count == 1
    assert "HISTORICAL_HEAD_MISMATCH" in point.quality_reasons


def test_v2_preserves_failed_partial_and_unresolved_quality_counts(registry):
    period_input = _input(
        registry,
        "2026-03",
        [_row(1, 5), _row(2, 7), _row(3, 11)],
        (
            _record(
                1,
                tech_ids=("react",),
                collection_status=RepoCollectionStatus.PARTIAL,
                partial=True,
            ),
            _record(
                2,
                collection_status=RepoCollectionStatus.FAILED,
                included=False,
            ),
            _record(3, unresolved=True),
        ),
        [_lineage(1), _lineage(2), _lineage(3)],
        include_partial=True,
    )

    point = archive_historical_trend(
        "react",
        (period_input,),
        registry,
        periods=("2026-03",),
        granularity="MONTH",
        include_partial=True,
    ).points[0]

    assert point.failed_repo_count == 1
    assert point.partial_repo_count == 1
    assert point.unresolved_repo_count == 1
    assert "PARTIAL_COLLECTION_INCLUDED" in point.quality_reasons
    assert "UNRESOLVED_TECHNOLOGY_OBSERVATIONS" in point.quality_reasons
