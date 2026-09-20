#!/usr/bin/env bash

# Applies the c_compute migration that the worker needs, from inside the worker
# container.
#
# The worker never creates its own tables: AI/worker/migrate.py exists precisely so
# that DDL is an explicit, approved step rather than something a container does on
# startup. deploy.sh invokes this script in `run` mode after building the new image
# and before recreating the runtime worker.
#
# migrate.py requires either C_COMPUTE_DATABASE_URL or the explicit
# --from-postgres-env switch, so that nobody applies DDL to an implicitly selected
# database. Compose already gives the worker all five POSTGRES_* values; the Python
# runner uses psycopg.make_conninfo so reserved characters are escaped correctly.
#
# The SQL ships in the image at /app/migrations/001_c_compute.sql
# (Infra/docker/worker/Dockerfile), which is where migrate.py looks by default.
#
# Safe to re-run: migrate.py verifies the immutable checksum recorded in
# c_compute.schema_version and skips versions that were already applied.
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

mode="${C_COMPUTE_MIGRATION_MODE:-exec}"
[[ "$mode" == exec || "$mode" == run ]] || die "C_COMPUTE_MIGRATION_MODE must be exec or run"
if [[ "$mode" == exec ]]; then
  container_id="$(compose ps -q worker | head -n 1)"
  [[ -n "$container_id" ]] || die "worker container is not running for the selected profiles"
  runner=(exec -T worker)
else
  runner=(run --rm --no-deps -T worker)
fi

echo "Applying the c_compute migration with worker mode=$mode..."

# The DSN is assembled and consumed inside Python, so the password never reaches
# this shell, its history, or the process list on the host.
compose "${runner[@]}" sh -c '
  set -e
  for name in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT POSTGRES_DB; do
    eval "value=\$$name"
    if [ -z "$value" ]; then
      echo "$name is not set in the worker container" >&2
      exit 1
    fi
  done
  python -m worker.migrate --from-postgres-env
'

echo "Done. Confirm with: ./Infra/scripts/verify-deployment.sh"
