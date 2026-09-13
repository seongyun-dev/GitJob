"""Failure/offset rules for S15P21E102-238's weekly completion consumer."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from common.events import EventEnvelope
from common.kafka import ConsumedMessage
from registry.contracts import TechnologyRegistry
from trend.archive import ArchiveActivityMetadata, PeriodGranularity
from trend.contracts import TrendStatus
from worker.store import (
    Artifact,
    ComputeStore,
    _public_payload_covers_week,
    apply_migration,
    digest,
)
from worker.weekly_activity_intake import (
    WEEKLY_COMPLETED_TOPIC,
    InputAdapterUnavailable,
    MountedWeeklyExportReader,
    Outcome,
    StorePublicSnapshotSelector,
    VerifiedWeeklyRows,
    WeeklyActivityConsumer,
    WeeklyManifest,
    _event,
    _merge_weekly_payloads,
)


class Transport:
    def __init__(self, messages):
        self.messages, self.commits = messages, 0

    def poll(self, timeout_ms):
        return self.messages

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class Never:
    def read(self, uri, *, max_bytes):
        raise AssertionError("invalid event must not read")

    def rows(self, manifest, *, public_snapshot_id, public_result):
        raise AssertionError("invalid event must not read")


def consumer(transport):
    return WeeklyActivityConsumer(transport, object(), Never(), object(), object())


def test_malformed_event_is_rejected_and_its_offset_can_advance():
    transport = Transport(
        [ConsumedMessage(WEEKLY_COMPLETED_TOPIC, 0, 0, b"bad", b"{}")]
    )
    assert consumer(transport).run_once() == (Outcome.REJECTED,)
    assert transport.commits == 1


def test_wrong_topic_is_rejected_without_reading_manifest():
    transport = Transport([ConsumedMessage("other", 0, 0, None, b"{}")])
    assert consumer(transport).run_once() == (Outcome.REJECTED,)
    assert transport.commits == 1


def test_a_publisher_event_and_manifest_are_accepted_without_contract_extension():
    from github.weekly_activity_publish import (
        WeeklySnapshotWeek,
        build_manifest,
        completion_envelope,
        manifest_uri_for,
    )

    week = WeeklySnapshotWeek("2026-09-07", "hdfs:///weekly", 1, "a" * 64)
    uri = manifest_uri_for(week.data_uri)
    envelope = completion_envelope(
        "snapshot", week, uri, ingested_at=datetime(2026, 9, 8, tzinfo=UTC)
    )
    message = ConsumedMessage(
        WEEKLY_COMPLETED_TOPIC,
        0,
        0,
        envelope.source_id.encode(),
        envelope.to_bytes(),
    )
    parsed_envelope, payload = _event(message)
    manifest = WeeklyManifest.parse(
        json.dumps(build_manifest("snapshot", week)).encode()
    )
    assert parsed_envelope.source_id == "snapshot/2026-09-07"
    assert payload["manifest_uri"] == uri
    assert manifest.row_digest == "a" * 64


def test_unavailable_c_read_adapter_retries_without_committing_offset():
    event = EventEnvelope(
        source="gharchive",
        source_id="snapshot/2026-09-07",
        event_type="RepoActivityWeeklySnapshotCompleted",
        occurred_at=datetime(2026, 9, 7, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 8, tzinfo=UTC),
        payload={
            "dataset_snapshot_id": "snapshot",
            "week_start": "2026-09-07",
            "manifest_uri": "hdfs:///weekly/_SUCCESS.json",
        },
    )

    class Reader:
        def read(self, uri, *, max_bytes):
            raise InputAdapterUnavailable("INPUT_ADAPTER_UNAVAILABLE")

        def rows(self, manifest, *, public_snapshot_id, public_result):
            raise AssertionError

    transport = Transport(
        [
            ConsumedMessage(
                WEEKLY_COMPLETED_TOPIC, 0, 0, event.source_id.encode(), event.to_bytes()
            )
        ]
    )
    result = WeeklyActivityConsumer(
        transport, object(), Reader(), object(), object()
    ).run_once()
    assert result == (Outcome.RETRY,)
    assert transport.commits == 0


def _valid_event():
    event = EventEnvelope(
        source="gharchive",
        source_id="snapshot/2026-09-07",
        event_type="RepoActivityWeeklySnapshotCompleted",
        occurred_at=datetime(2026, 9, 7, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 8, tzinfo=UTC),
        payload={
            "dataset_snapshot_id": "snapshot",
            "week_start": "2026-09-07",
            "manifest_uri": "hdfs:///weekly/_SUCCESS.json",
        },
    )
    return ConsumedMessage(
        WEEKLY_COMPLETED_TOPIC, 0, 0, event.source_id.encode(), event.to_bytes()
    )


def _manifest(**updates):
    value = {
        "schema_version": "repo-activity-weekly-publish-manifest/v1",
        "dataset_snapshot_id": "snapshot",
        "week_start": "2026-09-07",
        "data_uri": "hdfs:///weekly",
        "row_count": 1,
        "row_digest": {"format": "typed-json-v2", "value": "a" * 64},
    }
    value.update(updates)
    return __import__("json").dumps(value).encode()


def _working(monkeypatch, status="RUNNING", complete_error=None):
    class Reader:
        def read(self, uri, *, max_bytes):
            return _manifest()

        def rows(self, manifest, *, public_snapshot_id, public_result):
            return VerifiedWeeklyRows(
                ArchiveActivityMetadata(
                    source_schema_version="repo-activity-weekly/v1",
                    source_version="spark-repo-activity-weekly/v1",
                    dataset_snapshot_id="snapshot",
                    source_uri="c-export://export/selected",
                    source_hash="b" * 64,
                    upstream_source_uri="hdfs:///weekly",
                    upstream_source_hash="a" * 64,
                    period="2026-09-07",
                    granularity=PeriodGranularity.WEEK,
                    top_n_limit=1,
                    selected_repo_count=1,
                    selected_event_count=2,
                    valid_event_count=2,
                    total_active_repo_count=1,
                    selection_event_coverage=1.0,
                ),
                public_snapshot_id,
                (
                    {
                        "repo_id": 1,
                        "repo_name": "o/r",
                        "week_start": "2026-09-07",
                        "event_count": 2,
                    },
                ),
            )

    class Public:
        def select(self, **kwargs):
            return ("c-public", {"result": {}})

    class Store:
        lease_seconds = 60

        def __init__(self):
            self.failed = []

        def claim(self, **kwargs):
            self.request = kwargs["request"]
            return SimpleNamespace(
                status=status,
                token=None if status != "RUNNING" else "t",
                event_id="id",
                kind="TREND",
                owner=None,
            )

        def complete(self, ticket, artifacts, *, head_merger=None):
            if complete_error:
                raise complete_error
            self.artifacts = artifacts
            self.head_merger = head_merger

        def fail(self, ticket, code):
            self.failed.append(code)

        def renew(self, ticket):
            return True

        def get_head_payloads(self, **kwargs):
            return {}

    store = Store()
    monkeypatch.setattr(
        "worker.weekly_activity_intake.PublicBatchResult.model_validate",
        lambda value: SimpleNamespace(
            registry_version="registry", include_partial=False
        ),
    )
    monkeypatch.setattr(
        "worker.weekly_activity_intake.archive_trend",
        lambda *args, **kwargs: SimpleNamespace(model_dump=lambda mode: {"ok": True}),
    )
    registry = SimpleNamespace(
        registry_version="registry",
        technologies=(
            SimpleNamespace(tech_id="python", status=SimpleNamespace(value="ACTIVE")),
        ),
    )
    return WeeklyActivityConsumer(
        Transport([_valid_event()]), store, Reader(), Public(), registry
    ), store


def test_normal_completion_stores_one_trend_per_active_technology(monkeypatch):
    value, store = _working(monkeypatch)
    assert value.run_once() == (Outcome.COMPLETED,)
    assert len(store.artifacts) == 1
    assert "public_snapshot_id" not in store.request
    assert store.request["registry_version"] == "registry"
    assert value.transport.commits == 1


def test_completed_duplicate_commits_without_second_result(monkeypatch):
    value, store = _working(monkeypatch, status="COMPLETED")
    assert value.run_once() == (Outcome.DUPLICATE,)
    assert not hasattr(store, "artifacts")
    assert value.transport.commits == 1


def test_busy_claim_and_compute_failure_retry_without_commit(monkeypatch):
    busy, _ = _working(monkeypatch, status="RUNNING")
    busy.store.claim = lambda **kwargs: SimpleNamespace(status="RUNNING", token=None)
    assert busy.run_once() == (Outcome.RETRY,)
    assert busy.transport.commits == 0
    failed, store = _working(monkeypatch, complete_error=RuntimeError("db"))
    assert failed.run_once() == (Outcome.RETRY,)
    assert store.failed == ["WEEKLY_ACTIVITY_RETRY"]
    assert failed.transport.commits == 0


def test_missing_public_snapshot_retries_without_claim_or_commit(monkeypatch):
    value, store = _working(monkeypatch)
    value.public.select = lambda **kwargs: None
    assert value.run_once() == (Outcome.RETRY,)
    assert not hasattr(store, "artifacts")
    assert value.transport.commits == 0


def test_manifest_identity_and_week_errors_are_rejected(monkeypatch):
    value, _ = _working(monkeypatch)
    value.reader.read = lambda uri, *, max_bytes: _manifest(week_start="2026-09-08")
    assert value.run_once() == (Outcome.REJECTED,)
    assert value.transport.commits == 1


def test_original_v1_manifest_rejects_unexpected_export_reference(monkeypatch):
    value, _ = _working(monkeypatch)
    value.reader.read = lambda uri, *, max_bytes: _manifest(
        c_export={"manifest_uri": "hdfs:///export/manifest.json"}
    )
    assert value.run_once() == (Outcome.REJECTED,)
    assert value.transport.commits == 1


def test_export_with_wrong_upstream_binding_is_rejected(monkeypatch):
    value, _ = _working(monkeypatch)
    original = value.reader.rows
    value.reader.rows = lambda manifest, *, public_snapshot_id, public_result: (
        VerifiedWeeklyRows(
            original(
                manifest,
                public_snapshot_id=public_snapshot_id,
                public_result=public_result,
            ).metadata.model_copy(update={"total_active_repo_count": 0}),
            public_snapshot_id,
            original(
                manifest,
                public_snapshot_id=public_snapshot_id,
                public_result=public_result,
            ).rows,
        )
    )
    assert value.run_once() == (Outcome.REJECTED,)
    assert value.transport.commits == 1


def test_export_with_wrong_public_snapshot_binding_is_rejected(monkeypatch):
    value, _ = _working(monkeypatch)
    original = value.reader.rows
    value.reader.rows = lambda manifest, *, public_snapshot_id, public_result: (
        VerifiedWeeklyRows(
            original(
                manifest,
                public_snapshot_id=public_snapshot_id,
                public_result=public_result,
            ).metadata,
            "c-other-public",
            original(
                manifest,
                public_snapshot_id=public_snapshot_id,
                public_result=public_result,
            ).rows,
        )
    )
    assert value.run_once() == (Outcome.REJECTED,)
    assert value.transport.commits == 1


def test_artifacts_runs_real_archive_calculator_for_one_week():
    from test_trend_archive import _public, _record

    registry = TechnologyRegistry.model_validate_json(
        (
            Path(__file__).parents[1] / "registry/data/technology_registry_v1.json"
        ).read_text(encoding="utf-8")
    )
    public = _public(registry, (_record(1, tech_ids=("python",)),))
    payload = public.model_dump(mode="json")
    public_id = "c-" + digest(
        {"kind": "PUBLIC_GITHUB", "owner": None, "payload": payload}
    )
    store = SimpleNamespace(get_head_payloads=lambda **kwargs: {})
    value = WeeklyActivityConsumer(Transport([]), store, Never(), object(), registry)
    metadata = ArchiveActivityMetadata(
        source_schema_version="repo-activity-weekly/v1",
        source_version="spark-repo-activity-weekly/v1",
        dataset_snapshot_id="snapshot",
        source_uri="c-export://export/selected",
        source_hash="b" * 64,
        upstream_source_uri="hdfs:///weekly",
        upstream_source_hash="a" * 64,
        period="2026-09-07",
        granularity=PeriodGranularity.WEEK,
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=2,
        valid_event_count=2,
        total_active_repo_count=1,
        selection_event_coverage=1.0,
    )
    artifacts = value._artifacts(
        VerifiedWeeklyRows(
            metadata,
            public_id,
            (
                {
                    "repo_id": 1,
                    "repo_name": "owner/repo-1",
                    "week_start": "2026-09-07",
                    "event_count": 2,
                },
            ),
        ),
        public_id,
        payload,
        public,
        head_occurred_at=datetime.now(UTC),
    )
    assert len(artifacts) == len(
        [tech for tech in registry.technologies if tech.status.value == "ACTIVE"]
    )


def test_invalid_export_after_claim_releases_ticket_before_committing(monkeypatch):
    value, store = _working(monkeypatch)
    original = value.reader.rows
    value.reader.rows = lambda manifest, *, public_snapshot_id, public_result: replace(
        original(
            manifest,
            public_snapshot_id=public_snapshot_id,
            public_result=public_result,
        ),
        metadata=original(
            manifest,
            public_snapshot_id=public_snapshot_id,
            public_result=public_result,
        ).metadata.model_copy(update={"total_active_repo_count": 0}),
    )
    assert value.run_once() == (Outcome.REJECTED,)
    assert store.failed == ["WEEKLY_ACTIVITY_INVALID_INPUT"]
    assert value.transport.commits == 1


def test_failure_recording_error_keeps_offset_uncommitted(monkeypatch):
    value, store = _working(monkeypatch)
    value.public.select = lambda **kwargs: None
    store.fail = lambda ticket, code: (_ for _ in ()).throw(RuntimeError("db"))
    assert value.run_once() == (Outcome.RETRY,)
    assert value.transport.commits == 0


def _mounted_fixture(tmp_path: Path, *, exported_repo_id: int = 1):
    from jobs.export_c_archive_activity import (
        build_export_metadata,
        write_bounded_export,
    )
    from test_trend_archive import _public, _record

    registry = TechnologyRegistry.model_validate_json(
        (
            Path(__file__).parents[1] / "registry/data/technology_registry_v1.json"
        ).read_text(encoding="utf-8")
    )
    public = _public(registry, (_record(1, tech_ids=("python",)),))
    public_payload = public.model_dump(mode="json")
    public_id = "c-" + digest(
        {"kind": "PUBLIC_GITHUB", "owner": None, "payload": public_payload}
    )
    output = tmp_path / f"public={public_id}" / "snapshot=snapshot" / "week=2026-09-07"
    metadata = build_export_metadata(
        source_schema_version="repo-activity-weekly/v1",
        source_version="spark-repo-activity-weekly/v1",
        dataset_snapshot_id="snapshot",
        source_uri="hdfs:///weekly",
        source_hash="a" * 64,
        period="2026-09-07",
        granularity="WEEK",
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=2,
        valid_event_count=2,
        total_active_repo_count=1,
    )
    write_bounded_export(
        output,
        (
            {
                "repo_id": exported_repo_id,
                "repo_name": "owner/repo-1",
                "event_count": 2,
            },
        ),
        metadata,
        output_format="ndjson",
    )
    reader = MountedWeeklyExportReader(
        SimpleNamespace(read=lambda *a, **k: b""), tmp_path
    )
    return reader, WeeklyManifest.parse(_manifest()), public_id, public, output


def test_mounted_reader_consumes_real_export_without_invented_sidecar(tmp_path):
    reader, manifest, public_id, public, _ = _mounted_fixture(tmp_path)
    verified = reader.rows(manifest, public_snapshot_id=public_id, public_result=public)
    assert verified.metadata.granularity is PeriodGranularity.WEEK
    assert verified.rows[0]["repo_id"] == 1


def test_mounted_reader_retries_missing_export(tmp_path):
    reader = MountedWeeklyExportReader(
        SimpleNamespace(read=lambda *a, **k: b""), tmp_path
    )
    with pytest.raises(InputAdapterUnavailable):
        reader.rows(
            WeeklyManifest.parse(_manifest()),
            public_snapshot_id="c-" + "0" * 64,
            public_result=SimpleNamespace(records=()),
        )


def test_mounted_reader_rejects_manifest_extension_and_foreign_repo(tmp_path):
    reader, manifest, public_id, public, output = _mounted_fixture(tmp_path)
    manifest_path = output / "manifest.json"
    os.chmod(manifest_path, 0o644)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["unexpected"] = True
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported weekly export manifest"):
        reader.rows(manifest, public_snapshot_id=public_id, public_result=public)

    second = tmp_path / "foreign"
    second.mkdir()
    foreign_reader, foreign_manifest, foreign_id, foreign_public, _ = _mounted_fixture(
        second, exported_repo_id=2
    )
    with pytest.raises(ValueError, match="outside selected PUBLIC_GITHUB"):
        foreign_reader.rows(
            foreign_manifest,
            public_snapshot_id=foreign_id,
            public_result=foreign_public,
        )


def test_weekly_artifact_stream_accumulates_consecutive_points():
    from test_trend_archive import _public, _record

    registry = TechnologyRegistry.model_validate_json(
        (
            Path(__file__).parents[1] / "registry/data/technology_registry_v1.json"
        ).read_text(encoding="utf-8")
    )
    public = _public(registry, (_record(1, tech_ids=("python",)),))
    payload = public.model_dump(mode="json")
    public_id = "c-" + digest(
        {"kind": "PUBLIC_GITHUB", "owner": None, "payload": payload}
    )

    value = WeeklyActivityConsumer(Transport([]), object(), Never(), object(), registry)
    metadata = ArchiveActivityMetadata(
        source_schema_version="repo-activity-weekly/v1",
        source_version="spark-repo-activity-weekly/v1",
        dataset_snapshot_id="snapshot-1",
        source_uri="c-export://export/selected",
        source_hash="b" * 64,
        upstream_source_uri="hdfs:///weekly-1",
        upstream_source_hash="a" * 64,
        period="2026-09-07",
        granularity=PeriodGranularity.WEEK,
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=2,
        valid_event_count=2,
        total_active_repo_count=1,
        selection_event_coverage=1.0,
    )
    row = {
        "repo_id": 1,
        "repo_name": "owner/repo-1",
        "week_start": "2026-09-07",
        "event_count": 2,
    }
    first = value._artifacts(
        VerifiedWeeklyRows(metadata, public_id, (row,)),
        public_id,
        payload,
        public,
        head_occurred_at=datetime.now(UTC),
    )
    second_metadata = metadata.model_copy(
        update={
            "dataset_snapshot_id": "snapshot-2",
            "period": "2026-09-14",
            "upstream_source_uri": "hdfs:///weekly-2",
        }
    )
    second_row = {**row, "week_start": "2026-09-14"}
    second = value._artifacts(
        VerifiedWeeklyRows(second_metadata, public_id, (second_row,)),
        public_id,
        payload,
        public,
        head_occurred_at=datetime.now(UTC),
    )
    current_python = next(
        artifact for artifact in second if artifact.payload["tech_id"] == "python"
    )
    assert current_python.stream == next(
        artifact.stream for artifact in first if artifact.payload["tech_id"] == "python"
    )
    previous_python = next(
        artifact for artifact in first if artifact.payload["tech_id"] == "python"
    )
    merged = _merge_weekly_payloads(current_python.payload, previous_python.payload)
    assert [point["period"] for point in merged["points"]] == [
        "2026-09-07",
        "2026-09-14",
    ]
    assert merged["status"] == TrendStatus.READY.value


def test_public_snapshot_period_must_cover_requested_week():
    result = {
        "records": [
            {
                "included_in_denominator": True,
                "activity_period_start": "2026-08-01",
                "activity_period_end": "2026-08-31",
            }
        ]
    }
    assert _public_payload_covers_week(result, date(2026, 8, 24))
    assert not _public_payload_covers_week(result, date(2026, 9, 7))


def test_postgres_weekly_results_survive_restart_and_accumulate():
    from github.weekly_activity_publish import WeeklySnapshotWeek, build_manifest
    from test_trend_archive import _public, _record

    dsn = os.environ.get("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires isolated C_COMPUTE_TEST_DATABASE_URL")
    apply_migration(dsn)
    registry = TechnologyRegistry.model_validate_json(
        (
            Path(__file__).parents[1] / "registry/data/technology_registry_v1.json"
        ).read_text(encoding="utf-8")
    ).model_copy(update={"registry_version": f"same-publish-time-{uuid4()}"})
    public = _public(registry, (_record(1, tech_ids=("python",)),))
    public_payload = public.model_dump(mode="json")
    store = ComputeStore(dsn)
    public_ticket = store.claim(
        event_id=str(uuid4()),
        kind="PUBLIC_REPO",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"fixture": str(uuid4())},
    )
    store.complete(
        public_ticket,
        [Artifact("PUBLIC_GITHUB", None, public_payload, str(uuid4()))],
    )

    def process(week_start: str, dataset: str, *, ingested_at: datetime | None = None):
        data_uri = f"hdfs:///weekly/{dataset}"
        week = WeeklySnapshotWeek(week_start, data_uri, 1, "a" * 64)
        manifest_bytes = json.dumps(build_manifest(dataset, week)).encode()
        envelope = EventEnvelope(
            source="gharchive",
            source_id=f"{dataset}/{week_start}",
            event_type="RepoActivityWeeklySnapshotCompleted",
            occurred_at=datetime.fromisoformat(week_start).replace(tzinfo=UTC),
            ingested_at=ingested_at or datetime.now(UTC),
            payload={
                "dataset_snapshot_id": dataset,
                "week_start": week_start,
                "manifest_uri": f"{data_uri}/_SUCCESS.json",
            },
        )
        message = ConsumedMessage(
            WEEKLY_COMPLETED_TOPIC,
            0,
            0,
            envelope.source_id.encode(),
            envelope.to_bytes(),
        )

        class Reader:
            def read(self, uri, *, max_bytes):
                return manifest_bytes

            def rows(self, manifest, *, public_snapshot_id, public_result):
                return VerifiedWeeklyRows(
                    ArchiveActivityMetadata(
                        source_schema_version="repo-activity-weekly/v1",
                        source_version="spark-repo-activity-weekly/v1",
                        dataset_snapshot_id=dataset,
                        source_uri=f"c-export://{dataset}/activity.ndjson",
                        source_hash="b" * 64,
                        upstream_source_uri=data_uri,
                        upstream_source_hash="a" * 64,
                        period=week_start,
                        granularity=PeriodGranularity.WEEK,
                        top_n_limit=1,
                        selected_repo_count=1,
                        selected_event_count=2,
                        valid_event_count=2,
                        total_active_repo_count=1,
                        selection_event_coverage=1.0,
                    ),
                    public_snapshot_id,
                    (
                        {
                            "repo_id": 1,
                            "repo_name": "owner/repo-1",
                            "week_start": week_start,
                            "event_count": 2,
                        },
                    ),
                )

        transport = Transport([message])
        consumer = WeeklyActivityConsumer(
            transport,
            ComputeStore(dsn),
            Reader(),
            StorePublicSnapshotSelector(ComputeStore(dsn)),
            registry,
        )
        assert consumer.run_once() == (Outcome.COMPLETED,)
        assert transport.commits == 1

    # A publishes every week in one snapshot with the same ingestion timestamp.
    # Accumulation must not depend on the event-id hash used as a generic tie-break.
    published_at = datetime(2026, 9, 1, tzinfo=UTC)
    while True:
        dataset = f"weekly-batch-{uuid4()}"
        first_id = digest({"dataset_snapshot_id": dataset, "week_start": "2026-08-24"})
        second_id = digest({"dataset_snapshot_id": dataset, "week_start": "2026-08-31"})
        if second_id < first_id:
            break
    process("2026-08-24", dataset, ingested_at=published_at)
    process("2026-08-31", dataset, ingested_at=published_at)
    stream = digest(
        {
            "source": "WEEKLY_REPO_ACTIVITY",
            "tech_id": "python",
            "registry_version": registry.registry_version,
            "include_partial": False,
        }
    )
    restarted = ComputeStore(dsn)
    payload = restarted.get_head_payloads(kind="TREND", owner=None, streams=(stream,))[
        stream
    ]
    assert [point["period"] for point in payload["points"]] == [
        "2026-08-24",
        "2026-08-31",
    ]
    assert payload["status"] == TrendStatus.READY.value


def test_postgres_late_week_advances_head_without_changing_event_identity():
    from test_trend_archive import _public, _record

    dsn = os.environ.get("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires isolated C_COMPUTE_TEST_DATABASE_URL")
    apply_migration(dsn)
    registry = TechnologyRegistry.model_validate_json(
        (
            Path(__file__).parents[1] / "registry/data/technology_registry_v1.json"
        ).read_text(encoding="utf-8")
    ).model_copy(update={"registry_version": f"late-week-{uuid4()}"})
    public = _public(registry, (_record(1, tech_ids=("python",)),))
    store = ComputeStore(dsn)
    public_ticket = store.claim(
        event_id=str(uuid4()),
        kind="PUBLIC_REPO",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"fixture": str(uuid4())},
    )
    store.complete(
        public_ticket,
        [
            Artifact(
                "PUBLIC_GITHUB",
                None,
                public.model_dump(mode="json"),
                str(uuid4()),
            )
        ],
    )

    def process(week_start: str, ingested_at: datetime):
        dataset = f"weekly-{uuid4()}"
        data_uri = f"hdfs:///weekly/{dataset}"
        envelope = EventEnvelope(
            source="gharchive",
            source_id=f"{dataset}/{week_start}",
            event_type="RepoActivityWeeklySnapshotCompleted",
            occurred_at=datetime.fromisoformat(week_start).replace(tzinfo=UTC),
            ingested_at=ingested_at,
            payload={
                "dataset_snapshot_id": dataset,
                "week_start": week_start,
                "manifest_uri": f"{data_uri}/_SUCCESS.json",
            },
        )
        message = ConsumedMessage(
            WEEKLY_COMPLETED_TOPIC,
            0,
            0,
            envelope.source_id.encode(),
            envelope.to_bytes(),
        )

        class Reader:
            def read(self, uri, *, max_bytes):
                return _manifest(
                    dataset_snapshot_id=dataset,
                    week_start=week_start,
                    data_uri=data_uri,
                )

            def rows(self, manifest, *, public_snapshot_id, public_result):
                return VerifiedWeeklyRows(
                    ArchiveActivityMetadata(
                        source_schema_version="repo-activity-weekly/v1",
                        source_version="spark-repo-activity-weekly/v1",
                        dataset_snapshot_id=dataset,
                        source_uri=f"c-export://{dataset}/activity.ndjson",
                        source_hash="b" * 64,
                        upstream_source_uri=data_uri,
                        upstream_source_hash="a" * 64,
                        period=week_start,
                        granularity=PeriodGranularity.WEEK,
                        top_n_limit=1,
                        selected_repo_count=1,
                        selected_event_count=2,
                        valid_event_count=2,
                        total_active_repo_count=1,
                        selection_event_coverage=1.0,
                    ),
                    public_snapshot_id,
                    (
                        {
                            "repo_id": 1,
                            "repo_name": "owner/repo-1",
                            "week_start": week_start,
                            "event_count": 2,
                        },
                    ),
                )

        transport = Transport([message])
        consumer = WeeklyActivityConsumer(
            transport,
            store,
            Reader(),
            StorePublicSnapshotSelector(store),
            registry,
        )
        assert consumer.run_once() == (Outcome.COMPLETED,)
        assert transport.commits == 1

    process("2026-08-24", datetime(2026, 9, 1, tzinfo=UTC))
    process("2026-08-17", datetime(2026, 9, 2, tzinfo=UTC))
    stream = digest(
        {
            "source": "WEEKLY_REPO_ACTIVITY",
            "tech_id": "python",
            "registry_version": registry.registry_version,
            "include_partial": False,
        }
    )
    payload = store.get_head_payloads(kind="TREND", owner=None, streams=(stream,))[
        stream
    ]
    assert [point["period"] for point in payload["points"]] == [
        "2026-08-17",
        "2026-08-24",
    ]
    assert payload["status"] == TrendStatus.READY.value
