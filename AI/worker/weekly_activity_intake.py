"""Fail-closed consumer for A's weekly Repo Activity completion event."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from common.events import EventEnvelope
from common.kafka import ConsumedMessage, ConsumerTransport
from common.webhdfs import WebHdfsError
from github.public_analysis import PublicBatchResult
from trend.archive import (
    ArchiveActivityMetadata,
    ArchivePeriodInput,
    ArchiveTrendResult,
    PeriodGranularity,
    archive_trend,
    iter_bounded_activity_stream,
)
from trend.contracts import TrendStatus
from worker.lease import LeaseHeartbeat
from worker.store import Artifact, IdempotencyConflict, digest
from worker.trend_streams import weekly_activity_trend_stream

WEEKLY_COMPLETED_TOPIC = "gitjob.repo-activity-weekly.completed.v1"
WEEKLY_SOURCE = "gharchive"
WEEKLY_EVENT_TYPE = "RepoActivityWeeklySnapshotCompleted"
MANIFEST_SCHEMA = "repo-activity-weekly-publish-manifest/v1"
ROW_DIGEST_FORMAT = "typed-json-v2"
MAX_MANIFEST_BYTES = 1_048_576
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_EXPORT_ROWS = 50_000

LOGGER = logging.getLogger(__name__)


class InputAdapterUnavailable(RuntimeError):
    """A has not supplied a C-readable bounded activity export."""


class RetryableWeeklyError(RuntimeError):
    """The record must remain uncommitted for redelivery."""


class WeeklyInputReader(Protocol):
    def read(self, uri: str, *, max_bytes: int) -> bytes: ...

    def rows(
        self,
        manifest: WeeklyManifest,
        *,
        public_snapshot_id: str,
        public_result: PublicBatchResult,
    ) -> VerifiedWeeklyRows: ...


class PublicSnapshotSelector(Protocol):
    def select(
        self, *, registry_version: str, include_partial: bool, week_start: str
    ) -> tuple[str, dict[str, object]] | None: ...


@dataclass(frozen=True)
class StorePublicSnapshotSelector:
    """Production adapter over ComputeStore's immutable PUBLIC_GITHUB heads."""

    store: Any

    def select(
        self, *, registry_version: str, include_partial: bool, week_start: str
    ) -> tuple[str, dict[str, object]] | None:
        return self.store.select_public_snapshot(
            registry_version=registry_version,
            include_partial=include_partial,
            week_start=week_start,
        )


class UnavailableWeeklyInputReader:
    """Safe default: worker has no Spark/Hadoop/Parquet runtime."""

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        raise InputAdapterUnavailable("INPUT_ADAPTER_UNAVAILABLE")

    def rows(
        self,
        manifest: WeeklyManifest,
        *,
        public_snapshot_id: str,
        public_result: PublicBatchResult,
    ) -> VerifiedWeeklyRows:
        raise InputAdapterUnavailable("INPUT_ADAPTER_UNAVAILABLE")


