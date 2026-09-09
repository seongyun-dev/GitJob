#!/usr/bin/env bash

# Applies BE/src/main/resources/db/cdc/cdc_prerequisites.sql: the replication role,
# its grants, and the publication Debezium reads.
#
# These objects are deliberately not Flyway migrations. The role needs a password
# substituted into it, CREATE ROLE is a cluster-level object rather than a schema
# change, and neither CREATE ROLE nor CREATE PUBLICATION can be re-run. As a
# migration, one failure would leave the application unable to start at all. See
# BE/src/main/resources/db/README.md.
#
# Run this once, after the schema migrations have been applied — the grants and the
# publication reference analysis_outbox and cdc_heartbeat, so it fails with
# "relation does not exist" if the backend has not started yet.
#
# NOT idempotent: re-running fails on the objects that already exist. That is why it
# checks first and refuses rather than leaving the database half-changed.
#
# Usage:
#   ./Infra/scripts/cdc-apply-prerequisites.sh
#   ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
#     PROFILES=core ./Infra/scripts/cdc-apply-prerequisites.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

PREREQUISITES_SQL="$REPO_ROOT/BE/src/main/resources/db/cdc/cdc_prerequisites.sql"
[[ -f "$PREREQUISITES_SQL" ]] || die "CDC prerequisites file is missing: $PREREQUISITES_SQL"

read_env() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

container_id="$(compose ps -q postgres | head -n 1)"
[[ -n "$container_id" ]] || die "postgres container is not running for the selected profiles"

database_name="${POSTGRES_DB:-$(read_env POSTGRES_DB)}"
[[ -n "$database_name" ]] || die "POSTGRES_DB is not set in $ENV_FILE"

cdc_password="${CDC_DATABASE_PASSWORD:-$(read_env CDC_DATABASE_PASSWORD)}"
[[ -n "$cdc_password" ]] || die "CDC_DATABASE_PASSWORD is not set in $ENV_FILE"

state="$(compose exec -T postgres sh -c '
  psql -tAX -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT coalesce((SELECT '"'"'y'"'"' FROM pg_roles WHERE rolname='"'"'gitjob_cdc'"'"'), '"'"'n'"'"')
        || coalesce((SELECT '"'"'y'"'"' FROM pg_publication WHERE pubname='"'"'gitjob_analysis_outbox_pub'"'"'), '"'"'n'"'"')
        || coalesce((SELECT '"'"'y'"'"' FROM information_schema.tables
             WHERE table_schema='"'"'public'"'"' AND table_name='"'"'analysis_outbox'"'"'), '"'"'n'"'"')"
' | tr -d '\r')"

role_present="${state:0:1}"
publication_present="${state:1:1}"
outbox_present="${state:2:1}"

[[ "$outbox_present" == "y" ]] \
  || die "analysis_outbox does not exist yet; start the backend so Flyway applies the migrations first"

if [[ "$role_present" == "y" && "$publication_present" == "y" ]]; then
  echo "Role and publication already exist; nothing to apply."
  exit 0
fi
if [[ "$role_present" == "y" || "$publication_present" == "y" ]]; then
  die "partially applied (role=$role_present publication=$publication_present); inspect the database before re-running"
fi

echo "Applying CDC prerequisites to database $database_name..."

# The substituted SQL is streamed straight into psql: it is never written to disk,
# so the password does not land in a temp file. ON_ERROR_STOP keeps a failure from
# leaving some statements applied and the rest skipped.
sed -e "s|__CDC_PASSWORD__|$cdc_password|g" -e "s|__DATABASE_NAME__|$database_name|g" \
  "$PREREQUISITES_SQL" \
  | compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "Done. Register the connector next: ./Infra/scripts/cdc-register.sh"
