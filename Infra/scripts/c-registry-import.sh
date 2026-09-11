#!/usr/bin/env bash

# Explicitly imports and activates the approved C Registry snapshot. This is a
# one-time/release-time operation, not a container startup seed: the immutable
# snapshot and its source revision must remain visible in the operator log.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=data"

snapshot_path="${C_REGISTRY_SNAPSHOT_PATH:-/app/registry/data/technology_registry_20260911_1.json}"
source_ref="${C_REGISTRY_SOURCE_REF:-AI/registry/data/technology_registry_20260911_1.json}"
repository_root="${C_REGISTRY_REPOSITORY_ROOT:-/opt/gitjob-provenance}"

container_id="$(compose ps -q worker | head -n 1)"
[[ -n "$container_id" ]] || die "worker container is not running for the selected profiles"

echo "Importing and activating the approved C Registry snapshot..."
compose exec -T \
  -e C_REGISTRY_IMPORT_PATH="$snapshot_path" \
  -e C_REGISTRY_IMPORT_SOURCE_REF="$source_ref" \
  -e C_REGISTRY_IMPORT_REPOSITORY_ROOT="$repository_root" \
  worker python - <<'PY'
import os

from psycopg.conninfo import make_conninfo

from registry.db import main

required = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("missing worker database settings: " + ", ".join(missing))

dsn = make_conninfo(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ["POSTGRES_PORT"],
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
)
raise SystemExit(
    main(
        [
            "import",
            "--dsn",
            dsn,
            "--path",
            os.environ["C_REGISTRY_IMPORT_PATH"],
            "--repository-root",
            os.environ["C_REGISTRY_IMPORT_REPOSITORY_ROOT"],
            "--source-ref",
            os.environ["C_REGISTRY_IMPORT_SOURCE_REF"],
            "--activate-alias",
        ]
    )
)
PY

echo "Registry import and alias activation completed. Restarting worker..."
compose restart worker

echo "Done. Run verify-deployment.sh after all release migrations are applied."
