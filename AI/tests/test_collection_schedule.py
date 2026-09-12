"""Tests for the declared collection schedule (S15P21E102-107).

The ticket's completion criteria are "이틀 연속 결번 없음" and "실패 알림 1회
이상 실제 수신", so the cases that matter here are the ones that decide whether
a gap is reported and whether a bad run alerts.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job.collector.schedule import (
    RunOutcome,
    RunRecord,
    ScheduledRun,
    append_history,
    count_blocked_runs,
    detect_gap,
    execute_run,
    load_schedule,
    notify,
    read_history,
    render_os_schedule,
)

NOW = datetime(2026, 9, 7, 21, 30, tzinfo=UTC)

SCHEDULE_TOML = """
max_interval_hours = 14
history_path = "history.jsonl"
webhook_env = "TEST_ALERT_WEBHOOK"

[[run]]
name = "worknet-morning"
site = "WORKNET"
module = "Worknet_Collector_V1"
at = ["09:10"]
args = ["--occupation-preset", "dev", "--days-back", "1"]

[[run]]
name = "worknet-evening"
site = "WORKNET"
module = "Worknet_Collector_V1"
at = ["21:10"]
args = ["--occupation-preset", "dev"]

[[run]]
name = "saramin-morning"
site = "SARAMIN"
module = "Saramin_Collector_V1"
at = ["09:30"]
enabled = false
args = []
"""


def _write_schedule(tmp_path: Path, body: str = SCHEDULE_TOML) -> Path:
    path = tmp_path / "schedule.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _record(**overrides: object) -> RunRecord:
    fields: dict[str, object] = {
        "run_name": "worknet-morning",
        "site": "WORKNET",
        "started_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "status": RunOutcome.SUCCESS,
        "records": 12,
        "exit_code": 0,
    }
    fields.update(overrides)
    return RunRecord(**fields)  # type: ignore[arg-type]


# --- config ----------------------------------------------------------------


def test_schedule_declares_two_runs_a_day_for_worknet(tmp_path: Path):
    config = load_schedule(_write_schedule(tmp_path))

    worknet = [run for run in config.runs if run.site == "WORKNET"]
    assert [run.at for run in worknet] == [("09:10",), ("21:10",)]


def test_history_path_is_resolved_relative_to_the_config(tmp_path: Path):
    config = load_schedule(_write_schedule(tmp_path))
    assert config.history_path == (tmp_path / "history.jsonl").resolve()


def test_webhook_url_is_not_stored_in_the_config(tmp_path: Path):
    """Only the env var name lives in the file (S15P21E102-106)."""

    config = load_schedule(_write_schedule(tmp_path))
    assert config.webhook_env == "TEST_ALERT_WEBHOOK"
    assert "http" not in _write_schedule(tmp_path).read_text(encoding="utf-8")


def test_unknown_run_name_is_rejected_with_the_known_names(tmp_path: Path):
    config = load_schedule(_write_schedule(tmp_path))
    with pytest.raises(KeyError, match="worknet-morning"):
        config.run("worknet-noon")


def test_a_config_with_no_runs_is_rejected(tmp_path: Path):
    path = tmp_path / "schedule.toml"
    path.write_text("history_path = 'h.jsonl'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="declares no runs"):
        load_schedule(path)


def test_disabled_run_is_loaded_but_marked(tmp_path: Path):
    config = load_schedule(_write_schedule(tmp_path))
    assert config.run("saramin-morning").enabled is False


# --- OS scheduler rendering ------------------------------------------------


def test_cron_lines_come_from_the_declared_times(tmp_path: Path):
    lines = render_os_schedule(load_schedule(_write_schedule(tmp_path)))

    assert len(lines) == 2
    assert lines[0].startswith("10 9 * * *")
    assert lines[1].startswith("10 21 * * *")
    assert "--run worknet-morning" in lines[0]


def test_disabled_runs_are_not_scheduled(tmp_path: Path):
    lines = render_os_schedule(load_schedule(_write_schedule(tmp_path)))
    assert all("saramin" not in line for line in lines)


def test_schtasks_flavour_renders_windows_commands(tmp_path: Path):
    lines = render_os_schedule(
        load_schedule(_write_schedule(tmp_path)),
        flavour="schtasks",
    )
    assert lines[0].startswith("schtasks /Create")
    assert "/ST 09:10" in lines[0]


def test_unknown_flavour_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown flavour"):
        render_os_schedule(
            load_schedule(_write_schedule(tmp_path)),
            flavour="systemd",
        )


# --- history ---------------------------------------------------------------


def test_history_is_append_only(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    append_history(path, _record(run_name="first"))
    append_history(path, _record(run_name="second"))

    assert [record.run_name for record in read_history(path)] == ["first", "second"]


def test_history_survives_a_truncated_final_line(tmp_path: Path):
    """A crash mid-append must not make the gap check unusable."""

    path = tmp_path / "history.jsonl"
    append_history(path, _record(run_name="complete"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"run_name": "torn", "site":')

    assert [record.run_name for record in read_history(path)] == ["complete"]


def test_history_skips_lines_with_unexpected_fields(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    append_history(path, _record())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"unrelated": True}) + "\n")

    assert len(read_history(path)) == 1


def test_missing_history_reads_as_empty(tmp_path: Path):
    assert read_history(tmp_path / "absent.jsonl") == []


# --- gap detection: the completion criterion --------------------------------


def test_no_gap_when_the_last_success_is_within_the_window():
    history = [_record(finished_at=(NOW - timedelta(hours=12)).isoformat())]
    assert detect_gap(history, site="WORKNET", now=NOW) is None


def test_gap_when_the_last_success_is_older_than_the_window():
    history = [_record(finished_at=(NOW - timedelta(hours=15)).isoformat())]
    gap = detect_gap(history, site="WORKNET", now=NOW)

    assert gap is not None
    assert "15.0시간 전" in gap


def test_a_failed_run_does_not_reset_the_clock():
    """The postings from a failed window are exactly what went missing."""

    history = [
        _record(finished_at=(NOW - timedelta(hours=20)).isoformat()),
        _record(
            finished_at=(NOW - timedelta(hours=1)).isoformat(),
            status=RunOutcome.FAILED,
            records=0,
            exit_code=1,
        ),
    ]
    assert detect_gap(history, site="WORKNET", now=NOW) is not None


def test_an_empty_run_does_not_reset_the_clock():
    history = [
        _record(finished_at=(NOW - timedelta(hours=20)).isoformat()),
        _record(
            finished_at=(NOW - timedelta(hours=1)).isoformat(),
            status=RunOutcome.EMPTY,
            records=0,
        ),
    ]
    assert detect_gap(history, site="WORKNET", now=NOW) is not None


def test_no_history_at_all_is_reported_as_a_gap():
    assert (
        detect_gap([], site="WORKNET", now=NOW)
        == "WORKNET: 성공한 수집 이력이 없습니다"
    )


def test_a_gap_is_per_site():
    history = [_record(site="WORKNET", finished_at=NOW.isoformat())]

    assert detect_gap(history, site="WORKNET", now=NOW) is None
    assert detect_gap(history, site="SARAMIN", now=NOW) is not None


def test_two_days_of_twice_daily_runs_report_no_gap():
    """The ticket's "이틀 연속 결번 없음" expressed as a test."""

    history = [
        _record(finished_at=(NOW - timedelta(hours=hours)).isoformat())
        for hours in (48, 36, 24, 12, 0)
    ]
    assert detect_gap(history, site="WORKNET", now=NOW) is None


