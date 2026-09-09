"""Watch GH Archive for newly published hours (S15P21E102-144).

`-105` downloaded a bounded historical range and stops at
`HISTORICAL_CUTOFF`; `validate_requested_range` refuses to look past it, so
that collector physically cannot drift into the present. This module owns the
other side of that line: the hours that appear after it, one per hour, forever.

### The boundary is the whole point

The ticket's completion criterion is that the same hour must not arrive twice —
once through `-105`'s HDFS bootstrap and once through this watcher. Two things
enforce that here, and neither is a comment:

- `WATCH_START` **is** `HISTORICAL_CUTOFF`. The two ranges are defined from one
  constant, so they cannot drift apart when the bootstrap window is re-cut.
- The checkpoint binds itself to its `(historical_start, historical_cutoff)`
  pair and refuses to load under a different one (`CheckpointStore._load`).
  A watch checkpoint therefore cannot be read as a bootstrap checkpoint even
  if someone points them at the same path.

### An unpublished hour is not a failure

GH Archive publishes an hour shortly after it ends — measured 2026-09-09, the
hour ending 01:00Z was already served 17 minutes later, while the hour in
progress returned 404. `HistoricalDownloader` classifies 404 as a
non-retryable failure, which is right for a historical range where every hour
must exist, and wrong here: for the newest hours 404 means "not yet", and the
next poll gets it.

So this module re-classifies. A 404 inside `UNPUBLISHED_GRACE` of now is
`not_yet_published` and leaves the cursor alone; an older one is a `gap` worth
someone's attention.

### What this module does not do

**It does not publish to Kafka.** `-144` also calls for wrapping each hour in
the `-103` envelope and sending it to `github.events`, and that is blocked:
the topic does not exist, and its partition count is still open in `-102`
(checklist item ⑤, `github.events` proposed at 6). Partitions cannot be
reduced, and this topic is keyed by repo id, so fixing the number early would
cost more than waiting. Detection, download and the cursor are independent of
that decision, so they land first. `WatchSummary.downloaded` is the seam the
publish step will read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collector.gharchive.historical import (
    DEFAULT_BASE_URL,
    DEFAULT_OUTPUT_ROOT,
    HISTORICAL_CUTOFF,
    SOURCE,
    DownloadSummary,
    HistoricalDownloader,
    RangeValidationError,
    format_utc_hour,
    parse_utc_hour,
)

__all__ = [
    "DEFAULT_PUBLICATION_LAG",
    "UNPUBLISHED_GRACE",
    "WATCH_HORIZON",
    "WATCH_START",
    "GhArchiveWatcher",
    "WatchSummary",
    "latest_publishable_hour",
    "watch_range",
]

# The line `-105` stops at. Defined from its constant rather than repeated, so
# re-cutting the bootstrap window moves both sides together.
WATCH_START = HISTORICAL_CUTOFF

# `CheckpointStore` pins itself to a fixed `(start, cutoff)` pair, and a watch
# window's upper edge moves every hour. A fixed horizon keeps the checkpoint
# loadable across polls; `watch_range` raises when it is reached rather than
# quietly collecting nothing, so the expiry cannot pass unnoticed.
WATCH_HORIZON = datetime(2027, 1, 1, tzinfo=UTC)

# How long after an hour ends before its file is expected. Measured 2026-09-09:
# the hour ending 01:00Z was served at 01:17Z, and every hour back to 12 hours
# earlier was present. 30 minutes doubles the observed lag, which is why an
# hourly poll (at :30, say) reaches each hour with room to spare.
DEFAULT_PUBLICATION_LAG = timedelta(minutes=30)

# How long a 404 stays "not yet" before it is reported as a gap. Generous
# against the measured 17 minutes on purpose: calling a slow hour a gap sends
# someone looking for a problem that resolves itself, and the next poll picks
# it up either way.
UNPUBLISHED_GRACE = timedelta(hours=3)

_NOT_FOUND = re.compile(r"\bHTTP 404\b")


def latest_publishable_hour(
    now: datetime,
    *,
    lag: timedelta = DEFAULT_PUBLICATION_LAG,
) -> datetime:
    """The newest hour whose archive should already be served.

    The hour in progress never exists, so this floors to the hour and steps
    back one; `lag` then holds it back further until publication is likely.
    """

    if now.tzinfo is None:
        raise RangeValidationError("now must include a timezone")
    if lag < timedelta(0):
        raise RangeValidationError("lag cannot be negative")

    anchor = now.astimezone(UTC) - lag
    return anchor.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


def watch_range(
    now: datetime,
    *,
    lag: timedelta = DEFAULT_PUBLICATION_LAG,
    watch_start: datetime = WATCH_START,
    horizon: datetime = WATCH_HORIZON,
) -> tuple[datetime, datetime] | None:
    """The half-open range this poll should ask for, or None when it is early.

    Returns None rather than an empty range when nothing new can exist yet —
    a poll that runs twice within an hour is normal, not an error.
    """

    latest = latest_publishable_hour(now, lag=lag)
    end = latest + timedelta(hours=1)

    if end <= watch_start:
        return None
    if end > horizon:
        raise RangeValidationError(
            "watch horizon reached: extend WATCH_HORIZON past "
            f"{format_utc_hour(end)} (currently {format_utc_hour(horizon)})"
        )
    return watch_start, end


@dataclass(frozen=True)
class WatchSummary:
    """What one poll found, with unpublished hours kept apart from gaps."""

    range_start: str | None
    range_end: str | None
    downloaded: tuple[str, ...] = ()
    reused: tuple[str, ...] = ()
    # 404 within `UNPUBLISHED_GRACE`. Expected; the next poll collects them.
    not_yet_published: tuple[str, ...] = ()
    # 404 older than the grace. The archive should exist and does not.
    gaps: tuple[str, ...] = ()
    # Anything else — transport, validation, a non-404 status.
    failed: tuple[dict[str, str], ...] = ()
    downloaded_bytes: int = 0

    @property
    def skipped(self) -> bool:
        return self.range_start is None

    @property
    def ok(self) -> bool:
        """Whether this poll needs anyone's attention.

        `not_yet_published` is deliberately not a problem, and `reused` is the
        normal state of a poll that had nothing new to fetch.
        """

        return not self.gaps and not self.failed

    def as_dict(self) -> dict[str, object]:
        return {
            "source": SOURCE,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "downloaded": list(self.downloaded),
            "reused": len(self.reused),
            "not_yet_published": list(self.not_yet_published),
            "gaps": list(self.gaps),
            "failed": [dict(entry) for entry in self.failed],
            "downloaded_bytes": self.downloaded_bytes,
            "kafka": "pending S15P21E102-108 (github.events topic)",
        }


class GhArchiveWatcher:
    """Collect hours published after `WATCH_START`, one poll at a time.

    The download, validation and resume machinery is `HistoricalDownloader`'s
    and is reused rather than reimplemented — only the bounds and the
    checkpoint path differ, which is what keeps the two cursors apart.
    """

    def __init__(
        self,
        output_root: Path = DEFAULT_OUTPUT_ROOT,
        *,
        checkpoint_path: Path | None = None,
        downloader: HistoricalDownloader | None = None,
        base_url: str = DEFAULT_BASE_URL,
        lag: timedelta = DEFAULT_PUBLICATION_LAG,
        grace: timedelta = UNPUBLISHED_GRACE,
        watch_start: datetime = WATCH_START,
        horizon: datetime = WATCH_HORIZON,
    ) -> None:
        self.output_root = output_root.resolve()
        # A distinct filename, not just a distinct directory. The bootstrap
        # checkpoint would refuse to load under these bounds anyway, but two
        # names make the separation visible on disk.
        self.checkpoint_path = (
            checkpoint_path.resolve()
            if checkpoint_path is not None
            else self.output_root / "watch-checkpoint.json"
        )
        self.downloader = downloader or HistoricalDownloader(
            self.output_root,
            checkpoint_path=self.checkpoint_path,
            base_url=base_url,
        )
        self.lag = lag
        self.grace = grace
        self.watch_start = watch_start
        self.horizon = horizon

    def poll(self, now: datetime | None = None) -> WatchSummary:
        """Fetch every hour published since the cursor, and classify the rest."""

        moment = (now or datetime.now(UTC)).astimezone(UTC)
        window = watch_range(
            moment,
            lag=self.lag,
            watch_start=self.watch_start,
            horizon=self.horizon,
        )
        if window is None:
            return WatchSummary(range_start=None, range_end=None)

        start, end = window
        summary = self.downloader.download(
            start,
            end,
            historical_start=self.watch_start,
            historical_cutoff=self.horizon,
        )
        return self._classify(summary, start=start, end=end, now=moment)

    def _classify(
        self,
        summary: DownloadSummary,
        *,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> WatchSummary:
        """Split `failed` into "not published yet" and everything else.

        `HistoricalDownloader` is right to call a 404 a failure — in a
        historical range every hour must exist. Here the newest hours are
        allowed not to yet, and treating that as an error would make every
        poll look broken.
        """

        not_yet: list[str] = []
        gaps: list[str] = []
        failed: list[dict[str, str]] = []

        for hour_key, error in summary.failed.items():
            if not _NOT_FOUND.search(error):
                failed.append({"hour": hour_key, "error": error[:400]})
                continue
            if self._within_grace(hour_key, now):
                not_yet.append(hour_key)
            else:
                gaps.append(hour_key)

        # `missing` holds hours the loop never reached — a range cut short.
        # They are gaps by definition: nothing even tried to fetch them.
        gaps.extend(hour for hour in summary.missing if hour not in gaps)

        return WatchSummary(
            range_start=format_utc_hour(start),
            range_end=format_utc_hour(end),
            downloaded=summary.downloaded,
            reused=summary.reused,
            not_yet_published=tuple(sorted(not_yet)),
            gaps=tuple(sorted(gaps)),
            failed=tuple(failed),
            downloaded_bytes=summary.downloaded_bytes,
        )

    def _within_grace(self, hour_key: str, now: datetime) -> bool:
        try:
            hour = parse_utc_hour(hour_key)
        except RangeValidationError:
            # An unparseable key cannot be aged, so it is not excused.
            return False
        return now - hour <= self.grace + timedelta(hours=1)
