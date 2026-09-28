"""New-hour watching for GH Archive (S15P21E102-144).

The ticket's completion criterion is that an hour must not arrive twice — once
through `-105`'s bootstrap and once through the watcher. Most of what is
verified here is that boundary, plus the reclassification of a 404 on a
just-ended hour from "failure" to "not yet".

No network: the downloader is a recording double.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collector.gharchive.historical import (
    HISTORICAL_CUTOFF,
    HISTORICAL_START,
    DownloadSummary,
    RangeValidationError,
    format_utc_hour,
)
from collector.gharchive.watch import (
    DEFAULT_PUBLICATION_LAG,
    UNPUBLISHED_GRACE,
    WATCH_HORIZON,
    WATCH_START,
    GhArchiveWatcher,
    latest_publishable_hour,
    watch_range,
)

# 2026-09-09 02:05Z. The hour 01:00Z has ended and is past the lag; 02:00Z is
# still in progress.
NOW = datetime(2026, 9, 9, 2, 5, tzinfo=UTC)


class FakeDownloader:
    """Records the bounds it was asked for and returns a canned summary."""

    def __init__(self, summary: DownloadSummary | None = None) -> None:
        self.calls: list[dict[str, datetime]] = []
        self.summary = summary or DownloadSummary(
            expected=0,
            downloaded=(),
            reused=(),
            failed={},
            missing=(),
            downloaded_bytes=0,
            validated_uncompressed_bytes=0,
        )

    def download(self, start, end, *, historical_start, historical_cutoff):
        self.calls.append(
            {
                "start": start,
                "end": end,
                "historical_start": historical_start,
                "historical_cutoff": historical_cutoff,
            }
        )
        return self.summary


def _summary(**overrides) -> DownloadSummary:
    values = {
        "expected": 1,
        "downloaded": (),
        "reused": (),
        "failed": {},
        "missing": (),
        "downloaded_bytes": 0,
        "validated_uncompressed_bytes": 0,
    }
    values.update(overrides)
    return DownloadSummary(**values)


def _watcher(tmp_path: Path, downloader: FakeDownloader) -> GhArchiveWatcher:
    return GhArchiveWatcher(tmp_path, downloader=downloader)


# --- the boundary: no hour may arrive twice ---------------------------------


def test_watch_start_is_the_historical_cutoff():
    """One constant defines both sides, so they cannot drift apart.

    Re-cutting the bootstrap window has to move the watch window with it, or
    the hours between them are collected twice — or not at all.
    """

    assert WATCH_START == HISTORICAL_CUTOFF
    assert WATCH_START > HISTORICAL_START


def test_poll_never_asks_for_an_hour_before_the_cutoff(tmp_path: Path):
    downloader = FakeDownloader()
    _watcher(tmp_path, downloader).poll(NOW)

    call = downloader.calls[0]
    assert call["start"] == WATCH_START
    assert call["historical_start"] == WATCH_START


def test_watch_range_starts_at_the_cutoff_not_at_the_cursor():
    """Resume is the checkpoint's job, not the range's.

    Asking from the cutoff every time and letting the checkpoint skip what it
    already has means a hour that failed once is retried, instead of being
    stepped over by a cursor that moved past it.
    """

    start, end = watch_range(NOW)
    assert start == WATCH_START
    # 02:05Z minus the 30-minute lag floors to 01:00Z, so the newest claimed
    # hour is 00:00Z and the half-open end is 01:00Z.
    assert end == datetime(2026, 9, 9, 1, tzinfo=UTC)


def test_the_watch_checkpoint_is_a_separate_file(tmp_path: Path):
    watcher = GhArchiveWatcher(tmp_path)

    assert watcher.checkpoint_path.name == "watch-checkpoint.json"
    assert watcher.checkpoint_path != tmp_path / "checkpoint.json"


# --- which hour is publishable ----------------------------------------------


def test_latest_publishable_hour_excludes_the_hour_in_progress():
    """Measured 2026-09-09: the hour in progress returns 404, always."""

    latest = latest_publishable_hour(NOW, lag=timedelta(0))
    assert latest == datetime(2026, 9, 9, 1, tzinfo=UTC)


def test_the_lag_holds_back_a_just_ended_hour():
    """At 02:05Z with a 30-minute lag, 01:00Z is not claimed yet.

    GH Archive served a just-ended hour 17 minutes late in measurement, so
    the default doubles that rather than racing publication.
    """

    latest = latest_publishable_hour(NOW, lag=DEFAULT_PUBLICATION_LAG)
    assert latest == datetime(2026, 9, 9, 0, tzinfo=UTC)


def test_a_poll_before_anything_new_exists_is_skipped(tmp_path: Path):
    """Two polls in one hour is normal operation, not an error."""

    downloader = FakeDownloader()
    early = WATCH_START  # nothing has been published past the cutoff yet
    result = _watcher(tmp_path, downloader).poll(early)

    assert result.skipped
    assert result.ok
    assert downloader.calls == []


def test_naive_now_is_refused():
    with pytest.raises(RangeValidationError, match="timezone"):
        latest_publishable_hour(datetime(2026, 9, 9, 2, 5))  # noqa: DTZ001


def test_reaching_the_horizon_raises_instead_of_collecting_nothing():
    """A silent expiry would look like "no new hours" forever."""

    beyond = WATCH_HORIZON + timedelta(days=1)
    with pytest.raises(RangeValidationError, match="watch horizon reached"):
        watch_range(beyond)


# --- a 404 on a new hour is not a failure -----------------------------------


def test_a_recent_404_is_not_yet_published(tmp_path: Path):
    """`HistoricalDownloader` calls 404 a failure; here it means "not yet".

    Reporting it as an error would make every poll that runs near the top of
    the hour look broken.
    """

    hour = format_utc_hour(datetime(2026, 9, 9, 1, tzinfo=UTC))
    downloader = FakeDownloader(
        _summary(failed={hour: f"HTTP 404 for https://data.gharchive.org/{hour}"})
    )

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.not_yet_published == (hour,)
    assert result.gaps == ()
    assert result.failed == ()
    assert result.ok


def test_an_old_404_is_a_gap(tmp_path: Path):
    """Past the grace the archive should exist, so its absence is real."""

    hour = format_utc_hour(NOW - UNPUBLISHED_GRACE - timedelta(hours=6))
    downloader = FakeDownloader(_summary(failed={hour: "HTTP 404 for x"}))

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.gaps == (hour,)
    assert result.not_yet_published == ()
    assert not result.ok


def test_a_non_404_failure_stays_a_failure(tmp_path: Path):
    """A 500 or a corrupt gzip is not excused by being recent."""

    hour = format_utc_hour(datetime(2026, 9, 9, 1, tzinfo=UTC))
    downloader = FakeDownloader(
        _summary(failed={hour: "gzip CRC mismatch after 3 attempts"})
    )

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.failed and result.failed[0]["hour"] == hour
    assert result.not_yet_published == ()
    assert not result.ok


def test_hours_the_run_never_reached_are_gaps(tmp_path: Path):
    """`missing` means nothing even tried, which the grace does not cover."""

    hour = format_utc_hour(datetime(2026, 9, 2, 5, tzinfo=UTC))
    downloader = FakeDownloader(_summary(missing=(hour,)))

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.gaps == (hour,)
    assert not result.ok


def test_downloaded_hours_are_the_seam_for_the_kafka_step(tmp_path: Path):
    """`-144`'s publish half reads this; the topic is blocked on `-108`."""

    hours = (
        format_utc_hour(datetime(2026, 9, 8, 22, tzinfo=UTC)),
        format_utc_hour(datetime(2026, 9, 8, 23, tzinfo=UTC)),
    )
    downloader = FakeDownloader(
        _summary(expected=2, downloaded=hours, downloaded_bytes=29_111_464)
    )

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.downloaded == hours
    assert result.downloaded_bytes == 29_111_464
    assert result.ok
    assert "S15P21E102-108" in str(result.as_dict()["kafka"])


def test_a_poll_with_nothing_new_is_ok(tmp_path: Path):
    hours = (format_utc_hour(datetime(2026, 9, 8, 23, tzinfo=UTC)),)
    downloader = FakeDownloader(_summary(reused=hours))

    result = _watcher(tmp_path, downloader).poll(NOW)

    assert result.ok
    assert result.downloaded == ()
    assert result.as_dict()["reused"] == 1
