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
    ReviewRecord,
    ReviewStatus,
    ReviewStore,
    build_records,
)

AI_ROOT = Path(__file__).resolve().parents[1]
JOB_FIXTURE = AI_ROOT / "job" / "fixtures" / "job_analysis_input_v1.json"
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"
FIXED_NOW = datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC)
LEGACY_FIXTURE_IDS = {
    "C": (
        "review-38e7a97dcd6f08de13560d03",
        "review-1149feb5aa22f0e92041dc17",
    ),
    "R": (
        "review-c577e61155faf9f9b7370f6b",
        "review-7ef7d4fd1d530b07091bca50",
    ),
    "Go": (
        "review-078767c644a0914d0810c35f",
        "review-43863bf3e8c86f8423c23cc2",
    ),
    "QuantumDB": (
        "review-2e4d9b55575a86b8c609fe2b",
        "review-020443146b8e4d901a32df13",
    ),
}


def load_base_registry() -> TechnologyRegistry:
    return load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)


def classify_fixture(registry: TechnologyRegistry | None = None):
    batch = JobAnalysisInputBatch.model_validate_json(
        JOB_FIXTURE.read_text(encoding="utf-8")
    )
    return classify_job_batch(batch, RegistryMapper(registry or load_base_registry()))


def write_legacy_snapshot(
    path: Path,
    *,
    schema_version: str,
    resolve_quantumdb: bool = False,
) -> None:
    store = ReviewStore(path, now=lambda: FIXED_NOW)
    records = store.ingest(classify_fixture())
    if resolve_quantumdb:
        quantumdb = next(
            record for record in records if record.raw_technology == "QuantumDB"
        )
        store.resolve_manual(
            quantumdb.review_id,
            tech_id="postgresql",
            reviewer="legacy-admin",
            note="기존 수동 결정",
            mapper=RegistryMapper(load_base_registry()),
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = schema_version
    legacy_index = 0 if schema_version == "registry-review-queue/v2" else 1
    for value in payload["records"]:
        record = ReviewRecord.model_validate(value)
        value["review_id"] = LEGACY_FIXTURE_IDS[record.raw_technology][legacy_index]
        value.pop("review_id_version")
        value.pop("char_start")
        value.pop("char_end")
        if schema_version == "registry-review-queue/v1":
            value.pop("source_dataset_snapshot_id")
    path.write_text(json.dumps(payload), encoding="utf-8")


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

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == (
        "registry-review-queue/v3"
    )
    assert len(second_store.query()) == 4
    assert second_store.query() == first_store.query()


def test_v1_snapshot_reloads_without_rewriting_stored_review_id(tmp_path: Path) -> None:
    path = tmp_path / "review-queue.json"
    store = ReviewStore(path, now=lambda: FIXED_NOW)
    store.ingest(classify_fixture())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "registry-review-queue/v1"
    payload["records"][0]["review_id"] = "review-" + "0" * 24
    for record in payload["records"]:
        record.pop("review_id_version")
        record.pop("char_start")
        record.pop("char_end")
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = ReviewStore(path, now=lambda: FIXED_NOW)

    assert loaded.query()[0].review_id == "review-" + "0" * 24


@pytest.mark.parametrize(
    "schema_version",
    ("registry-review-queue/v1", "registry-review-queue/v2"),
)
def test_legacy_snapshot_reingest_preserves_existing_resolution(
    tmp_path: Path,
    schema_version: str,
) -> None:
    path = tmp_path / "review-queue.json"
    write_legacy_snapshot(
        path,
        schema_version=schema_version,
        resolve_quantumdb=True,
    )
    before = ReviewStore(path, now=lambda: FIXED_NOW)
    legacy_resolution = next(
        record for record in before.query() if record.raw_technology == "QuantumDB"
    )

    affected = ReviewStore(path, now=lambda: FIXED_NOW).ingest(classify_fixture())
    after = ReviewStore(path, now=lambda: FIXED_NOW)
    preserved = next(
        record for record in after.query() if record.raw_technology == "QuantumDB"
    )

    assert len(after.query()) == 4
    assert preserved == legacy_resolution
    assert preserved.status is ReviewStatus.RESOLVED
    assert preserved.resolved_tech_id == "postgresql"
    assert len(preserved.attempts) == 2
    assert preserved in affected


def test_v1_reingest_does_not_merge_same_legacy_id_from_a_different_site(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review-queue.json"
    write_legacy_snapshot(path, schema_version="registry-review-queue/v1")
    payload = json.loads(JOB_FIXTURE.read_text(encoding="utf-8"))
    quantumdb_source = payload["records"][3]
    quantumdb_source["source_site"] = "WANTED"
    quantumdb_source["source_url"] = "https://example.invalid/jobs/wanted-1004"
    changed_batch = JobAnalysisInputBatch.model_validate(payload)

    ReviewStore(path, now=lambda: FIXED_NOW).ingest(
        classify_job_batch(changed_batch, RegistryMapper(load_base_registry()))
    )
    stored = ReviewStore(path, now=lambda: FIXED_NOW).query()
    quantumdb_records = [
        record for record in stored if record.raw_technology == "QuantumDB"
    ]

    assert len(stored) == 5
    assert len(quantumdb_records) == 2
    assert {record.source_site for record in quantumdb_records} == {
        "JOBKOREA",
        "WANTED",
    }


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


def test_changed_source_variant_has_its_own_id_and_reconstructable_location() -> None:
    payload = json.loads(JOB_FIXTURE.read_text(encoding="utf-8"))
    original = payload["records"][3]
    changed = json.loads(json.dumps(original))
    changed["source_url"] = "https://example.invalid/jobs/fixture-1004-revised"
    changed["title"] = "수정된 데이터 엔지니어"
    payload["records"].append(changed)
    classified = classify_job_batch(
        JobAnalysisInputBatch.model_validate_json(json.dumps(payload)),
        RegistryMapper(load_base_registry()),
    )

    records = [
        record
        for record in build_records(classified)
        if record.raw_technology == "QuantumDB"
    ]

    assert len(records) == 2
    assert len({record.review_id for record in records}) == 2
    assert {record.review_id_version for record in records} == {"registry-review-id/v3"}
    assert all(record.char_start is not None for record in records)
    assert all(record.char_end is not None for record in records)


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


def test_manual_resolution_can_correct_a_prior_decision_without_losing_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review-queue.json"
    store = ReviewStore(path, now=lambda: FIXED_NOW)
    unknown = next(
        record
        for record in store.ingest(classify_fixture())
        if record.raw_technology == "QuantumDB"
    )
    first = store.resolve_manual(
        unknown.review_id,
        tech_id="postgresql",
        reviewer="reviewer-123",
        note="원문 확인 후 최초 결정",
        mapper=RegistryMapper(load_base_registry()),
    )

    corrected = store.resolve_manual(
        unknown.review_id,
        tech_id="python",
        reviewer="reviewer-456",
        note="교차 검토 후 결정 교정",
        mapper=RegistryMapper(load_base_registry()),
    )

    assert corrected.status is ReviewStatus.RESOLVED
    assert corrected.resolved_tech_id == "python"
    assert corrected.attempts[:-1] == first.attempts
    assert corrected.attempts[-2].tech_id == "postgresql"
    assert corrected.attempts[-1].tech_id == "python"
    assert corrected.attempts[-1].reviewer == "reviewer-456"
    assert ReviewStore(path, now=lambda: FIXED_NOW).query(ReviewStatus.RESOLVED) == (
        corrected,
    )


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
