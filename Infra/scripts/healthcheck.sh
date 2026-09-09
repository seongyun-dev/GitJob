#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

services=()
if profile_enabled core; then
  services+=(postgres redis kafka kafka-connect)
fi
if profile_enabled app; then
  services+=(backend frontend nginx)
fi
if profile_enabled data; then
  # The data profile expects all three logical DataNodes. During a rollout,
  # check the existing NameNode/DataNode-1 first, run the targeted DN2/DN3
  # up command, and invoke this full check only after both new nodes are up.
  services+=(hdfs-namenode hdfs-datanode hdfs-datanode2 hdfs-datanode3 spark-master spark-worker worker collector)
fi
if profile_enabled ci; then
  services+=(jenkins)
fi
if profile_enabled observability; then
  services+=(kafka-ui redis-insight)
fi
timeout_seconds="${HEALTHCHECK_TIMEOUT_SECONDS:-120}"
deadline=$((SECONDS + timeout_seconds))

while (( SECONDS < deadline )); do
  all_healthy=true
  for service in "${services[@]}"; do
    container_id="$(service_container_id "$service")"
    if [[ -z "$container_id" ]]; then
      printf '%-14s not running\n' "$service"
      all_healthy=false
      continue
    fi

    status="$(docker inspect --format '{{.State.Status}}' "$container_id")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container_id")"
    printf '%-14s %-10s %s\n' "$service" "$status" "$health"

    if [[ "$status" == "exited" || "$status" == "dead" || "$health" == "unhealthy" ]]; then
      printf '\n%s logs:\n' "$service" >&2
      compose logs --tail=80 "$service" >&2 || true
      exit 1
    fi
    [[ "$health" == "healthy" ]] || all_healthy=false
  done

  if [[ "$all_healthy" == true ]]; then
    echo "All selected services are healthy."
    exit 0
  fi
  sleep 2
done

echo "Timed out after ${timeout_seconds}s waiting for core services." >&2
compose ps >&2 || true
exit 1