@dataclass(frozen=True)
class MountedWeeklyExportReader:
    """Read A's HDFS completion manifest and C's mounted bounded export.

    Export layout is deterministic and produced by the existing exporter:
    ``<root>/public=<id>/snapshot=<id>/week=<date>/{manifest,metadata,activity.*}``.
    """

    manifest_reader: Any
    export_root: Path

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        try:
            return self.manifest_reader.read(uri, max_bytes=max_bytes)
        except (OSError, WebHdfsError) as error:
            raise InputAdapterUnavailable("HDFS_UNAVAILABLE") from error

    def rows(
        self,
        manifest: WeeklyManifest,
        *,
        public_snapshot_id: str,
        public_result: PublicBatchResult,
    ) -> VerifiedWeeklyRows:
        try:
            root = self.export_root.resolve(strict=True)
            directory = (
                root
                / f"public={public_snapshot_id}"
                / f"snapshot={manifest.dataset_snapshot_id}"
                / f"week={manifest.week_start}"
            ).resolve(strict=True)
        except OSError as error:
            raise InputAdapterUnavailable("INPUT_ADAPTER_UNAVAILABLE") from error
        if not directory.is_relative_to(root):
            raise ValueError("weekly export path escapes configured root")

        def bounded(name: str, limit: int) -> bytes:
            try:
                path = (directory / name).resolve(strict=True)
                if not path.is_relative_to(directory) or not path.is_file():
                    raise ValueError("weekly export file escapes directory")
                with path.open("rb") as stream:
                    value = stream.read(limit + 1)
            except OSError as error:
                raise InputAdapterUnavailable("INPUT_ADAPTER_UNAVAILABLE") from error
            if len(value) > limit:
                raise ValueError("weekly export exceeds byte limit")
            return value

        try:
            raw = bounded("manifest.json", MAX_MANIFEST_BYTES)
            exported = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("malformed weekly export manifest") from error
        required = {
            "schema_version",
            "data_file",
            "data_sha256",
            "metadata_file",
            "metadata_sha256",
            "record_count",
        }
        if (
            not isinstance(exported, dict)
            or set(exported) != required
            or exported.get("schema_version") != "c-archive-activity-export/v1"
            or exported.get("metadata_file") != "metadata.json"
            or exported.get("data_file") not in {"activity.csv", "activity.ndjson"}
            or type(exported.get("record_count")) is not int
            or not 0 <= exported["record_count"] <= MAX_EXPORT_ROWS
            or any(
                not isinstance(exported.get(field), str)
                or len(exported[field]) != 64
                or any(
                    character not in "0123456789abcdef" for character in exported[field]
                )
                for field in ("data_sha256", "metadata_sha256")
            )
        ):
            raise ValueError("unsupported weekly export manifest")
        data_bytes, metadata_bytes = (
            bounded(exported["data_file"], MAX_EXPORT_BYTES),
            bounded("metadata.json", MAX_MANIFEST_BYTES),
        )
        if (
            hashlib.sha256(data_bytes).hexdigest() != exported["data_sha256"]
            or hashlib.sha256(metadata_bytes).hexdigest() != exported["metadata_sha256"]
        ):
            raise ValueError("weekly export checksum mismatch")
        try:
            metadata = ArchiveActivityMetadata.model_validate_json(metadata_bytes)
        except ValueError as error:
            raise ValueError("malformed weekly export metadata") from error
        if (
            metadata.dataset_snapshot_id != manifest.dataset_snapshot_id
            or metadata.period != manifest.week_start
        ):
            raise ValueError("weekly export metadata identity mismatch")
        if metadata.top_n_limit > MAX_EXPORT_ROWS:
            raise ValueError("weekly export row budget exceeds C limit")
        try:
            text = data_bytes.decode("utf-8-sig")
            rows = tuple(
                iter_bounded_activity_stream(
                    io.StringIO(text),
                    suffix=Path(exported["data_file"]).suffix,
                    granularity=PeriodGranularity.WEEK,
                    max_rows=MAX_EXPORT_ROWS,
                )
            )
        except (
            UnicodeDecodeError,
            csv.Error,
            json.JSONDecodeError,
            TypeError,
        ) as error:
            raise ValueError("malformed weekly activity rows") from error
        eligible = {
            record.github_repo_id
            for record in public_result.records
            if record.included_in_denominator
        }
        if any(
            not isinstance(row, dict) or row.get("repo_id") not in eligible
            for row in rows
        ):
            raise ValueError("weekly export rows are outside selected PUBLIC_GITHUB")
        if (
            exported["record_count"] != len(rows)
            or metadata.selected_repo_count != len(rows)
            or metadata.selected_event_count
            != sum(int(row["event_count"]) for row in rows)
        ):
            raise ValueError("weekly export counts do not reconcile")
        return VerifiedWeeklyRows(metadata, public_snapshot_id, rows)


class Outcome(StrEnum):
    COMPLETED = "COMPLETED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    RETRY = "RETRY"


