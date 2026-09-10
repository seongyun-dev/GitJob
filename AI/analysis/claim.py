"""Exactly-once-ish handling on top of at-least-once delivery.

The request topic is fed by Debezium, which is at-least-once, and the runbook
has an operator re-publish an event by hand. So the same `event_id` arrives more
than once by design, and cloning twice wastes a GitHub round trip and a disk.

### Why this table and not `analysis_job.status`

`analysis_job` belongs to the Spring service: it is a mapped JPA entity, the
deployment runs with `ddl-auto=validate`, and B owns the status vocabulary.
A second writer in another language turns every column change into a two-repo
migration. This schema is the worker's own, the way `c_compute` is C's.

Job status still has to move eventually; that travels back over the results
topic so B stays the only writer of its own table.

### Why a claim can be taken over

A worker that dies mid-clone leaves a row in `CLONING` that nobody will ever
finish. Without a takeover rule that event is stuck forever. The rule is a
lease: a `CLONING` row older than the lease is fair game. The lease therefore
has to be longer than the slowest clone, or two workers will run at once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import psycopg
from psycopg.conninfo import make_conninfo

__all__ = ["Claim", "ClaimStatus", "ClaimStore", "connect", "dsn_from_env"]

MIGRATION_VERSION = 1


class ClaimStatus(str, Enum):
    """Whether a delivery may run, must retry, or is already complete."""

    ACQUIRED = "ACQUIRED"
    BUSY = "BUSY"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class Claim:
    """A claim decision and the fencing token for its owner."""

    status: ClaimStatus
    token: int | None = None

    def __post_init__(self) -> None:
        if self.status is ClaimStatus.ACQUIRED:
            if self.token is None or self.token < 1:
                raise ValueError("an acquired claim requires a positive token")
        elif self.token is not None:
            raise ValueError("only an acquired claim may carry a token")


def dsn_from_env(env: dict[str, str] | None = None) -> str | None:
    """Build a DSN, or `None` when the database is not configured."""

    values = os.environ if env is None else env
    required = ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    if not all(values.get(key) for key in required):
        return None
    return make_conninfo(
        host=values["POSTGRES_HOST"],
        port=values.get("POSTGRES_PORT", "5432"),
        dbname=values["POSTGRES_DB"],
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
    )


def connect(dsn: str):
    """Open a connection with this worker's timeouts.

    Shared with the registry reader so both halves fail the same way. The
    timeouts matter more here than in a web request: this process holds a lease
    while it works, and a query that blocks indefinitely holds it past the
    lease, at which point another worker takes over and both are running.
    """
    return psycopg.connect(
        dsn,
        connect_timeout=5,
        options="-c statement_timeout=15000 -c lock_timeout=5000",
    )


@dataclass
class ClaimStore:
    """Serializes work per `event_id` across every worker instance."""

    dsn: str
    lease_seconds: int = 900

    def __post_init__(self) -> None:
        if not 60 <= self.lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be between 60 and 86400")

    def _connect(self):
        return connect(self.dsn)

    def ready(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT to_regclass('repo_analysis.event_claim')"
            ).fetchone()
            return row is not None and row[0] is not None

    def claim(self, event_id: str, analysis_id: str) -> Claim:
        """Return an explicit lease decision, with a token for its owner."""
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO repo_analysis.event_claim
                    (event_id, analysis_id, state)
                VALUES (%s, %s, 'CLONING')
                ON CONFLICT (event_id) DO NOTHING
                RETURNING attempt
                """,
                (event_id, analysis_id),
            ).fetchone()
            if row is not None:
                return Claim(ClaimStatus.ACQUIRED, int(row[0]))

            current = conn.execute(
                """
                SELECT state,
                       attempt,
                       claimed_at < clock_timestamp() - make_interval(secs => %s)
                FROM repo_analysis.event_claim
                WHERE event_id = %s
                FOR UPDATE
                """,
                (self.lease_seconds, event_id),
            ).fetchone()
            if current is None:
                raise RuntimeError("claim row disappeared while deciding ownership")

            state, attempt, expired = current
            if state != "CLONING":
                return Claim(ClaimStatus.TERMINAL)
            if not expired:
                return Claim(ClaimStatus.BUSY)

            takeover = conn.execute(
                """
                UPDATE repo_analysis.event_claim
                SET claimed_at = clock_timestamp(),
                    updated_at = clock_timestamp(),
                    attempt = attempt + 1,
                    error_code = NULL
                WHERE event_id = %s AND state = 'CLONING' AND attempt = %s
                RETURNING attempt
                """,
                (event_id, attempt),
            ).fetchone()
            if takeover is None:  # Defensive: the row is locked in this transaction.
                raise RuntimeError(
                    "claim ownership changed while taking over an expired lease"
                )
            return Claim(ClaimStatus.ACQUIRED, int(takeover[0]))

    def release(self, event_id: str, token: int) -> bool:
        """Expire this owner's lease so redelivery can retry immediately."""
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE repo_analysis.event_claim
                SET claimed_at = '-infinity'::timestamptz,
                    updated_at = clock_timestamp()
                WHERE event_id = %s AND state = 'CLONING' AND attempt = %s
                RETURNING event_id
                """,
                (event_id, token),
            ).fetchone()
            return row is not None

    def finish(
        self,
        event_id: str,
        token: int,
        state: str,
        error_code: str | None = None,
    ) -> bool:
        """Record a terminal outcome. Later deliveries of this event are skipped."""
        if state not in {"CLONED", "FAILED"}:
            raise ValueError("state must be CLONED or FAILED")
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE repo_analysis.event_claim
                SET state = %s, error_code = %s, updated_at = clock_timestamp()
                WHERE event_id = %s AND state = 'CLONING' AND attempt = %s
                RETURNING event_id
                """,
                (state, error_code, event_id, token),
            ).fetchone()
            return row is not None
