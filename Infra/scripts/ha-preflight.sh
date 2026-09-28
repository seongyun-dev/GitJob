#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

[[ "$COMPOSE_OVERRIDE_FILE" == *"compose.ec2-ha.yaml" ]] || \
  die "HA preflight requires COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml"
profile_enabled app || die "HA app nodes must include the app profile"

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

require_value() {
  local key="$1"
  local value
  value="$(env_value "$key")"
  [[ -n "$value" ]] || die "$key must be set in $ENV_FILE"
}

[[ "$(env_value DEPLOYMENT_MODE)" == "ha" ]] || \
  die "DEPLOYMENT_MODE=ha is required in $ENV_FILE"

node_name="$(env_value EC2_NODE_NAME)"
case "$node_name" in
  node-a|node-b) ;;
  *) die "EC2_NODE_NAME must be node-a or node-b" ;;
esac

require_value DB_HOST
require_value REDIS_HOST
require_value KAFKA_BOOTSTRAP_SERVERS
require_value ALB_HEALTHCHECK_URL

for key in DB_HOST REDIS_HOST KAFKA_BOOTSTRAP_SERVERS; do
  value="$(env_value "$key")"
  case "$value" in
    postgres|redis|kafka|localhost|127.*|*://localhost*|*://127.*|*kafka:9092*)
      die "$key still points to a local Compose service ($value)"
      ;;
  esac
done

compose config --quiet
echo "HA preflight passed for ${node_name}. Compose config is valid and local core endpoints are not selected."
