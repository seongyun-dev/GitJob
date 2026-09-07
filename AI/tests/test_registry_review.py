import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from job.classifier import classify_job_batch
from job.contracts import JobAnalysisInputBatch
from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import MapperSource, MatchStatus, RegistryMapper
from registry.review import (
    DecisionKind,
    ReviewQueueSnapshot,
    ReviewStatus,
    ReviewStore,
)

AI_ROOT = Path(__file__).resolve().parents[1]
JOB_FIXTURE = AI_ROOT / "job" / "fixtures" / "job_analysis_input_v1.json"
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"
FIXED_NOW = datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC)


def load_base_registry() -> TechnologyRegistry:
    return load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)


def classify_fixture(registry: TechnologyRegistry | None = None):
    batch = JobAnalysisInputBatch.model_validate_json(
        JOB_FIXTURE.read_text(encoding="utf-8")
    )
    return classify_job_batch(batch, RegistryMapper(registry or load_base_registry()))


def add_quantumdb_registry_mapping() -> TechnologyRegistry:
    payload = load_base_registry().model_dump(mode="json")
    payload["registry_version"] = "registry-20260907.1"
    payload["technologies"].append(
        {
            "tech_id": "quantumdb",
            "display_name": "QuantumDB",
            "categories": ["AI_DATA"],
            "status": "ACTIVE",
            "provenance_refs": ["https://example.com/quantumdb"],
        }
    )
    payload["mappings"].append(
        {
            "tech_id": "quantumdb",
            "mapping_type": "ALIAS",
            "ecosystem": None,
            "value": "QuantumDB",
            "match_mode": "EXACT",
            "status": "ACTIVE",
            "provenance_refs": ["https://example.com/quantumdb"],
        }
    )
    return TechnologyRegistry.model_validate_json(json.dumps(payload))


def test_unknown_and_ambiguous_results_are_saved_without_loss(tmp_path: Path) -> None:
    path = tmp_path / "review-queue.json"
    store = ReviewStore(path, now=lambda: FIXED_NOW)

    ingested = store.ingest(classify_fixture())

    assert len(ingested) == 4
    assert {record.raw_technology for record in ingested} == {
        "C",
        "R",
        "Go",
        "QuantumDB",
    }
    assert {record.original_match_status for record in ingested} == {
        MatchStatus.UNKNOWN,
        MatchStatus.AMBIGUOUS,
    }
    assert all(record.status is ReviewStatus.PENDING for record in ingested)
    assert all(record.source_record_id and record.source_site for record in ingested)
    assert all(record.context and record.mapping_evidence.reason for record in ingested)
    assert all(
        record.attempts[0].decision_kind is DecisionKind.AUTOMATIC
        for record in ingested
    )
    short_c = next(record for record in ingested if record.raw_technology == "C")
    assert short_c.mapping_strategy == (
        MapperSource.ALIAS,
        MapperSource.DISPLAY_NAME,
    )
    assert (
        tuple(mapping.source for mapping in short_c.attempts[0].mapping_attempts)
        == short_c.mapping_strategy
    )
    assert short_c.attempts[0].mapping_attempts[-1].evidence == (
        short_c.mapping_evidence
    )
    quantumdb = next(
        record for record in ingested if record.raw_technology == "QuantumDB"
    )
    assert str(quantumdb.source_url) == "https://example.invalid/jobs/fixture-1004"
    assert "데이터 엔지니어" in quantumdb.context
    assert "QuantumDB 경험이 있으면 좋습니다." in quantumdb.context
    assert path.is_file()

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0]["source_url"] = "not-a-url"
    with pytest.raises(ValidationError):
        ReviewQueueSnapshot.model_validate(payload)


def test_review_queue_reloads_and_ingestion_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "review-queue.json"
    first_store = ReviewStore(path, now=lambda: FIXED_NOW)
    first_store.ingest(classify_fixture())

    second_store = ReviewStore(path, now=lambda: FIXED_NOW)
    second_store.ingest(classify_fixture())

    assert len(second_store.query()) == 4
    assert second_store.query() == first_store.query()


