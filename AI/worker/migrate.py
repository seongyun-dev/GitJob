"""Explicit C migration runner; the HTTP worker never creates tables."""

import argparse
import os
from pathlib import Path

from worker.store import MIGRATION_FILE, apply_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    packaged = Path(__file__).resolve().parents[1] / "migrations/001_c_compute.sql"
    parser.add_argument(
        "--file", type=Path, default=packaged if packaged.exists() else MIGRATION_FILE
    )
    args = parser.parse_args()
    dsn = os.environ.get("C_COMPUTE_DATABASE_URL")
    if not dsn:
        parser.error("C_COMPUTE_DATABASE_URL must explicitly name the target database")
    apply_migration(dsn, args.file)
    print("C compute migration 1 applied or verified")


if __name__ == "__main__":
    main()
