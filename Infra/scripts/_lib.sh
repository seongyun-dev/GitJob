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

# Build the network-related spark-submit arguments in one place. The defaults
# retain the current single-host behavior. Phase 8 activates the fixed
# Tailscale addresses and ports through the environment without rewriting each
# job wrapper independently.
spark_submit_network_args() {
  local driver_host
  local bind_address
  local driver_port
  local driver_block_manager_port
  local executor_block_manager_port
  local port_max_retries
  local executor_cores
  local cores_max

  spark_setting() {
    local key="$1"
    local fallback="${2:-}"
    local value="${!key:-}"
    if [[ -z "$value" && -f "$ENV_FILE" ]]; then
      value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1)"
    fi
    printf '%s' "${value:-$fallback}"
  }

  # When the two-host topology is configured (DATA_TS_IP set) the driver must
  # advertise and bind the data host's Tailscale address, or executors on the
  # service host cannot reach it. Derive that default from the topology so an
  # operator sets one variable; explicit SPARK_DRIVER_* still wins.
  local topology_ip
  topology_ip="$(spark_setting DATA_TS_IP)"
  driver_host="$(spark_setting SPARK_DRIVER_HOST "${topology_ip:-spark-worker}")"
  bind_address="$(spark_setting SPARK_DRIVER_BIND_ADDRESS "${topology_ip:-0.0.0.0}")"
  driver_port="$(spark_setting SPARK_DRIVER_PORT)"
  driver_block_manager_port="$(spark_setting SPARK_DRIVER_BLOCK_MANAGER_PORT)"
  executor_block_manager_port="$(spark_setting SPARK_EXECUTOR_BLOCK_MANAGER_PORT)"
  port_max_retries="$(spark_setting SPARK_PORT_MAX_RETRIES)"
  executor_cores="$(spark_setting SPARK_EXECUTOR_CORES)"
  cores_max="$(spark_setting SPARK_CORES_MAX)"

  SPARK_NETWORK_ARGS=(
    --conf "spark.driver.bindAddress=${bind_address}"
    --conf "spark.driver.host=${driver_host}"
    --conf "spark.hadoop.dfs.client.use.datanode.hostname=true"
  )
  [[ -n "$driver_port" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.driver.port=${driver_port}")
  [[ -n "$driver_block_manager_port" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.driver.blockManager.port=${driver_block_manager_port}")
  [[ -n "$executor_block_manager_port" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.blockManager.port=${executor_block_manager_port}")
  [[ -n "$port_max_retries" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.port.maxRetries=${port_max_retries}")
  [[ -n "$executor_cores" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.executor.cores=${executor_cores}")
  [[ -n "$cores_max" ]] \
    && SPARK_NETWORK_ARGS+=(--conf "spark.cores.max=${cores_max}")
  return 0
}

# Storage-side spark-submit arguments, kept separate from the network ones so a
# replication change is not buried in address/port handling.
#
# dfs.replication is a client-side decision: the NameNode's value applies only to
# clients that ask for it. The Spark image ships no hdfs-site.xml, so without
# this the client falls back to Hadoop's built-in default of 3. With one
# DataNode on /rack-b the placement policy cannot satisfy 3 replicas, and every
# Spark write stays permanently under-replicated (S15P21E102-207 Phase 6/8).
#
# 2 is the value the two-rack topology can actually satisfy: HDFS places one
# replica per rack, so each block lands on both EC2 hosts.
spark_submit_storage_args() {
  local replication

  replication="${SPARK_HDFS_REPLICATION:-}"
  if [[ -z "$replication" && -f "$ENV_FILE" ]]; then
    replication="$(
      sed -n 's/^[[:space:]]*SPARK_HDFS_REPLICATION[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" \
        | tail -n 1
    )"
  fi
  replication="${replication:-2}"
  [[ "$replication" =~ ^[1-9][0-9]*$ ]] \
    || die "SPARK_HDFS_REPLICATION must be a positive integer: $replication"

  SPARK_STORAGE_ARGS=(
    --conf "spark.hadoop.dfs.replication=${replication}"
  )
  return 0
}

require_core_tools() {
  require_docker
  require_env_file
  [[ -f "$COMPOSE_DIR/compose.yaml" ]] || die "shared Compose file is missing"
  [[ -f "$COMPOSE_OVERRIDE_FILE" ]] || die "Compose override is missing: $COMPOSE_OVERRIDE_FILE"
}
