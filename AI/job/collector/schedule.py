"""Declared collection schedule, run history and failure alerting.

S15P21E102-107. The reason this exists is in the ticket's first line: a
posting that is never collected cannot be collected later, so a failed run
has to be noticed the same day, not at the end of the sprint.

Three things follow from that.

**The schedule is declared, not coded.** `schedule.toml` names the runs and
the times. The OS scheduler (cron, Windows Task Scheduler) executes them, and
`render_os_schedule` prints those lines from the same file, so there is one
source of truth for "when" instead of a config that documents a crontab
someone edited by hand.

**A run is a subprocess.** Each site already has a CLI, so the config gives a
module and its arguments. A collector that crashes cannot take the scheduler
down with it, and 사람인 needs no change here on the day it lands.

**History is append-only.** A gap is detected by comparing runs, so the record
of what ran has to survive the process that wrote it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import tomllib

from job.collector.outcome import empty_run_blockers, is_valid_empty_run

__all__ = [
    "DEFAULT_MAX_INTERVAL_HOURS",
    "RunOutcome",
    "RunRecord",
    "ScheduleConfig",
    "ScheduledRun",
    "append_history",
    "count_blocked_runs",
    "detect_gap",
    "execute_run",
    "load_schedule",
    "notify",
    "read_history",
    "render_os_schedule",
]

# Twice a day is every 12 hours; 14 gives a late run room to finish before the
# next one is called missing. A wider window would let a whole missed cycle
# pass unreported, which is the one failure this ticket exists to catch.
DEFAULT_MAX_INTERVAL_HOURS = 14


@dataclass(frozen=True)
class ScheduledRun:
    """One declared collection run."""

    name: str
    site: str
    # Executed as `python -m <module> <args...>`. The site's own CLI stays the
    # contract; the scheduler does not reach into collector internals.
    module: str
    args: tuple[str, ...]
    # "HH:MM" local time. Informational for the scheduler itself — the OS
    # scheduler is what fires — and the source for `render_os_schedule`.
    at: tuple[str, ...]
    enabled: bool = True


@dataclass(frozen=True)
class ScheduleConfig:
    runs: tuple[ScheduledRun, ...]
    history_path: Path
    # Env var holding the incoming-webhook URL. The URL itself is a secret and
    # must not appear in this file (S15P21E102-106: no secrets in the repo).
    webhook_env: str | None = None
    max_interval_hours: int = DEFAULT_MAX_INTERVAL_HOURS

    def run(self, name: str) -> ScheduledRun:
        for candidate in self.runs:
            if candidate.name == name:
                return candidate
        known = ", ".join(candidate.name for candidate in self.runs)
        raise KeyError(f"unknown run {name!r}; declared runs: {known}")


class RunOutcome:
    # New explicit operational states.
    SUCCESS_WITH_DATA = "SUCCESS_WITH_DATA"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"

    # History written before S15P21E102-273 is append-only. Keep these values
    # readable; do not rewrite old lines on disk.
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    FAILED = "FAILED"

    SUCCESS_STATUSES = frozenset({SUCCESS, SUCCESS_WITH_DATA, SUCCESS_EMPTY})

    @classmethod
    def is_success(cls, status: str) -> bool:
        return status in cls.SUCCESS_STATUSES


@dataclass(frozen=True)
class RunRecord:
    """One line of the run history — the ticket's 사이트·시각·건수·상태·오류."""

    run_name: str
    site: str
    started_at: str
    finished_at: str
    status: str
    records: int
    exit_code: int
    error: str | None = None
    # The collector's own reason for ending early — "blocked: ...", a failed
    # page fetch. Carried here, not left in the manifest, because
    # S15P21E102-101 closes on "7일 연속 수집 중 차단 0회" and a run that was
    # blocked *after* collecting records is a SUCCESS with no other trace.
    stopped_reason: str | None = None
    pipeline_run_id: str | None = None
    manifest_path: str | None = None
    # Preserve the manifest diagnostic/filter counters in append-only history.
    # Older records deserialize with the empty default.
    filter_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def load_schedule(path: Path) -> ScheduleConfig:
    """Read the declared schedule.

    TOML through `tomllib` keeps this dependency-free; the collector packages
    deliberately carry no third-party parsing libraries.
    """

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    runs = tuple(
        ScheduledRun(
            name=str(entry["name"]),
            site=str(entry["site"]),
            module=str(entry["module"]),
            args=tuple(str(arg) for arg in entry.get("args", ())),
            at=tuple(str(when) for when in entry.get("at", ())),
            enabled=bool(entry.get("enabled", True)),
        )
        for entry in raw.get("run", ())
    )
    if not runs:
        raise ValueError(f"{path} declares no runs")

    history = raw.get("history_path", "data/collection-history.jsonl")
    return ScheduleConfig(
        runs=runs,
        history_path=(path.parent / str(history)).resolve(),
        webhook_env=raw.get("webhook_env"),
        max_interval_hours=int(
            raw.get("max_interval_hours", DEFAULT_MAX_INTERVAL_HOURS)
        ),
    )


