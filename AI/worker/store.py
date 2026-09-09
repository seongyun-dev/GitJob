"""PostgreSQL snapshots and fenced, retry-safe completion of C compute events."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATION_VERSION = 1
MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/001_c_compute.sql"
)


class IdempotencyConflict(ValueError):
    """The caller reused an event ID for a different immutable request."""


class LeaseLost(RuntimeError):
    """Another attempt owns the event, or this attempt's lease expired."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def apply_migration(dsn: str, path: Path = MIGRATION_FILE) -> None:
    """Explicit operator action, never run as an application startup side effect."""
    source = path.read_bytes()
    checksum = hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET LOCAL statement_timeout = '15s'")
        conn.execute("SELECT pg_advisory_xact_lock(331029)")
        exists = conn.execute(
            "SELECT to_regclass('c_compute.schema_version')"
        ).fetchone()[0]
        if exists:
            row = conn.execute(
                "SELECT checksum FROM c_compute.schema_version WHERE version = %s",
                (MIGRATION_VERSION,),
            ).fetchone()
            if row:
                if row[0] != checksum:
                    raise ValueError(
                        "C migration checksum mismatch; do not rewrite applied DDL"
                    )
                return
        conn.execute(source.decode("utf-8"))
        conn.execute(
            "INSERT INTO c_compute.schema_version(version, checksum) VALUES (%s, %s)",
            (MIGRATION_VERSION, checksum),
        )


@dataclass(frozen=True)
class Artifact:
    kind: str
    owner: str | None
    payload: dict[str, Any]
    stream: str

    def __post_init__(self):
        if self.kind not in {
            "COHORT",
            "DEMAND",
            "RECOMMENDATION",
            "PUBLIC_GITHUB",
            "TREND",
        }:
            raise ValueError("unsupported snapshot kind")
        if (self.kind == "RECOMMENDATION") != bool(self.owner):
            raise ValueError("only recommendation snapshots have a user owner")
        if not self.stream or len(self.stream) > 160:
            raise ValueError("invalid snapshot stream")

    @property
    def snapshot_id(self) -> str:
        return "c-" + digest(
            {"kind": self.kind, "owner": self.owner, "payload": self.payload}
        )


@dataclass(frozen=True)
class Ticket:
    event_id: str
    kind: str
    owner: str | None
    occurred_at: datetime
    status: str
    token: str | None
    attempt: int
    results: list[dict[str, str]]


