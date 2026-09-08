"""Keep a live compute lease renewed while completion remains transaction-fenced."""

import math
from threading import Event, Thread
from typing import Self

import psycopg

from worker.store import ComputeStore, Ticket


class LeaseHeartbeat:
    """Renew in the background; stop promptly on completion or renewal loss.

    ComputeStore.complete is the authoritative ownership check. In particular,
    __exit__ must not raise merely because a renewal saw state COMPLETED just
    after the body successfully committed. A lost/expired/replaced lease is
    rejected by complete itself. A process crash stops heartbeats and the normal
    expiry/claim path permits recovery.
    """

    def __init__(
        self,
        store: ComputeStore,
        ticket: Ticket,
        *,
        interval_seconds: float | None = None,
    ):
        if ticket.token is None or ticket.status != "RUNNING":
            raise ValueError("heartbeat requires an owned RUNNING attempt")
        interval = (
            store.lease_seconds / 3 if interval_seconds is None else interval_seconds
        )
        if (
            not math.isfinite(interval)
            or interval <= 0
            or interval > store.lease_seconds / 2
        ):
            raise ValueError(
                "heartbeat interval must be positive and at most half the lease"
            )
        self._store = store
        self._ticket = ticket
        self._interval = interval
        self._stop = Event()
        self._lost = Event()
        self._thread: Thread | None = None
        self.renewal_error: Exception | None = None

    @property
    def lease_lost(self) -> bool:
        """Diagnostic renewal result; completion can already have committed."""
        return self._lost.is_set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._store.renew(self._ticket):
                    self._lost.set()
                    return
            except (psycopg.Error, OSError, RuntimeError) as exc:
                self.renewal_error = exc
                self._lost.set()
                return

    def __enter__(self) -> Self:
        if self._thread is not None:
            raise RuntimeError("heartbeat context cannot be entered twice")
        self._thread = Thread(
            target=self._run,
            name=f"c-lease-{self._ticket.event_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            # A DB call has bounded connection/statement timeouts, but must not
            # hold up HTTP completion. The daemon exits as that call returns.
            self._thread.join(timeout=0.1)
        return False