def execute_run(
    run: ScheduledRun,
    *,
    now: datetime | None = None,
    python: str | None = None,
    cwd: Path | None = None,
    timeout_seconds: float = 3600.0,
) -> RunRecord:
    """Run one collection and describe what happened.

    A non-zero exit, a crash and a timeout are all recorded rather than raised:
    the caller has to write history and alert for every one of them, and an
    exception here would skip both.

    A zero-record child that exits cleanly is SUCCESS_EMPTY only when its
    manifest proves that request/parser processing completed without quality
    or source-fatal blockers.
    """

    started = now or datetime.now(UTC)
    command = [python or sys.executable, "-m", run.module, *run.args]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunRecord(
            run_name=run.name,
            site=run.site,
            started_at=started.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            status=RunOutcome.FAILED,
            records=0,
            exit_code=-1,
            error=f"timed out after {timeout_seconds:.0f}s",
        )
    except OSError as error:
        return RunRecord(
            run_name=run.name,
            site=run.site,
            started_at=started.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            status=RunOutcome.FAILED,
            records=0,
            exit_code=-1,
            error=f"could not start: {error}",
        )

    manifest_path = _tagged_value(completed.stdout, "manifest")
    counts = _read_manifest_counts(manifest_path, cwd, source_site=run.site)

    if completed.returncode != 0:
        # A collector may deliberately stop after retaining records because a
        # later page was blocked. Preserve that existing partial-data outcome.
        # Other non-zero exits, including Raw/analysis_input upload failures,
        # are actual failures even when local records exist.
        if counts["records"] > 0 and counts["stopped_reason"]:
            status = RunOutcome.SUCCESS_WITH_DATA
        else:
            status = RunOutcome.FAILED
    elif counts["records"] == 0 and counts["empty_valid"]:
        status = RunOutcome.SUCCESS_EMPTY
    elif counts["records"] == 0:
        status = RunOutcome.FAILED
    else:
        status = RunOutcome.SUCCESS_WITH_DATA

    return RunRecord(
        run_name=run.name,
        site=run.site,
        started_at=started.isoformat(),
        finished_at=datetime.now(UTC).isoformat(),
        status=status,
        records=counts["records"],
        exit_code=completed.returncode,
        error=_error_summary(
            completed,
            status,
            manifest_error=counts["manifest_error"],
        ),
        stopped_reason=counts["stopped_reason"],
        pipeline_run_id=counts["pipeline_run_id"],
        manifest_path=manifest_path,
        filter_counts=counts["filter_counts"],
    )


def _tagged_value(stdout: str, key: str) -> str | None:
    """Read a `key=value` line the collector CLIs print on success."""

    for line in reversed(stdout.splitlines()):
        name, separator, value = line.partition("=")
        if separator and name.strip() == key and value.strip():
            return value.strip()
    return None


def _read_manifest_counts(
    manifest_path: str | None,
    cwd: Path | None,
    *,
    source_site: str | None = None,
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "records": 0,
        "pipeline_run_id": None,
        "stopped_reason": None,
        "filter_counts": {},
        "empty_valid": False,
        "manifest_error": None,
    }
    if not manifest_path:
        empty["manifest_error"] = "collector did not report a manifest"
        return empty
    path = Path(manifest_path)
    if not path.is_absolute() and cwd is not None:
        path = cwd / path
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        empty["manifest_error"] = f"manifest unreadable: {path}"
        return empty
    if not isinstance(manifest, Mapping):
        empty["manifest_error"] = "manifest is not a JSON object"
        return empty
    raw_counts = manifest.get("counts")
    if not isinstance(raw_counts, Mapping):
        empty["manifest_error"] = "manifest counts are missing"
        return empty
    filter_counts = {
        str(key): value
        for key, value in raw_counts.items()
        if type(value) is int
    }
    records = raw_counts.get("records")
    if type(records) is not int:
        empty["manifest_error"] = "manifest records count is missing"
        records = 0
    blockers = empty_run_blockers(manifest, source_site=source_site)
    return {
        "records": records,
        "pipeline_run_id": manifest.get("pipeline_run_id"),
        "stopped_reason": manifest.get("stopped_reason"),
        "filter_counts": filter_counts,
        "empty_valid": records == 0 and not blockers and is_valid_empty_run(
            manifest, source_site=source_site
        ),
        "manifest_error": (
            empty["manifest_error"]
            or (
                f"invalid empty run manifest: {', '.join(blockers)}"
                if records == 0 and blockers
                else None
            )
        ),
    }


