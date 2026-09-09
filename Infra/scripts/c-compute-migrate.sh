#!/usr/bin/env bash

# Applies the c_compute migration that the worker needs, from inside the worker
# container.
#
# The worker never creates its own tables: AI/worker/migrate.py exists precisely so
# that DDL is an explicit, approved step rather than something a container does on
# startup. That is why this is a separate script and not part of deploy.sh.
#
# migrate.py insists on C_COMPUTE_DATABASE_URL rather than falling back to the
# POSTGRES_* variables, so that nobody applies DDL to a database they did not name.
# We honour that by building the URL here from the values the worker container
# already holds, which also means no new secret has to be added to any env file.
#
# The SQL ships in the image at /app/migrations/001_c_compute.sql
# (Infra/docker/worker/Dockerfile), which is where migrate.py looks by default.
#
# Safe to re-run: the migration is written with CREATE ... IF NOT EXISTS and records
# itself in c_compute.schema_version.
#
# Usage:
#   ./Infra/scripts/c-compute-migrate.sh
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
#     PROFILES=data ./Infra/scripts/c-compute-migrate.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

container_id="$(compose ps -q worker | head -n 1)"
[[ -n "$container_id" ]] || die "worker container is not running for the selected profiles"

echo "Applying the c_compute migration inside the worker container..."

# The URL is assembled and consumed inside the container, so the password never
# reaches this shell, its history, or the process list on the host.
compose exec -T worker sh -c '
  set -e
  for name in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT POSTGRES_DB; do
    eval "value=\$$name"
    if [ -z "$value" ]; then
      echo "$name is not set in the worker container" >&2
      exit 1
    fi
  done
  C_COMPUTE_DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB" \
    python -m worker.migrate
'

echo "Done. Confirm with: ./Infra/scripts/verify-deployment.sh"
