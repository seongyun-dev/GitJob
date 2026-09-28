#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
"$SCRIPT_DIR/healthcheck.sh" >/dev/null

backup_dir="${BACKUP_DIR:-$REPO_ROOT/.local/backups}"
mkdir -p "$backup_dir"
umask 077
db_name="${POSTGRES_DB:-$(sed -n 's/^[[:space:]]*POSTGRES_DB[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" | tail -n 1)}"
db_name="${db_name:-gitjob}"
[[ "$db_name" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "POSTGRES_DB contains characters unsafe for a backup filename"
backup_file="$backup_dir/${db_name}-$(date -u +%Y%m%dT%H%M%SZ).dump"
temporary_file="$backup_file.tmp.$$"
trap 'rm -f "$temporary_file"' EXIT

echo "Creating PostgreSQL backup: $backup_file"
compose exec -T postgres sh -c \
  'pg_dump --format=custom --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$temporary_file"

if [[ ! -s "$temporary_file" ]]; then
  die "backup file is empty"
fi

mv -- "$temporary_file" "$backup_file"

echo "Backup completed."
