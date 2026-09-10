"""Claim-store lease and fencing checks against an explicitly selected test DB."""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from analysis.claim import ClaimStatus, ClaimStore

TEST_DSN = os.getenv("ANALYSIS_TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="ANALYSIS_TEST_POSTGRES_DSN is not set to an isolated PostgreSQL database",
)


def test_active_lease_takeover_and_stale_owner_are_fenced():
    event_id = f"ev_{uuid4().hex}"
    analysis_id = f"an_{uuid4().hex}"
    first = ClaimStore(TEST_DSN, lease_seconds=60)
    second = ClaimStore(TEST_DSN, lease_seconds=60)

    try:
        original = first.claim(event_id, analysis_id)
        assert original.status is ClaimStatus.ACQUIRED
        assert original.token is not None

        busy = second.claim(event_id, analysis_id)
        assert busy.status is ClaimStatus.BUSY
        assert busy.token is None

        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                """
                UPDATE repo_analysis.event_claim
                SET claimed_at = clock_timestamp() - interval '61 seconds'
                WHERE event_id = %s
                """,
                (event_id,),
            )

        takeover = second.claim(event_id, analysis_id)
        assert takeover.status is ClaimStatus.ACQUIRED
        assert takeover.token is not None
        assert takeover.token > original.token

        assert first.release(event_id, original.token) is False
        assert first.finish(event_id, original.token, "CLONED") is False
        assert second.finish(event_id, takeover.token, "CLONED") is True

        terminal = first.claim(event_id, analysis_id)
        assert terminal.status is ClaimStatus.TERMINAL
        assert terminal.token is None
    finally:
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                "DELETE FROM repo_analysis.event_claim WHERE event_id = %s",
                (event_id,),
            )


def test_release_preserves_the_fencing_generation_for_the_retry():
    event_id = f"ev_{uuid4().hex}"
    analysis_id = f"an_{uuid4().hex}"
    store = ClaimStore(TEST_DSN, lease_seconds=60)

    try:
        original = store.claim(event_id, analysis_id)
        assert original.token is not None
        assert store.release(event_id, original.token) is True

        retry = store.claim(event_id, analysis_id)
        assert retry.status is ClaimStatus.ACQUIRED
        assert retry.token is not None
        assert retry.token > original.token
        assert store.finish(event_id, original.token, "FAILED", "STALE") is False
    finally:
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                "DELETE FROM repo_analysis.event_claim WHERE event_id = %s",
                (event_id,),
            )
