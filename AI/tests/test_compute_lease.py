"""Real local PostgreSQL lease fencing plus bounded heartbeat lifecycle checks."""

import os
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest

from worker.lease import LeaseHeartbeat
from worker.store import Artifact, ComputeStore, LeaseLost, Ticket, apply_migration


@pytest.fixture
def lease_store():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires explicitly selected isolated PostgreSQL test database")
    apply_migration(dsn)
    return ComputeStore(dsn, lease_seconds=1)


def claim(store, *, event_id=None, occurred_at=None):
    return store.claim(
        event_id=event_id or str(uuid4()),
        kind="ANALYSIS",
        owner="lease-test-user",
        occurred_at=occurred_at or datetime.now(UTC),
        request={"test": "lease-heartbeat"},
    )


def artifact():
    return Artifact(
        "RECOMMENDATION", "lease-test-user", {"lease_probe": str(uuid4())}, str(uuid4())
    )


def test_heartbeat_allows_compute_longer_than_original_lease(lease_store):
    ticket = claim(lease_store)
    with LeaseHeartbeat(lease_store, ticket, interval_seconds=0.1):
        Event().wait(1.8)
        references = lease_store.complete(ticket, [artifact()])
    replay = claim(
        lease_store, event_id=ticket.event_id, occurred_at=ticket.occurred_at
    )
    assert replay.status == "COMPLETED"
    assert replay.results == references
    assert replay.attempt == 1


def test_expired_lease_cannot_be_resurrected_and_can_be_reclaimed(lease_store):
    ticket = claim(lease_store)
    Event().wait(1.1)
    assert not lease_store.renew(ticket)
    with pytest.raises(LeaseLost):
        lease_store.complete(ticket, [artifact()])
    replacement = claim(
        lease_store, event_id=ticket.event_id, occurred_at=ticket.occurred_at
    )
    assert replacement.token != ticket.token
    assert replacement.attempt == 2
    assert lease_store.renew(replacement)
    assert not lease_store.renew(ticket)
    assert lease_store.complete(replacement, [artifact()])


def test_replaced_or_completed_owner_cannot_renew(lease_store):
    ticket = claim(lease_store)
    lease_store.fail(ticket, "TEST_FAILURE")
    replacement = claim(
        lease_store, event_id=ticket.event_id, occurred_at=ticket.occurred_at
    )
    assert not lease_store.renew(ticket)
    with pytest.raises(LeaseLost):
        lease_store.complete(ticket, [artifact()])
    assert lease_store.complete(replacement, [artifact()])
    assert not lease_store.renew(replacement)


def fake_ticket():
    return Ticket(
        str(uuid4()),
        "ANALYSIS",
        "lease-test-user",
        datetime.now(UTC),
        "RUNNING",
        str(uuid4()),
        1,
        [],
    )


def test_context_does_not_convert_completed_renewal_race_into_failure():
    called = Event()

    class CompletedStore:
        lease_seconds = 1

        def renew(self, ticket):
            called.set()
            return False  # complete() already committed when the next renewal ran.

    with LeaseHeartbeat(CompletedStore(), fake_ticket(), interval_seconds=0.01):
        assert called.wait(1)


def test_renewal_failure_stops_heartbeat_and_body_exception_is_preserved():
    called = Event()

    class FailedStore:
        lease_seconds = 1

        def renew(self, ticket):
            called.set()
            raise RuntimeError("test renewal unavailable")

    heartbeat = LeaseHeartbeat(FailedStore(), fake_ticket(), interval_seconds=0.01)
    with pytest.raises(ValueError, match="original compute failure"), heartbeat:
        assert called.wait(1)
        raise ValueError("original compute failure")
    assert heartbeat.lease_lost
    assert isinstance(heartbeat.renewal_error, RuntimeError)


def test_cleanup_does_not_block_on_an_unresponsive_database_renewal():
    entered, release, finished = Event(), Event(), Event()

    class BlockedStore:
        lease_seconds = 1

        def renew(self, ticket):
            entered.set()
            release.wait(2)
            finished.set()
            return True

    try:
        with LeaseHeartbeat(BlockedStore(), fake_ticket(), interval_seconds=0.01):
            assert entered.wait(1)
            started = monotonic()
        assert monotonic() - started < 0.3
    finally:
        release.set()
        assert finished.wait(1)


def test_heartbeat_rejects_interval_that_cannot_protect_lease():
    class Store:
        lease_seconds = 1

    for interval in (0, -1, float("nan"), float("inf"), 1):
        with pytest.raises(ValueError):
            LeaseHeartbeat(Store(), fake_ticket(), interval_seconds=interval)


def test_renewal_requires_original_owner_kind_and_token(lease_store):
    ticket = claim(lease_store)
    assert not lease_store.renew(replace(ticket, owner="another-user"))
    assert not lease_store.renew(replace(ticket, kind="TREND"))
    assert not lease_store.renew(replace(ticket, token=str(uuid4())))
    assert not lease_store.renew(replace(ticket, token=None))
    assert lease_store.renew(ticket)
