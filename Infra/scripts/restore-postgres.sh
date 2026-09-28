#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

backup_file="${1:-}"
[[ -n "$backup_file" ]] || die "usage: CONFIRM_RESTORE=yes $0 /absolute/or/relative/backup.dump"
[[ -f "$backup_file" ]] || die "backup file not found: $backup_file"
[[ "${CONFIRM_RESTORE:-}" == "yes" ]] || die "restore replaces database objects; rerun with CONFIRM_RESTORE=yes"

"$SCRIPT_DIR/healthcheck.sh" >/dev/null
echo "Restoring PostgreSQL backup: $backup_file"
compose exec -T postgres sh -c \
  'pg_restore --exit-on-error --clean --if-exists --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  < "$backup_file"
echo "Restore completed."
