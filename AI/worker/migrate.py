"""Explicit C migration runner; the HTTP worker never creates tables."""

import argparse
import os
from pathlib import Path

from worker.store import MIGRATION_FILES, apply_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    packaged = Path(__file__).resolve().parents[1] / "migrations"
    parser.add_argument(
        "--file",
        type=Path,
        action="append",
        dest="files",
        help="Apply only the named migration file; repeat in version order",
    )
    args = parser.parse_args()
    dsn = os.environ.get("C_COMPUTE_DATABASE_URL")
    if not dsn:
        parser.error("C_COMPUTE_DATABASE_URL must explicitly name the target database")
    paths = (
        tuple(args.files)
        if args.files
        else tuple(sorted(packaged.glob("*.sql")))
        if packaged.is_dir()
        else MIGRATION_FILES
    )
    apply_migration(dsn, paths)
    print("C compute migrations applied or verified")


if __name__ == "__main__":
    main()
