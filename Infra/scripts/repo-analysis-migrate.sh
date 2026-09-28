#!/usr/bin/env bash

# Applies the repository analysis consumer's idempotent claim-table migration
# through the service host's PostgreSQL container. The SQL deliberately lives
# outside Spring Flyway because repo_analysis is owned by the Python consumer.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled core || die "core profile is not enabled; use PROFILES=core"

migration_file="$REPO_ROOT/BE/src/main/resources/db/migrations/002_repo_analysis.sql"
[[ -f "$migration_file" ]] || die "repository analysis migration is missing: $migration_file"

echo "Applying the repo_analysis claim-table migration..."
compose exec -T postgres sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$migration_file"

claim_table="$({
  compose exec -T postgres sh -c \
    'psql -tAX -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -c "SELECT to_regclass('"'"'repo_analysis.event_claim'"'"')"'
} | tr -d '\r')"
[[ "$claim_table" == "repo_analysis.event_claim" ]] \
  || die "repo_analysis.event_claim was not created"

echo "Repository analysis migration applied and verified."