def _monday(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("week_start must be canonical ISO Monday")
    try:
        day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError as error:
        raise ValueError("week_start must be canonical ISO Monday") from error
    if day.isoformat() != value or day.weekday() != 0:
        raise ValueError("week_start must be canonical ISO Monday")
    return value


@dataclass(frozen=True)
class WeeklyManifest:
    dataset_snapshot_id: str
    week_start: str
    data_uri: str
    row_count: int
    row_digest: str

    @classmethod
    def parse(cls, raw: bytes) -> WeeklyManifest:
        try:
            value = json.loads(raw)
            checksum = value["row_digest"]
            result = cls(
                value["dataset_snapshot_id"],
                value["week_start"],
                value["data_uri"],
                value["row_count"],
                checksum["value"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("malformed weekly manifest") from error
        expected = {
            "schema_version",
            "dataset_snapshot_id",
            "week_start",
            "data_uri",
            "row_count",
            "row_digest",
        }
        if (
            not isinstance(value, dict)
            or set(value) != expected
            or value["schema_version"] != MANIFEST_SCHEMA
            or not isinstance(checksum, dict)
            or set(checksum) != {"format", "value"}
            or checksum["format"] != ROW_DIGEST_FORMAT
            or not isinstance(result.dataset_snapshot_id, str)
            or not result.dataset_snapshot_id
            or not isinstance(result.data_uri, str)
            or not result.data_uri
            or type(result.row_count) is not int
            or result.row_count < 0
            or not isinstance(result.row_digest, str)
            or len(result.row_digest) != 64
            or any(c not in "0123456789abcdef" for c in result.row_digest)
        ):
            raise ValueError("invalid weekly manifest contract")
        _monday(result.week_start)
        return result


@dataclass(frozen=True)
class VerifiedWeeklyRows:
    """Reader proof that its bounded export still names A's exact weekly rows."""

    metadata: ArchiveActivityMetadata
    public_snapshot_id: str
    rows: tuple[dict[str, object], ...]


def _event(message: ConsumedMessage) -> tuple[EventEnvelope, dict[str, object]]:
    if message.topic != WEEKLY_COMPLETED_TOPIC:
        raise ValueError("unexpected weekly completion topic")
    try:
        raw = json.loads(message.value)
        for field in ("occurred_at", "ingested_at"):
            raw[field] = datetime.fromisoformat(raw[field].replace("Z", "+00:00"))
        envelope = EventEnvelope(**raw)
        payload = envelope.payload
        snapshot, week, uri = (
            payload["dataset_snapshot_id"],
            payload["week_start"],
            payload["manifest_uri"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("malformed weekly completion event") from error
    if (
        envelope.source != WEEKLY_SOURCE
        or envelope.event_type != WEEKLY_EVENT_TYPE
        or set(payload) != {"dataset_snapshot_id", "week_start", "manifest_uri"}
        or not all(isinstance(x, str) and x for x in (snapshot, week, uri))
        or envelope.source_id != f"{snapshot}/{week}"
        or message.key != envelope.source_id.encode()
    ):
        raise ValueError("weekly completion event identity mismatch")
    _monday(week)
    return envelope, dict(payload)


@dataclass
class WeeklyActivityConsumer:
    transport: ConsumerTransport
    store: Any
    reader: WeeklyInputReader
    public: PublicSnapshotSelector
    registry: Any
    include_partial: bool = False
    poll_timeout_ms: int = 1_000
    tally: dict[str, int] = field(default_factory=dict)
    last_retry_code: str | None = field(default=None, init=False)

    def handle(self, message: ConsumedMessage) -> Outcome:
        ticket = None
        try:
            envelope, payload = _event(message)
            manifest_bytes = self.reader.read(
                payload["manifest_uri"], max_bytes=MAX_MANIFEST_BYTES
            )
            manifest = WeeklyManifest.parse(manifest_bytes)
            if (
                manifest.dataset_snapshot_id != payload["dataset_snapshot_id"]
                or manifest.week_start != payload["week_start"]
                or payload["manifest_uri"].rstrip("/")
                != manifest.data_uri.rstrip("/") + "/_SUCCESS.json"
            ):
                raise ValueError("weekly event and manifest disagree")
            identity = {
                "dataset_snapshot_id": manifest.dataset_snapshot_id,
                "week_start": manifest.week_start,
            }
            ticket = self.store.claim(
                event_id="weekly-activity-" + digest(identity),
                kind="TREND",
                owner=None,
                occurred_at=envelope.occurred_at.astimezone(UTC),
                # Only what A published: the week, and the bytes it published
                # for that week. `registry_version` used to be in here, but it
                # is resolved from whichever registry row is CURRENT at
                # processing time, so a registry change turned the same Kafka
                # record into a different request and the ticket could never be
                # claimed again (S15P21E102-283). `include_partial` and
                # `algorithm_version` are the same kind of value — how C
                # computes, not what A sent — and they are already recorded
                # where they belong, in the artifact stream key and the
                # archived Trend result.
                request={
                    **identity,
                    "manifest_uri": payload["manifest_uri"],
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
            )
            if ticket.status == "COMPLETED":
                return self._count(Outcome.DUPLICATE)
            if ticket.token is None:
                raise RetryableWeeklyError("WEEKLY_ACTIVITY_CLAIM_BUSY")
            selection = self.public.select(
                registry_version=self.registry.registry_version,
                include_partial=self.include_partial,
                week_start=manifest.week_start,
            )
            if selection is None:
                raise RetryableWeeklyError("PUBLIC_GITHUB_NOT_READY")
            public_id, public_payload = selection
            public_result = PublicBatchResult.model_validate(
                public_payload.get("result", public_payload)
            )
            if (
                public_result.registry_version != self.registry.registry_version
                or public_result.include_partial != self.include_partial
            ):
                raise RetryableWeeklyError("PUBLIC_GITHUB_NOT_READY")
            verified = self.reader.rows(
                manifest, public_snapshot_id=public_id, public_result=public_result
            )
            if (
                verified.metadata.dataset_snapshot_id != manifest.dataset_snapshot_id
                or verified.metadata.period != manifest.week_start
                or verified.metadata.granularity is not PeriodGranularity.WEEK
                or verified.metadata.upstream_source_uri != manifest.data_uri
                or verified.metadata.upstream_source_hash != manifest.row_digest
                or verified.metadata.total_active_repo_count != manifest.row_count
                or verified.public_snapshot_id != public_id
                or len(verified.rows) != verified.metadata.selected_repo_count
            ):
                raise ValueError("weekly activity export binding mismatch")
            return self._compute(
                envelope,
                payload,
                ticket,
                verified,
                public_id,
                public_payload,
                public_result,
            )
        except (RetryableWeeklyError, InputAdapterUnavailable) as error:
            code = _retry_code(error)
            self.last_retry_code = code
            LOGGER.warning(
                "weekly activity retry reason=%s topic=%s partition=%s offset=%s key=%r",
                code,
                message.topic,
                message.partition,
                message.offset,
                message.key,
            )
            if not self._fail_owned(ticket, code):
                return self._count(Outcome.RETRY)
            return self._count(Outcome.RETRY)
        # Must precede the ValueError clause: IdempotencyConflict subclasses it.
        # A conflict means the store refused to hand us the ticket, so nothing
        # was computed — REJECTED would commit the offset and drop the event
        # silently, which is how the 2026-03-02 week was lost. RETRY leaves the
        # record uncommitted, so the failure is loud and the event survives
        # the consumer reconnect (S15P21E102-283).
        except IdempotencyConflict:
            self.last_retry_code = "WEEKLY_ACTIVITY_IDEMPOTENCY_CONFLICT"
            LOGGER.warning(
                "weekly activity retry reason=%s topic=%s partition=%s offset=%s key=%r",
                self.last_retry_code,
                message.topic,
                message.partition,
                message.offset,
                message.key,
            )
            self._fail_owned(ticket, self.last_retry_code)
            return self._count(Outcome.RETRY)
        except (ValueError, TypeError, KeyError):
            if not self._fail_owned(ticket, "WEEKLY_ACTIVITY_INVALID_INPUT"):
                self.last_retry_code = "WEEKLY_ACTIVITY_FAILURE_RECORDING_FAILED"
                return self._count(Outcome.RETRY)
            return self._count(Outcome.REJECTED)

    def _compute(
        self,
        envelope,
        payload,
        ticket,
        verified,
        public_id,
        public_payload,
        public_result,
    ) -> Outcome:
        try:
            with LeaseHeartbeat(self.store, ticket):
                self.store.complete(
                    ticket,
                    self._artifacts(
                        verified,
                        public_id,
                        public_payload,
                        public_result,
                        head_occurred_at=envelope.ingested_at.astimezone(UTC),
                    ),
                    head_merger=_merge_weekly_payloads,
                )
        except Exception as error:
            raise RetryableWeeklyError("WEEKLY_ACTIVITY_COMPUTE_FAILED") from error
        return self._count(Outcome.COMPLETED)

    def _artifacts(
        self,
        verified,
        public_id,
        public_payload: Mapping[str, object],
        public_result,
        *,
        head_occurred_at: datetime,
    ) -> list[Artifact]:
        metadata = verified.metadata
        item = ArchivePeriodInput(
            metadata=metadata,
            activity_rows=verified.rows,
            public_analysis=public_result,
            public_snapshot_payload=dict(public_payload),
            public_snapshot_uri=f"c-compute://snapshot/{public_id}",
            public_snapshot_hash=digest(public_payload),
        )
        active = tuple(
            tech for tech in self.registry.technologies if tech.status.value == "ACTIVE"
        )
        streams = {
            tech.tech_id: weekly_activity_trend_stream(
                tech_id=tech.tech_id,
                registry_version=self.registry.registry_version,
                include_partial=self.include_partial,
            )
            for tech in active
        }
        artifacts = []
        for tech in active:
            current = archive_trend(
                tech.tech_id,
                (item,),
                self.registry,
                periods=(metadata.period,),
                granularity=PeriodGranularity.WEEK,
                include_partial=self.include_partial,
            )
            stream = streams[tech.tech_id]
            artifacts.append(
                Artifact(
                    "TREND",
                    None,
                    current.model_dump(mode="json"),
                    stream,
                    # The event time is the week being described and must stay
                    # stable for idempotency.  Head ordering follows A's
                    # publication time so a late backfill can advance the
                    # cumulative series without making a replay look new.
                    head_occurred_at=head_occurred_at,
                )
            )
        return artifacts

    def run_once(self) -> tuple[Outcome, ...]:
        self.last_retry_code = None
        outcomes = tuple(
            self.handle(message)
            for message in self.transport.poll(self.poll_timeout_ms)
        )
        if outcomes and Outcome.RETRY not in outcomes:
            self.transport.commit()
        return outcomes

    def _count(self, outcome: Outcome) -> Outcome:
        self.tally[outcome.value] = self.tally.get(outcome.value, 0) + 1
        return outcome

    def _fail_owned(self, ticket: Any, code: str) -> bool:
        if ticket is None or ticket.token is None:
            return True
        try:
            self.store.fail(ticket, code)
        except (OSError, RuntimeError):
            return False
        return True


def _retry_code(error: RetryableWeeklyError | InputAdapterUnavailable) -> str:
    code = str(error).strip()
    if (
        code
        and len(code) <= 128
        and code.replace("_", "").isalnum()
        and code == code.upper()
    ):
        return code
    return "WEEKLY_ACTIVITY_RETRY"


def _merge_weekly_result(
    current: ArchiveTrendResult, previous_payload: Mapping[str, object] | None
) -> ArchiveTrendResult:
    if previous_payload is None:
        return current
    try:
        previous = ArchiveTrendResult.model_validate(previous_payload)
    except ValueError as error:
        raise RetryableWeeklyError("WEEKLY_TREND_HISTORY_INVALID") from error
    if (
        previous.tech_id != current.tech_id
        or previous.registry_version != current.registry_version
        or previous.algorithm_version != current.algorithm_version
        or previous.granularity is not PeriodGranularity.WEEK
        or previous.include_partial != current.include_partial
    ):
        raise RetryableWeeklyError("WEEKLY_TREND_HISTORY_INCOMPATIBLE")
    by_period = {point.period: point for point in previous.points}
    by_period.update((point.period, point) for point in current.points)
    points = tuple(by_period[period] for period in sorted(by_period))
    consecutive = all(
        date.fromisoformat(points[index].period)
        == date.fromisoformat(points[index - 1].period) + timedelta(days=7)
        for index in range(1, len(points))
    )
    ready = (
        len(points) >= 2
        and consecutive
        and all(point.status is TrendStatus.READY for point in points)
    )
    return ArchiveTrendResult.model_validate(
        {
            **current.model_dump(mode="python"),
            "status": TrendStatus.READY if ready else TrendStatus.INSUFFICIENT_DATA,
            "reasons": () if ready else ("MISSING_PERIOD_BASELINE_OR_QUALITY",),
            "points": points,
        }
    )


def _merge_weekly_payloads(
    current_payload: Mapping[str, object],
    previous_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    current = ArchiveTrendResult.model_validate(current_payload)
    return _merge_weekly_result(current, previous_payload).model_dump(mode="json")
