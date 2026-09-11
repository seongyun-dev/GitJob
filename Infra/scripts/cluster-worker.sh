#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.service}"
COMPOSE_FILE="$REPO_ROOT/Infra/compose/compose.ec2-cluster-worker.yaml"
[[ "$ENV_FILE" == /* ]] || ENV_FILE="$REPO_ROOT/$ENV_FILE"
[[ -f "$ENV_FILE" ]] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

# Profiles: shell override, then the env file (which .env.example documents),
# then the fail-safe default. Reading the env file here matches how the project
# name below is resolved, so `down`/`health` act on the same service set that
# `up` created. The default stays hdfs-worker so an option-less invocation may
# add storage but never enrolls Spark Worker-2 before its own phase gate.
if [[ -z "${CLUSTER_WORKER_PROFILES:-}" ]]; then
  CLUSTER_WORKER_PROFILES="$(
    sed -n 's/^[[:space:]]*CLUSTER_WORKER_PROFILES[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" | tail -n 1
  )"
fi
CLUSTER_WORKER_PROFILES="${CLUSTER_WORKER_PROFILES:-hdfs-worker}"

# COMPOSE_PROJECT_NAME in .env.service belongs to the existing core/app stack
# and takes precedence over the Compose file's top-level name. Force a separate
# project explicitly so this command can never adopt those containers.
if [[ -z "${CLUSTER_WORKER_PROJECT_NAME:-}" ]]; then
  CLUSTER_WORKER_PROJECT_NAME="$(
    sed -n 's/^[[:space:]]*CLUSTER_WORKER_PROJECT_NAME[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" | tail -n 1
  )"
fi
CLUSTER_WORKER_PROJECT_NAME="${CLUSTER_WORKER_PROJECT_NAME:-gitjob-cluster-worker}"
[[ "$CLUSTER_WORKER_PROJECT_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || {
  echo "invalid CLUSTER_WORKER_PROJECT_NAME: $CLUSTER_WORKER_PROJECT_NAME" >&2
  exit 1
}

profile_args=()
IFS=',' read -r -a profiles <<< "$CLUSTER_WORKER_PROFILES"
for profile in "${profiles[@]}"; do
  [[ -n "$profile" ]] && profile_args+=(--profile "$profile")
done

compose=(
  docker compose
  --project-directory "$REPO_ROOT"
  --project-name "$CLUSTER_WORKER_PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f "$COMPOSE_FILE"
  "${profile_args[@]}"
)
action="${1:-config}"

case "$action" in
  config)
    "${compose[@]}" config --quiet
    ;;
  up)
    "${compose[@]}" config --quiet
    "${compose[@]}" up -d --build
    ;;
  health)
    "${compose[@]}" ps
    services=()
    [[ ",$CLUSTER_WORKER_PROFILES," == *,hdfs-worker,* ]] && services+=(hdfs-datanode4)
    [[ ",$CLUSTER_WORKER_PROFILES," == *,spark-worker,* ]] && services+=(spark-worker2)
    for service in "${services[@]}"; do
      id="$("${compose[@]}" ps -q "$service")"
      [[ -n "$id" ]] || { echo "$service is not running" >&2; exit 1; }
      state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")"
      [[ "$state" == "running healthy" ]] || { echo "$service: $state" >&2; exit 1; }
    done
    ;;
  down)
    "${compose[@]}" down
    ;;
  *)
    echo "usage: $0 {config|up|health|down}" >&2
    exit 2
    ;;
esac
