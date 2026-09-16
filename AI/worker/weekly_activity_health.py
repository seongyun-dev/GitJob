"""Docker readiness probe for the weekly activity consumer."""

from __future__ import annotations

import json

from worker.weekly_activity_consumer import _status_path


def main() -> int:
    try:
        value = json.loads(_status_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    return 0 if value.get("state") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
