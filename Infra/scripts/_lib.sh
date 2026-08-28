#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$INFRA_DIR/.." && pwd)"
COMPOSE_DIR="$INFRA_DIR/compose"

ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.wsl}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi

COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-$COMPOSE_DIR/compose.wsl.yaml}"
if [[ "$COMPOSE_OVERRIDE_FILE" != /* ]]; then
  COMPOSE_OVERRIDE_FILE="$REPO_ROOT/$COMPOSE_OVERRIDE_FILE"
fi

# Scripts default to core. Select additional profiles without editing the
# scripts, for example: PROFILES=core,app,data ./Infra/scripts/up.sh. When the
# caller has not set PROFILES, honor COMPOSE_PROFILES from the selected env file
# as well as from the shell environment.
if [[ -n "${PROFILES:-}" ]]; then
  PROFILE_SET="$PROFILES"
elif [[ -n "${COMPOSE_PROFILES:-}" ]]; then
  PROFILE_SET="$COMPOSE_PROFILES"
elif [[ -f "$ENV_FILE" ]]; then
  PROFILE_SET="$(sed -n 's/^[[:space:]]*COMPOSE_PROFILES[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" | tail -n 1)"
  [[ -n "$PROFILE_SET" ]] || PROFILE_SET=core
else
  PROFILE_SET=core
fi

profile_enabled() {
  local wanted="$1"
  local profile
  local -a profiles

  IFS=',' read -r -a profiles <<< "$PROFILE_SET"
  for profile in "${profiles[@]}"; do
    [[ "$profile" == "$wanted" ]] && return 0
  done
  return 1
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed or is not on PATH"
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable; start Docker Desktop/Engine first"
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found; run ./Infra/scripts/init-wsl.sh first"
}

compose() {
  local -a profile_args=()
  local profile
  local -a profiles

  IFS=',' read -r -a profiles <<< "$PROFILE_SET"
  for profile in "${profiles[@]}"; do
    [[ -n "$profile" ]] || continue
    profile_args+=(--profile "$profile")
  done

  docker compose \
    --project-directory "$REPO_ROOT" \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_DIR/compose.yaml" \
    -f "$COMPOSE_OVERRIDE_FILE" \
    "${profile_args[@]}" \
    "$@"
}

service_container_id() {
  local service="$1"
  compose ps -q "$service" | head -n 1
}

require_core_tools() {
  require_docker
  require_env_file
  [[ -f "$COMPOSE_DIR/compose.yaml" ]] || die "shared Compose file is missing"
  [[ -f "$COMPOSE_OVERRIDE_FILE" ]] || die "Compose override is missing: $COMPOSE_OVERRIDE_FILE"
}
