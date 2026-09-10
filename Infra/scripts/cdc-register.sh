#!/usr/bin/env bash
#
# Registers (or updates) the Debezium outbox connector from Infra/cdc/connector.json.
# Safe to re-run: PUT /connectors/<name>/config is idempotent and keeps the
# existing replication slot and source offsets, so no event is replayed.
#
# Prerequisites, in order:
#   1. postgres running with wal_level=logical (compose does this)
#   2. BE/src/main/resources/db/cdc/cdc_prerequisites.sql applied once
#   3. CDC_DATABASE_PASSWORD in the env file, matching that migration

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

CONNECTOR_TEMPLATE="$INFRA_DIR/cdc/connector.json"
[[ -f "$CONNECTOR_TEMPLATE" ]] || die "connector definition is missing: $CONNECTOR_TEMPLATE"

read_env() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

connector_name="${CDC_CONNECTOR_NAME:-$(read_env CDC_CONNECTOR_NAME)}"
connector_name="${connector_name:-analysis-outbox}"
database_host="${DB_HOST:-$(read_env DB_HOST)}"
database_host="${database_host:-postgres}"
database_port="${DB_PORT:-$(read_env DB_PORT)}"
database_port="${database_port:-5432}"
database_name="${POSTGRES_DB:-$(read_env POSTGRES_DB)}"
[[ -n "$database_name" ]] || die "POSTGRES_DB is not set in $ENV_FILE"

[[ -n "$(service_container_id kafka-connect)" ]] \
  || die "kafka-connect is not running; start it with PROFILES=core ./Infra/scripts/up.sh"

# The worker resolves ${env:CDC_DATABASE_PASSWORD} itself, so the rendered
# config below still carries no secret.
config="$(sed \
  -e "s|__DATABASE_HOST__|$database_host|g" \
  -e "s|__DATABASE_PORT__|$database_port|g" \
  -e "s|__DATABASE_NAME__|$database_name|g" \
  "$CONNECTOR_TEMPLATE")"

echo "Registering connector '$connector_name' against $database_host:$database_port/$database_name"
# Body and status come back on the same stream rather than through a file inside
# the container. Git Bash rewrites an argument that looks like an absolute path
# (/tmp/x becomes C:/Users/.../Temp/x), so the earlier `-o /tmp/...` form pointed
# curl at a directory the container does not have. It failed on Windows only, and
# only at the moment of registration.
response="$(printf '%s' "$config" | compose exec -T kafka-connect \
  curl -sS -w '\n%{http_code}' \
  -X PUT -H 'Content-Type: application/json' --data @- \
  "http://localhost:8083/connectors/$connector_name/config")"
status="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$status" != "200" && "$status" != "201" ]]; then
  echo "Connector registration failed (HTTP $status):" >&2
  echo "$body" >&2
  exit 1
fi

echo "Registered. Current status:"
compose exec -T kafka-connect \
  curl -sS "http://localhost:8083/connectors/$connector_name/status"
echo
