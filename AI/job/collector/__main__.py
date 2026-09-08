"""CLI for the declared collection schedule (S15P21E102-107).

    python -m job.collector --run worknet-morning   # 한 회차 실행
    python -m job.collector --check                 # 결번만 점검
    python -m job.collector --render cron           # crontab 줄 출력
    python -m job.collector --history               # 최근 이력

Invoked by cron or Windows Task Scheduler at the times `schedule.toml`
declares. It always writes history and always alerts on a bad run, so its own
exit code is what the OS scheduler logs, not the only record of the failure.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job.collector.schedule import (
    RunOutcome,
    ScheduleConfig,
    append_history,
    count_blocked_runs,
    detect_gap,
    execute_run,
    load_schedule,
    notify,
    read_history,
    render_os_schedule,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "schedule.toml"


def _webhook(config: ScheduleConfig) -> str | None:
    if not config.webhook_env:
        return None
    return os.environ.get(config.webhook_env) or None


def _alert(config: ScheduleConfig, text: str) -> None:
    """Print the alert, then try to deliver it.

    Printing first means the alert survives a missing or broken webhook — the
    OS scheduler's log still carries it.
    """

    print(f"ALERT {text}", file=sys.stderr)
    if not _webhook(config):
        print(
            "  (알림 미발송: "
            f"{config.webhook_env or 'webhook_env 미선언'} 환경변수가 비어 있습니다)",
            file=sys.stderr,
        )
        return
    if not notify(_webhook(config), text):
        print("  (알림 발송 실패)", file=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m job.collector")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--run", default=None, help="declared run name to execute")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check every site for a collection gap and alert; collects nothing",
    )
    parser.add_argument(
        "--render",
        default=None,
        choices=("cron", "schtasks"),
        help="print OS scheduler lines for the declared times",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="print the most recent run history",
    )
    parser.add_argument("--history-limit", type=int, default=20)
    parser.add_argument(
        "--blocks",
        type=int,
        nargs="?",
        const=7,
        default=None,
        metavar="DAYS",
        help="report site refusals over the last N days (default 7) and exit",
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="send one alert to verify delivery (S15P21E102-107 완료 조건)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        config = load_schedule(config_path)
    except (OSError, ValueError, KeyError) as error:
        print(f"schedule config unusable: {error}", file=sys.stderr)
        return 2

    if args.render:
        for line in render_os_schedule(config, flavour=args.render):
            print(line)
        return 0

    if args.history:
        history = read_history(config.history_path)
        if not history:
            print(f"이력 없음 ({config.history_path})")
            return 0
        for record in history[-args.history_limit :]:
            print(
                f"{record.finished_at}  {record.site:<10} {record.status:<8} "
                f"{record.records:>4}건  {record.run_name}"
                + (f"  {record.stopped_reason[:50]}" if record.stopped_reason else "")
                + (f"  {record.error.splitlines()[-1][:60]}" if record.error else "")
            )
        return 0

    if args.blocks is not None:
        since = datetime.now(UTC) - timedelta(days=args.blocks)
        blocked = count_blocked_runs(read_history(config.history_path), since=since)
        if not blocked:
            print(f"최근 {args.blocks}일 차단 0회")
            return 0
        print(f"최근 {args.blocks}일 차단 {len(blocked)}회")
        for record in blocked:
            reason = (record.stopped_reason or record.error or "").splitlines()[0]
            print(f"  {record.finished_at}  {record.site:<10} {reason[:70]}")
        return 1

    if args.test_alert:
        text = "[GitJob] 수집 알림 발송 테스트 (S15P21E102-107)"
        print(f"ALERT {text}", file=sys.stderr)
        webhook = _webhook(config)
        if not webhook:
            print(
                f"  ({config.webhook_env or 'webhook_env 미선언'} 환경변수가 비어 "
                "있어 발송하지 않았습니다)",
                file=sys.stderr,
            )
            return 1
        if notify(webhook, text):
            print("발송 성공")
            return 0
        print("  (알림 발송 실패)", file=sys.stderr)
        return 1

    now = datetime.now(UTC)

    if args.check:
        gaps = [
            gap
            for site in dict.fromkeys(run.site for run in config.runs)
            if (
                gap := detect_gap(
                    read_history(config.history_path),
                    site=site,
                    now=now,
                    max_interval_hours=config.max_interval_hours,
                )
            )
        ]
        for gap in gaps:
            _alert(config, f"[GitJob] 수집 결번 - {gap}")
        if not gaps:
            print("결번 없음")
        return 1 if gaps else 0

    if not args.run:
        print(
            "--run, --check, --render, --history 중 하나가 필요합니다", file=sys.stderr
        )
        return 2

    try:
        run = config.run(args.run)
    except KeyError as error:
        print(error, file=sys.stderr)
        return 2
    if not run.enabled:
        print(f"{run.name} is disabled in {config_path}", file=sys.stderr)
        return 0

    record = execute_run(run, now=now, cwd=config_path.parent)
    # History first. An alert that fails must not cost us the record of what
    # ran, because the gap check is built on it.
    append_history(config.history_path, record)
    print(
        f"{record.status} {record.records}건 exit={record.exit_code} "
        f"run={record.run_name}"
    )

    if record.status != RunOutcome.SUCCESS:
        detail = f" - {record.error.splitlines()[-1][:160]}" if record.error else ""
        _alert(
            config,
            f"[GitJob] 수집 {record.status} - {record.site} {record.run_name}"
            f" ({record.records}건, exit {record.exit_code}){detail}",
        )

    gap = detect_gap(
        read_history(config.history_path),
        site=run.site,
        now=now,
        max_interval_hours=config.max_interval_hours,
    )
    if gap:
        _alert(config, f"[GitJob] 수집 결번 - {gap}")

    return 0 if record.status == RunOutcome.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