def test_a_missed_cycle_in_the_middle_is_caught_at_that_moment():
    history = [_record(finished_at=(NOW - timedelta(hours=36)).isoformat())]
    at_the_miss = NOW - timedelta(hours=12)
    assert detect_gap(history, site="WORKNET", now=at_the_miss) is not None


def test_unreadable_timestamp_is_reported_rather_than_ignored():
    history = [_record(finished_at="어제")]
    gap = detect_gap(history, site="WORKNET", now=NOW)
    assert gap is not None and "읽을 수 없습니다" in gap


def test_naive_timestamp_is_treated_as_utc():
    history = [
        _record(finished_at=(NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat())
    ]
    assert detect_gap(history, site="WORKNET", now=NOW) is None


# --- executing a run -------------------------------------------------------


def _execute_code(code: str, tmp_path: Path, **kwargs: object) -> RunRecord:
    script = tmp_path / "fake_collector.py"
    script.write_text(code, encoding="utf-8")
    run = ScheduledRun(
        name="probe",
        site="WORKNET",
        module="fake_collector",
        args=(),
        at=("09:10",),
    )
    return execute_run(run, cwd=tmp_path, python=sys.executable, **kwargs)  # type: ignore[arg-type]


def test_a_run_reports_the_record_count_from_the_manifest(tmp_path: Path):
    (tmp_path / "m.json").write_text(
        json.dumps({"counts": {"records": 7}, "pipeline_run_id": "WORKNET-X"}),
        encoding="utf-8",
    )
    record = _execute_code('print("manifest=m.json")', tmp_path)

    assert record.status == RunOutcome.SUCCESS
    assert record.records == 7
    assert record.pipeline_run_id == "WORKNET-X"
    assert record.error is None


def test_a_zero_record_run_is_empty_not_success(tmp_path: Path):
    """A broken selector looks exactly like a quiet day; do not conflate them."""

    (tmp_path / "m.json").write_text(
        json.dumps({"counts": {"records": 0}}), encoding="utf-8"
    )
    record = _execute_code('print("manifest=m.json")', tmp_path)
    assert record.status == RunOutcome.EMPTY


def test_a_crashing_collector_is_recorded_not_raised(tmp_path: Path):
    record = _execute_code(
        'import sys; print("boom", file=sys.stderr); sys.exit(3)',
        tmp_path,
    )

    assert record.status == RunOutcome.FAILED
    assert record.exit_code == 3
    assert record.error is not None and "boom" in record.error


def test_a_missing_module_is_recorded_as_a_failure(tmp_path: Path):
    run = ScheduledRun(
        name="probe",
        site="WORKNET",
        module="module_that_does_not_exist",
        args=(),
        at=("09:10",),
    )
    record = execute_run(run, cwd=tmp_path, python=sys.executable)
    assert record.status == RunOutcome.FAILED


def test_a_timeout_is_recorded_as_a_failure(tmp_path: Path):
    record = _execute_code(
        "import time; time.sleep(5)",
        tmp_path,
        timeout_seconds=0.4,
    )

    assert record.status == RunOutcome.FAILED
    assert record.error is not None and "timed out" in record.error


def test_an_unreadable_manifest_does_not_crash_the_run(tmp_path: Path):
    record = _execute_code('print("manifest=absent.json")', tmp_path)
    assert record.status == RunOutcome.EMPTY
    assert record.records == 0


def test_a_nonzero_exit_that_still_collected_is_not_a_failure(tmp_path: Path):
    """A blocked later page keeps the postings the run already validated."""

    (tmp_path / "m.json").write_text(
        json.dumps({"counts": {"records": 4}}), encoding="utf-8"
    )
    record = _execute_code(
        'import sys; print("manifest=m.json"); sys.exit(1)',
        tmp_path,
    )
    assert record.status == RunOutcome.SUCCESS
    assert record.records == 4


# --- alerting --------------------------------------------------------------


def test_notify_without_a_url_is_a_no_op():
    assert notify(None, "text") is False
    assert notify("", "text") is False


def test_notify_never_raises_on_an_unreachable_host():
    """An alert that cannot be sent must not fail the run it reports on."""

    assert notify("http://127.0.0.1:9/hook", "text", timeout=0.4) is False


def test_notify_rejects_a_non_http_url():
    assert notify("file:///etc/passwd", "text") is False


# --- 실제 schedule.toml -----------------------------------------------------

REPO_SCHEDULE = Path(__file__).resolve().parents[1] / "schedule.toml"


def test_repo_schedule_declares_two_runs_a_day_per_site():
    """The ticket is "하루 2회"; a site with one run would not meet it.

    Asserted per site rather than against a fixed total, so adding a fourth
    collector cannot satisfy this by giving one site four runs and another
    none.
    """

    config = load_schedule(REPO_SCHEDULE)

    per_site: dict[str, int] = {}
    for run in config.runs:
        if run.enabled:
            per_site[run.site] = per_site.get(run.site, 0) + len(run.at)

    assert per_site, "no enabled runs declared"
    assert all(count == 2 for count in per_site.values()), per_site


def test_repo_schedule_covers_the_target_sites():
    """S15P21E102-196 admitted the three 기준 A 미통과 sites.

    `-94` had fixed the targets at 사람인 · 워크넷 on criterion A. The project
    owner admitted 게임잡 · 커리어 · 잡코리아 on 2026-09-10 knowing each
    ground still stands — see `test_criterion_a_failures_are_admitted_on_the
    _record`.

    Listed explicitly rather than accepting "whatever the file says", because
    a site silently dropped from the schedule is exactly the gap this suite
    exists to catch. It now also catches a site silently *added*.
    """

    config = load_schedule(REPO_SCHEDULE)
    assert {run.site for run in config.runs if run.enabled} == {
        "WORKNET",
        "SARAMIN",
        "GAMEJOB",
        "CAREER",
    }
    # Declared but off: `-230` excluded it from the MVP without deleting it.
    assert {run.site for run in config.runs} == {
        "WORKNET",
        "SARAMIN",
        "GAMEJOB",
        "CAREER",
        "JOBKOREA",
    }


def test_criterion_a_failures_are_admitted_on_the_record():
    """The three admitted sites failed criterion A, and that has to stay said.

    Until 2026-09-10 these shipped `enabled = false` and this suite asserted
    it, so that turning one on could not happen by editing a comment. The
    owner has now turned all three on (`-196`). The grounds did not change:

        게임잡    `-149` §3 — operator is the same legal entity as 잡코리아,
                  so `-94`'s case-law ground carries over
        커리어    `-149` §10 — 이용약관 제14조 5항 prohibits 복제·배포
                  without consent; 기준 A is an OR condition, so robots.txt
                  allowing the paths is not a pass
        잡코리아  `-94` §3.1 — 서울고등법원 held unauthorized crawling of this
                  site's postings to infringe 데이터베이스제작자 권리

    So what this test guards moved rather than disappeared. It no longer
    asserts the runs are off; it asserts the schedule still *names* each
    ground, so nobody can quietly re-tell the story as "these were fine all
    along". The per-run `source_admission` block in each collector's manifest
    is the other half of that record.

    On 2026-09-13 the owner took JobKorea back out of the MVP (`-230`), which
    is a partial reversal of `-196` and not a change of grounds. 게임잡 and
    커리어 stay on. So this now asserts three things at once: all three are
    still declared, only the two the owner kept are enabled, and the file still
    states every ground — including JobKorea's, which is the strongest of the
    three and the reason it is the one that went back off.
    """

    config = load_schedule(REPO_SCHEDULE)
    text = REPO_SCHEDULE.read_text(encoding="utf-8")

    for site in ("GAMEJOB", "CAREER", "JOBKOREA"):
        runs = [run for run in config.runs if run.site == site]
        assert runs, f"{site} runs should stay declared"

    for site in ("GAMEJOB", "CAREER"):
        runs = [run for run in config.runs if run.site == site]
        assert all(run.enabled for run in runs), f"{site} was admitted by -196"

    jobkorea = [run for run in config.runs if run.site == "JOBKOREA"]
    assert not any(run.enabled for run in jobkorea), "JOBKOREA was excluded by -230"
    # Excluded, not discarded: `-195` tried deletion and never merged.
    assert (REPO_SCHEDULE.parent / "JobKorea_Collector_V1").is_dir()
    assert "`-230`" in text

    # The decision, the date and the reversal are all in the file.
    assert text.count("기준 A 미통과") >= 3
    assert text.count("`-196`") >= 3
    assert text.count("2026-09-10") >= 3
    assert "서울고등법원" in text
    assert "제14조 5항" in text
    assert "110-81-34859" in text
    assert text.count("되돌리려면") >= 3


def test_check_ignores_sites_whose_every_run_is_disabled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """A site that is deliberately off has no gap to report.

    게임잡 is declared with `enabled = false` (criterion A, see
    `test_gamejob_is_declared_but_never_scheduled`) and has no history at all,
    so `detect_gap` returns "성공한 수집 이력이 없습니다" for it on every check.

    That was invisible while `GITJOB_ALERT_WEBHOOK_URL` was unset and the alert
    only reached a log file. Once alerts reach the team channel it becomes a
    warning nobody can ever clear, which is worse than no warning: it trains
    everyone to ignore the channel, and the next real gap is ignored with it.

    The fixture's SARAMIN run is disabled, so it stands in for 게임잡 here.
    """

    from job.collector.__main__ import main

    config_path = _write_schedule(tmp_path)
    # WORKNET is enabled, so it must still be checked — a fresh success keeps
    # it out of the report and leaves SARAMIN as the only candidate.
    #
    # Timed off the wall clock, not the module's `NOW`: `main` calls
    # `datetime.now(UTC)` itself, so a fixed timestamp would age past
    # `max_interval_hours` and report WORKNET as the gap instead.
    append_history(
        tmp_path / "history.jsonl",
        _record(
            run_name="worknet-evening",
            site="WORKNET",
            finished_at=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        ),
    )

    code = main(["--check", "--config", str(config_path)])
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "SARAMIN" not in combined
    assert "결번 없음" in combined
    assert code == 0


def test_check_still_reports_an_enabled_site(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The skip must be about `enabled`, not about having no history.

    Without this the previous test passes just as well for a check that
    reports nothing at all.
    """

    from job.collector.__main__ import main

    config_path = _write_schedule(tmp_path)
    # No WORKNET history at all, and WORKNET is enabled.
    code = main(["--check", "--config", str(config_path)])
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "WORKNET" in combined
    assert code == 1


def test_every_repo_run_filters_by_job_category():
    """An unfiltered run collects 요양보호사 and 카지노 공채, not developers.

    게임잡 uses `--duty-preset`, and for that site the filter runs on our side
    because the listing does not accept a 직무 code over the query string —
    see `GameJob_Collector_V1/duties.py`. The declaration is still required.

    잡코리아 has no preset flag: it takes one `--duty-code` (1000229 =
    백엔드개발자). That counts, but only when the schedule states it. Relying
    on the CLI default would make the filter change silently the day the
    default does — which is what this test exists to prevent.
    """

    config = load_schedule(REPO_SCHEDULE)
    presets = (
        "--occupation-preset",
        "--category-preset",
        "--duty-preset",
        "--duty-code",
    )
    for run in config.runs:
        if not run.enabled:
            continue
        assert any(preset in run.args for preset in presets), run.name


def test_every_repo_run_covers_the_day_boundary():
    """Yesterday's late postings carry yesterday's date."""

    config = load_schedule(REPO_SCHEDULE)
    for run in config.runs:
        if run.enabled:
            assert "--days-back" in run.args


def test_repo_schedule_keeps_the_webhook_url_out_of_the_file():
    config = load_schedule(REPO_SCHEDULE)
    body = REPO_SCHEDULE.read_text(encoding="utf-8")

    assert config.webhook_env == "GITJOB_ALERT_WEBHOOK_URL"
    assert "https://" not in body


def test_repo_schedule_renders_one_cron_line_per_declared_time():
    """Derived from the file rather than hardcoded.

    A fixed count made adding a third site look like a regression; what
    actually matters is that every declared time produces exactly one crontab
    line, so no run is registered twice or dropped.
    """

    config = load_schedule(REPO_SCHEDULE)
    expected = sum(len(run.at) for run in config.runs if run.enabled)
    lines = render_os_schedule(config)

    assert len(lines) == expected
    assert len(set(lines)) == expected


# --- 차단 계측: S15P21E102-101 완료 조건 -----------------------------------


def test_a_block_after_collecting_records_is_still_counted_as_a_block():
    """The case the run status hides.

    A run blocked on a later page keeps the postings it already validated, so
    it is recorded SUCCESS — postings did accumulate. But "7일 연속 수집 중
    차단 0회" counts blocks, not failures, so the block has to survive in the
    history independently of the status.
    """

    history = [
        _record(
            status=RunOutcome.SUCCESS,
            records=40,
            stopped_reason="blocked: refused with HTTP 403",
        ),
    ]
    blocked = count_blocked_runs(history)

    assert len(blocked) == 1
    assert blocked[0].status == RunOutcome.SUCCESS


def test_a_clean_run_is_not_counted_as_a_block():
    assert count_blocked_runs([_record()]) == []


def test_a_failure_that_is_not_a_block_is_not_counted():
    """A parse error or a timeout is a failure, not a refusal."""

    history = [
        _record(status=RunOutcome.FAILED, records=0, error="timed out after 3600s")
    ]
    assert count_blocked_runs(history) == []


def test_blocks_are_counted_per_site():
    history = [
        _record(site="SARAMIN", stopped_reason="blocked: refused"),
        _record(site="WORKNET"),
    ]
    assert len(count_blocked_runs(history, site="SARAMIN")) == 1
    assert count_blocked_runs(history, site="WORKNET") == []


def test_blocks_outside_the_window_are_excluded():
    """The criterion is a rolling 7 days, not all history."""

    history = [
        _record(
            finished_at=(NOW - timedelta(days=9)).isoformat(),
            stopped_reason="blocked: refused",
        ),
        _record(
            finished_at=(NOW - timedelta(days=2)).isoformat(),
            stopped_reason="blocked: refused",
        ),
    ]
    recent = count_blocked_runs(history, since=NOW - timedelta(days=7))
    assert len(recent) == 1


def test_stopped_reason_survives_a_history_round_trip(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    append_history(path, _record(stopped_reason="blocked: refused with HTTP 403"))

    reloaded = read_history(path)[0]
    assert reloaded.stopped_reason == "blocked: refused with HTTP 403"


def test_execute_run_carries_the_collectors_stopped_reason(tmp_path: Path):
    """The reason comes from the collector's manifest, not from stderr."""

    (tmp_path / "m.json").write_text(
        json.dumps(
            {
                "counts": {"records": 3},
                "stopped_reason": "blocked: refused with HTTP 403",
            }
        ),
        encoding="utf-8",
    )
    record = _execute_code('print("manifest=m.json")', tmp_path)

    assert record.status == RunOutcome.SUCCESS
    assert record.stopped_reason == "blocked: refused with HTTP 403"
    assert count_blocked_runs([record])
