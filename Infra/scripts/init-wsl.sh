#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.wsl}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi

if [[ -e "$ENV_FILE" ]]; then
  echo "Already exists: $ENV_FILE"
  echo "Delete it only if you intentionally want to recreate the local settings."
  exit 0
fi

cp "$REPO_ROOT/.env.example" "$ENV_FILE"

if command -v openssl >/dev/null 2>&1; then
  replace_value() {
    local key="$1"
    local value="$2"
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  }

  replace_value POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  # The Debezium replication role is separate from the application DB user;
  # BE/src/main/resources/db/changes/002_analysis_outbox_cdc.sql needs this value.
  replace_value CDC_DATABASE_PASSWORD "$(openssl rand -hex 24)"
  replace_value REDIS_PASSWORD "$(openssl rand -hex 24)"
  replace_value JWT_SECRET "$(openssl rand -hex 32)"
  replace_value JENKINS_ADMIN_PASSWORD "$(openssl rand -hex 24)"
else
  echo "warning: openssl is unavailable; replace all change-me values manually" >&2
fi

chmod 600 "$ENV_FILE"
echo "Created $ENV_FILE"
echo "Review the values, then run ./Infra/scripts/up.sh"
echo "When the ci profile is enabled, Jenkins issues the inbound agent secret after the controller starts."
