#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

env_value() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

if ! profile_enabled ci; then
  PROFILE_SET="${PROFILE_SET},ci"
fi

controller_url="${JENKINS_BOOTSTRAP_URL:-$(env_value JENKINS_URL)}"
controller_url="${controller_url:-http://127.0.0.1:${JENKINS_HTTP_PORT:-8081}}"
controller_url="${controller_url%/}"
admin_id="${JENKINS_ADMIN_ID:-$(env_value JENKINS_ADMIN_ID)}"
admin_password="${JENKINS_ADMIN_PASSWORD:-$(env_value JENKINS_ADMIN_PASSWORD)}"
node_name="${JENKINS_AGENT_NAME:-$(env_value JENKINS_AGENT_NAME)}"
node_name="${node_name:-docker-agent}"

[[ -n "$admin_id" ]] || die "JENKINS_ADMIN_ID is required to bootstrap the inbound agent"
[[ -n "$admin_password" ]] || die "JENKINS_ADMIN_PASSWORD is required to bootstrap the inbound agent"

echo "Starting Jenkins controller before resolving the ${node_name} agent secret..."
compose up -d jenkins

auth_file="$(mktemp)"
trap 'rm -f "$auth_file"' EXIT
chmod 600 "$auth_file"
printf 'user = "%s:%s"\n' "$admin_id" "$admin_password" > "$auth_file"

controller_ready=false
for _ in $(seq 1 "${JENKINS_BOOTSTRAP_ATTEMPTS:-60}"); do
  if curl --config "$auth_file" --fail --silent --show-error \
    "$controller_url/login" >/dev/null 2>&1; then
    controller_ready=true
    break
  fi
  sleep "${JENKINS_BOOTSTRAP_INTERVAL_SECONDS:-2}"
done
[[ "$controller_ready" == true ]] || die "Jenkins controller did not become ready: $controller_url"

encoded_node_name="${node_name// /%20}"
jnlp_xml="$(curl --config "$auth_file" --fail --silent --show-error \
  "$controller_url/computer/${encoded_node_name}/jenkins-agent.jnlp")"
agent_secret="$(printf '%s' "$jnlp_xml" \
  | sed 's#<argument>#\n<argument>#g' \
  | sed -n 's:.*<argument>\([^<]*\)</argument>.*:\1:p' \
  | head -n 1)"
[[ -n "$agent_secret" ]] || die "Jenkins did not return a secret for node ${node_name}"

safe_node_name="${node_name//[^a-zA-Z0-9_.-]/_}"
secret_dir="${JENKINS_AGENT_SECRET_DIR:-$REPO_ROOT/.local/jenkins}"
secret_file="$secret_dir/${safe_node_name}.secret"
install -d -m 700 "$secret_dir"
printf '%s\n' "$agent_secret" > "$secret_file"
chmod 600 "$secret_file"

# Compose mounts the ignored 0600 file into the agent. The secret is therefore
# not placed in the agent container's Config.Env (and is never put in
# .env.example or the build log).
export JENKINS_AGENT_SECRET_FILE="$secret_file"
compose up -d --force-recreate jenkins-agent

agent_online=false
for _ in $(seq 1 "${JENKINS_AGENT_ONLINE_ATTEMPTS:-60}"); do
  node_json="$(curl --config "$auth_file" --fail --silent --show-error \
    "$controller_url/computer/${encoded_node_name}/api/json" 2>/dev/null || true)"
  if [[ "$node_json" == *'"offline":false'* && "$node_json" != *'"temporarilyOffline":true'* ]]; then
    agent_online=true
    break
  fi
  sleep "${JENKINS_BOOTSTRAP_INTERVAL_SECONDS:-2}"
done
[[ "$agent_online" == true ]] || die "Jenkins agent ${node_name} did not become online"

echo "Jenkins agent ${node_name} is online. Secret stored at ${secret_file}."
