#!/usr/bin/env bash

# Explicitly imports the approved C Registry and executable Rule Pack, then
# activates their shared Registry version. This is a one-time/release-time
# operation, not a container startup seed: immutable content and provenance
# remain visible in the operator log.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=data"

snapshot_path="${C_REGISTRY_SNAPSHOT_PATH:-/app/registry/data/technology_registry_20260911_4.json}"
rule_pack_path="${C_RULE_PACK_SNAPSHOT_PATH:-/app/analysis/data/rule_pack_20260911_4.json}"
registry_source_ref="${C_REGISTRY_SOURCE_REF:-AI/registry/data/technology_registry_20260911_4.json}"
rule_pack_source_ref="${C_RULE_PACK_SOURCE_REF:-AI/analysis/data/rule_pack_20260911_4.json}"
repository_root="${C_REGISTRY_REPOSITORY_ROOT:-/opt/gitjob-provenance}"

container_id="$(compose ps -q worker | head -n 1)"
[[ -n "$container_id" ]] || die "worker container is not running for the selected profiles"

echo "Importing the approved C Registry and Rule Pack..."
compose exec -T \
  -e C_REGISTRY_IMPORT_PATH="$snapshot_path" \
  -e C_RULE_PACK_IMPORT_PATH="$rule_pack_path" \
  -e C_REGISTRY_IMPORT_SOURCE_REF="$registry_source_ref" \
  -e C_RULE_PACK_IMPORT_SOURCE_REF="$rule_pack_source_ref" \
  -e C_REGISTRY_IMPORT_REPOSITORY_ROOT="$repository_root" \
  worker python - <<'PY'
import os
from pathlib import Path

from psycopg.conninfo import make_conninfo

from registry.contracts import load_registry
from registry.db import (
    ImmutableRegistryConflict,
    PostgresRegistryStore,
    RegistryVersionUnavailable,
    registry_content_sha256,
)
from registry.rulepack_db import PostgresRulePackStore

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
registry = load_registry(
    Path(os.environ["C_REGISTRY_IMPORT_PATH"]),
    repository_root=Path(os.environ["C_REGISTRY_IMPORT_REPOSITORY_ROOT"]),
)
registry_store = PostgresRegistryStore(dsn)
try:
    existing = registry_store.resolve_version(registry.registry_version)
except RegistryVersionUnavailable:
    registry_source_ref = os.environ["C_REGISTRY_IMPORT_SOURCE_REF"]
else:
    if existing.content_sha256 != registry_content_sha256(registry):
        raise ImmutableRegistryConflict(
            "existing Registry version names different immutable content"
        )
    # Preserve the original provenance of an already published Registry. The
    # Rule Pack has its own immutable source reference below.
    registry_source_ref = existing.source_ref
published = PostgresRulePackStore(dsn).import_pack(
    registry,
    Path(os.environ["C_RULE_PACK_IMPORT_PATH"]),
    source_ref=os.environ["C_RULE_PACK_IMPORT_SOURCE_REF"],
    registry_source_ref=registry_source_ref,
)
active = registry_store.activate_alias(published.registry_version)
print(
    "activated Registry and Rule Pack",
    active.registry_version,
    published.rule_pack_version,
)
PY

echo "Registry and Rule Pack activation completed. Restarting worker..."
compose restart worker

echo "Done. Run verify-deployment.sh after all release migrations are applied."