def test_same_evidence_at_same_offset_on_different_surfaces_is_not_collapsed(
    tmp_path: Path,
) -> None:
    payload = json.loads(JOB_FIXTURE.read_text(encoding="utf-8"))
    record = payload["records"][3]
    base_mention = dict(record["technology_mentions"][0])
    record["title"] = "QuantumDB"
    record["description_text"] = "QuantumDB"
    title_mention = dict(base_mention)
    title_mention.update(
        {
            "source_surface": "TITLE",
            "evidence_section": "공고 제목",
            "evidence_text": "QuantumDB",
        }
    )
    body_mention = dict(title_mention)
    body_mention.update({"source_surface": "BODY", "evidence_section": "기술스택"})
    record["technology_mentions"] = [title_mention, body_mention]
    batch = JobAnalysisInputBatch.model_validate_json(json.dumps(payload))
    classifications = classify_job_batch(batch, RegistryMapper(load_base_registry()))
    store = ReviewStore(tmp_path / "review-queue.json", now=lambda: FIXED_NOW)

    store.ingest(classifications)
    quantumdb_records = [
        item for item in store.query() if item.raw_technology == "QuantumDB"
    ]

    assert len(store.query()) == 5
    assert len(quantumdb_records) == 2
    assert len({item.review_id for item in quantumdb_records}) == 2
    assert {item.source_surface.value for item in quantumdb_records} == {
        "TITLE",
        "BODY",
    }


def test_manual_resolution_records_actor_note_and_registry_version(
    tmp_path: Path,
) -> None:
    store = ReviewStore(tmp_path / "review-queue.json", now=lambda: FIXED_NOW)
    unknown = next(
        record
        for record in store.ingest(classify_fixture())
        if record.raw_technology == "QuantumDB"
    )

    resolved = store.resolve_manual(
        unknown.review_id,
        tech_id="postgresql",
        reviewer="reviewer-123",
        note="Explicit reviewer decision for fixture verification",
        mapper=RegistryMapper(load_base_registry()),
    )

    assert resolved.status is ReviewStatus.RESOLVED
    assert resolved.resolved_tech_id == "postgresql"
    assert resolved.attempts[-1].decision_kind is DecisionKind.MANUAL
    assert resolved.attempts[-1].reviewer == "reviewer-123"
    assert resolved.attempts[-1].note == (
        "Explicit reviewer decision for fixture verification"
    )
    assert resolved.attempts[-1].registry_version == "registry-20260901.1"


def test_manual_resolution_rejects_unknown_or_inactive_registry_technology(
    tmp_path: Path,
) -> None:
    store = ReviewStore(tmp_path / "review-queue.json", now=lambda: FIXED_NOW)
    unknown = next(
        record
        for record in store.ingest(classify_fixture())
        if record.raw_technology == "QuantumDB"
    )

    with pytest.raises(ValueError, match="active Registry tech_id"):
        store.resolve_manual(
            unknown.review_id,
            tech_id="quantumdb",
            reviewer="reviewer-123",
            note="Invalid until the Registry contains this technology",
            mapper=RegistryMapper(load_base_registry()),
        )

    assert store.query(ReviewStatus.RESOLVED) == ()


def test_new_registry_reprocesses_pending_records_and_keeps_unresolved_ones(
    tmp_path: Path,
) -> None:
    store = ReviewStore(tmp_path / "review-queue.json", now=lambda: FIXED_NOW)
    store.ingest(classify_fixture())

    reprocessed = store.reprocess_pending(
        RegistryMapper(add_quantumdb_registry_mapping())
    )
    by_raw_value = {record.raw_technology: record for record in reprocessed}

    assert by_raw_value["QuantumDB"].status is ReviewStatus.RESOLVED
    assert by_raw_value["QuantumDB"].resolved_tech_id == "quantumdb"
    assert by_raw_value["QuantumDB"].attempts[-1].registry_version == (
        "registry-20260907.1"
    )
    assert by_raw_value["QuantumDB"].attempts[-1].decision_kind is (
        DecisionKind.AUTOMATIC
    )
    assert tuple(
        attempt.source
        for attempt in by_raw_value["QuantumDB"].attempts[-1].mapping_attempts
    ) == (MapperSource.ALIAS,)
    assert by_raw_value["C"].status is ReviewStatus.PENDING
    assert by_raw_value["R"].status is ReviewStatus.PENDING
    assert by_raw_value["Go"].status is ReviewStatus.PENDING
    assert all(len(record.attempts) == 2 for record in reprocessed)
