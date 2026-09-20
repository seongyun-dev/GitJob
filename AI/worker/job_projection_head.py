"""Audited compare-and-swap operations for the published job projection head."""

from __future__ import annotations

import argparse
import json
import os

from worker.job_projection_store import JobProjectionStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-current", required=True)
    parser.add_argument("--to", required=True, dest="target")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    dsn = os.environ.get("C_COMPUTE_DATABASE_URL")
    if not dsn:
        parser.error("C_COMPUTE_DATABASE_URL is required")
    selected = JobProjectionStore(dsn).rollback(
        expected_current=args.expected_current,
        target_projection_version_id=args.target,
        actor=args.actor,
        reason=args.reason,
    )
    print(
        json.dumps(
            {
                "status": "ROLLED_BACK",
                "from_projection_version_id": args.expected_current,
                "to_projection_version_id": selected,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
