"""Docker runtime probe for the weekly activity consumer.

Business-input readiness is recorded in the status file, but it must not make
an otherwise healthy long-running consumer fail a deployment. ``BLOCKED``
means the consumer initialized successfully and is deliberately backing off
until its external input becomes available.
"""

from __future__ import annotations

import json

from worker.weekly_activity_consumer import _status_path


def main() -> int:
    try:
        value = json.loads(_status_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    return 0 if value.get("state") in {"READY", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