class ComputeStore:
    def __init__(self, dsn: str, *, lease_seconds: int = 120):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        self._dsn = dsn
        self.lease_seconds = lease_seconds

    def _connect(self):
        return psycopg.connect(
            self._dsn,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c statement_timeout=15000 -c lock_timeout=5000",
        )

    def ready(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version FROM c_compute.schema_version WHERE version = %s",
                (MIGRATION_VERSION,),
            ).fetchone()
            return row is not None

    def bind_job_inputs(self, inputs: dict[str, tuple[str, str]]) -> None:
        """Pin verified completion paths before publishing, independently of compute versions.

        These completed validation events have no result snapshots. Reusing the
        existing event ledger keeps the first byte binding durable across restarts.
        """
        if not inputs:
            return
        expected = {
            "job-input-" + digest(path): digest(
                {"path": path, "batch_sha256": hashes[0], "manifest_sha256": hashes[1]}
            )
            for path, hashes in inputs.items()
        }
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO c_compute.event
                       (event_id, kind, owner, request_hash, occurred_at, state,
                        lease_token, lease_until, attempt)
                       VALUES (%s, 'JOB_INPUT', '', %s, clock_timestamp(), 'COMPLETED',
                               %s, clock_timestamp(), 1)
                       ON CONFLICT (event_id) DO NOTHING""",
                    [(key, expected[key], uuid4()) for key in sorted(expected)],
                )
            rows = conn.execute(
                "SELECT event_id, kind, owner, request_hash FROM c_compute.event "
                "WHERE event_id = ANY(%s)",
                (list(expected),),
            ).fetchall()
            if len(rows) != len(expected) or any(
                row["kind"] != "JOB_INPUT"
                or row["owner"] != ""
                or row["request_hash"] != expected[row["event_id"]]
                for row in rows
            ):
                raise IdempotencyConflict("verified completion input was replaced")

    def claim(
        self,
        *,
        event_id: str,
        kind: str,
        owner: str | None,
        occurred_at: datetime,
        request: dict[str, Any],
    ) -> Ticket:
        if (
            not event_id
            or len(event_id) > 128
            or kind not in {"JOB_BATCH", "ANALYSIS", "PUBLIC_REPO", "TREND"}
        ):
            raise ValueError("invalid event identity")
        if occurred_at.tzinfo is None:
            raise ValueError("event timestamp needs a timezone")
        if (kind == "ANALYSIS") != bool(owner) or (owner and len(owner) > 128):
            raise ValueError("invalid event owner")
        request_hash = digest(
            {
                "kind": kind,
                "owner": owner,
                "request": request,
                "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            }
        )
        token = uuid4()
        with self._connect() as conn:
            inserted = conn.execute(
                """INSERT INTO c_compute.event
                   (event_id, kind, owner, request_hash, occurred_at, state,
                    lease_token, lease_until, attempt)
                   VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s,
                           clock_timestamp() + %s * interval '1 second', 1)
                   ON CONFLICT (event_id) DO NOTHING RETURNING event_id""",
                (
                    event_id,
                    kind,
                    owner or "",
                    request_hash,
                    occurred_at,
                    token,
                    self.lease_seconds,
                ),
            ).fetchone()
            row = conn.execute(
                "SELECT *, lease_until > clock_timestamp() AS lease_alive "
                "FROM c_compute.event WHERE event_id = %s FOR UPDATE",
                (event_id,),
            ).fetchone()
            if (
                row["request_hash"] != request_hash
                or row["owner"] != (owner or "")
                or row["kind"] != kind
            ):
                raise IdempotencyConflict(
                    "event ID already has different content or scope"
                )
            if inserted:
                ticket_token = str(token)
            elif row["state"] == "COMPLETED" or (
                row["state"] == "RUNNING" and row["lease_alive"]
            ):
                ticket_token = None
            else:
                row = conn.execute(
                    """UPDATE c_compute.event SET state = 'RUNNING', lease_token = %s,
                       lease_until = clock_timestamp() + %s * interval '1 second',
                       attempt = attempt + 1, error_code = NULL, updated_at = clock_timestamp()
                       WHERE event_id = %s RETURNING *""",
                    (token, self.lease_seconds, event_id),
                ).fetchone()
                ticket_token = str(token)
            return Ticket(
                event_id,
                kind,
                owner,
                occurred_at,
                row["state"],
                ticket_token,
                row["attempt"],
                row["results"],
            )

    def renew(self, ticket: Ticket) -> bool:
        """Extend only this still-live RUNNING attempt; never resurrect a lease."""
        if ticket.token is None:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE c_compute.event
                   SET lease_until = clock_timestamp() + %s * interval '1 second',
                       updated_at = clock_timestamp()
                   WHERE event_id = %s AND kind = %s AND owner = %s
                     AND lease_token = %s AND state = 'RUNNING'
                     AND lease_until > clock_timestamp()
                   RETURNING event_id""",
                (
                    self.lease_seconds,
                    ticket.event_id,
                    ticket.kind,
                    ticket.owner or "",
                    ticket.token,
                ),
            ).fetchone()
            return row is not None

    def complete(
        self, ticket: Ticket, artifacts: list[Artifact]
    ) -> list[dict[str, str]]:
        allowed = {
            "JOB_BATCH": {"COHORT", "DEMAND"},
            "ANALYSIS": {"RECOMMENDATION"},
            "PUBLIC_REPO": {"PUBLIC_GITHUB"},
            "TREND": {"TREND"},
        }[ticket.kind]
        if not artifacts or any(
            a.kind not in allowed or a.owner != ticket.owner for a in artifacts
        ):
            raise ValueError("result scope does not match event")
        if len({(a.kind, a.stream) for a in artifacts}) != len(artifacts):
            raise ValueError("duplicate result stream")
        results = [{"kind": a.kind, "snapshot_id": a.snapshot_id} for a in artifacts]
        with self._connect() as conn:
            row = conn.execute(
                """SELECT event_id FROM c_compute.event
                   WHERE event_id = %s AND lease_token = %s AND kind = %s AND owner = %s AND state = 'RUNNING'
                     AND lease_until > clock_timestamp() FOR UPDATE""",
                (ticket.event_id, ticket.token, ticket.kind, ticket.owner or ""),
            ).fetchone()
            if not row:
                raise LeaseLost("attempt no longer owns a live lease")
            for artifact in artifacts:
                conn.execute(
                    """INSERT INTO c_compute.snapshot(snapshot_id, kind, owner, payload)
                       VALUES (%s, %s, %s, %s) ON CONFLICT(snapshot_id) DO NOTHING""",
                    (
                        artifact.snapshot_id,
                        artifact.kind,
                        artifact.owner or "",
                        Jsonb(artifact.payload),
                    ),
                )
                conn.execute(
                    """INSERT INTO c_compute.head(kind, owner, stream, snapshot_id, occurred_at, event_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT(kind, owner, stream) DO UPDATE
                       SET snapshot_id = EXCLUDED.snapshot_id, occurred_at = EXCLUDED.occurred_at,
                           event_id = EXCLUDED.event_id
                       WHERE (EXCLUDED.occurred_at, EXCLUDED.event_id) >
                             (c_compute.head.occurred_at, c_compute.head.event_id)""",
                    (
                        artifact.kind,
                        artifact.owner or "",
                        artifact.stream,
                        artifact.snapshot_id,
                        ticket.occurred_at,
                        ticket.event_id,
                    ),
                )
            conn.execute(
                """UPDATE c_compute.event SET state = 'COMPLETED', results = %s,
                   error_code = NULL, updated_at = clock_timestamp() WHERE event_id = %s""",
                (Jsonb(results), ticket.event_id),
            )
        return results

    def fail(self, ticket: Ticket, code: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE c_compute.event SET state = 'FAILED', error_code = %s,
                   updated_at = clock_timestamp()
                   WHERE event_id = %s AND lease_token = %s AND state = 'RUNNING'""",
                (code, ticket.event_id, ticket.token),
            )

    def get_snapshot(self, snapshot_id: str, *, owner: str | None) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id, kind, payload FROM c_compute.snapshot "
                "WHERE snapshot_id = %s AND owner = %s",
                (snapshot_id, owner or ""),
            ).fetchone()
            return dict(row) if row else None

    def get_head(self, kind: str, owner: str | None, stream: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id FROM c_compute.head WHERE kind = %s AND owner = %s AND stream = %s",
                (kind, owner or "", stream),
            ).fetchone()
            return row["snapshot_id"] if row else None