def _error_summary(
    completed: subprocess.CompletedProcess[str],
    status: str,
    *,
    manifest_error: str | None = None,
) -> str | None:
    if RunOutcome.is_success(status):
        return None
    stderr = (completed.stderr or "").strip()
    if stderr:
        # Last lines carry the failure; the head is progress output.
        return "\n".join(stderr.splitlines()[-8:])[:1200]
    if manifest_error:
        return manifest_error
    if status == RunOutcome.FAILED:
        return f"exited {completed.returncode} with no stderr"
    return None


def append_history(path: Path, record: RunRecord) -> None:
    """Append one line. Never rewrites, so a crash cannot lose earlier runs."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")


def read_history(path: Path) -> list[RunRecord]:
    """Read history, skipping lines that are not readable.

    A partially written final line — a crash mid-append — must not make the
    whole history unreadable, because the gap check depends on it.
    """

    if not path.exists():
        return []
    records: list[RunRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            records.append(RunRecord(**raw))
        except TypeError:
            continue
    return records


def detect_gap(
    history: Sequence[RunRecord],
    *,
    site: str,
    now: datetime,
    max_interval_hours: int = DEFAULT_MAX_INTERVAL_HOURS,
) -> str | None:
    """Report a collection gap for one site, or None when it is on schedule.

    "결번" is measured from the last successful scheduled run. SUCCESS_EMPTY
    is a successful request/parser round and resets the clock; FAILED and the
    legacy EMPTY state do not.
    """

    successes = [
        record
        for record in history
        if record.site == site and RunOutcome.is_success(record.status)
    ]
    if not successes:
        return f"{site}: 성공한 수집 이력이 없습니다"

    latest = max(successes, key=lambda record: record.finished_at)
    finished = _parse_timestamp(latest.finished_at)
    if finished is None:
        return f"{site}: 마지막 수집 시각을 읽을 수 없습니다 ({latest.finished_at!r})"

    elapsed = now - finished
    if elapsed > timedelta(hours=max_interval_hours):
        hours = elapsed.total_seconds() / 3600
        return (
            f"{site}: 마지막 성공 수집이 {hours:.1f}시간 전입니다 "
            f"(허용 {max_interval_hours}시간, {latest.finished_at})"
        )
    return None


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def count_blocked_runs(
    history: Sequence[RunRecord],
    *,
    site: str | None = None,
    since: datetime | None = None,
) -> list[RunRecord]:
    """Runs that a site refused, for the S15P21E102-101 completion criterion.

    A run blocked after it had already collected records is recorded as
    SUCCESS, because postings did accumulate — but it is still a block, and
    "7일 연속 수집 중 차단 0회" counts blocks, not failures. So this reads
    `stopped_reason` rather than `status`.
    """

    found = []
    for record in history:
        if site is not None and record.site != site:
            continue
        reason = (record.stopped_reason or "") + " " + (record.error or "")
        if "blocked" not in reason.lower():
            continue
        if since is not None:
            finished = _parse_timestamp(record.finished_at)
            if finished is None or finished < since:
                continue
        found.append(record)
    return found


def notify(webhook_url: str | None, text: str, *, timeout: float = 10.0) -> bool:
    """Post a plain-text alert to the team channel.

    Returns whether it was delivered and never raises. An alert that fails to
    send must not fail the collection it is reporting on — the run already
    happened, and losing its history would be the worse outcome.
    """

    if not webhook_url:
        return False
    # Only http(s). A config or env var holding file:// or another scheme must
    # not turn an alert into a local read through urlopen.
    if not webhook_url.lower().startswith(("http://", "https://")):
        return False
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def render_os_schedule(config: ScheduleConfig, *, flavour: str = "cron") -> list[str]:
    """Render the OS scheduler lines from the declared times.

    Generated rather than documented so the crontab and this file cannot
    disagree about when collection runs.
    """

    lines: list[str] = []
    for run in config.runs:
        if not run.enabled:
            continue
        for when in run.at:
            hour, _, minute = when.partition(":")
            if flavour == "cron":
                lines.append(
                    f"{int(minute)} {int(hour)} * * * "
                    f"cd /srv/gitjob && "
                    f"PYTHONPATH=AI python -m job.collector --run {run.name}"
                )
            elif flavour == "schtasks":
                lines.append(
                    f'schtasks /Create /TN "GitJob-{run.name}" /SC DAILY '
                    f'/ST {when} /TR "python -m job.collector --run {run.name}"'
                )
            else:
                raise ValueError(f"unknown flavour {flavour!r}")
    return lines
