#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.ci}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi

die() {
  echo "error: $*" >&2
  exit 1
}

[[ -f "$ENV_FILE" ]] || die "CI environment file is missing: $ENV_FILE"

env_value() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

require_value() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "$name must be set in $ENV_FILE"
}

valid_host() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

valid_user() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9._-]*$ ]]
}

valid_path() {
  [[ "$1" == /* && "$1" != *[[:space:]]* ]]
}

valid_env_file() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

valid_deploy_ref() {
  local ref="$1"
  [[ "$ref" != -* && "$ref" != */ && "$ref" != *..* && "$ref" != *'@{'* ]] || return 1
  [[ "$ref" =~ ^[A-Za-z0-9._/-]+$ ]] || return 1
  git check-ref-format --branch "$ref" >/dev/null 2>&1
}

quote_for_remote() {
  printf '%q' "$1"
}

compose_command() {
  local deploy_path="$1"
  local env_file_name="$2"
  local override_file="$3"
  local -a command=(
    docker compose
    --project-directory "$deploy_path"
    --env-file "$deploy_path/$env_file_name"
    -f "$deploy_path/Infra/compose/compose.yaml"
    -f "$deploy_path/Infra/compose/$override_file"
  )
  printf '%q ' "${command[@]}"
}

ssh_key="${EC2_SSH_KEY:-}"
require_value EC2_SSH_KEY "$ssh_key"
[[ -r "$ssh_key" ]] || die "EC2_SSH_KEY is not readable"

ssh_port="${EC2_SSH_PORT:-$(env_value EC2_SSH_PORT)}"
ssh_port="${ssh_port:-22}"
[[ "$ssh_port" =~ ^[0-9]+$ && "$ssh_port" -ge 1 && "$ssh_port" -le 65535 ]] || die "EC2_SSH_PORT is invalid"

deployment_mode="${DEPLOYMENT_MODE:-$(env_value DEPLOYMENT_MODE)}"
[[ "$deployment_mode" == split ]] || die "DEPLOYMENT_MODE=split is required"

deploy_ref="${EC2_DEPLOY_REF:-$(env_value EC2_DEPLOY_REF)}"
deploy_ref="${deploy_ref:-develop}"
valid_deploy_ref "$deploy_ref" || die "EC2_DEPLOY_REF is not a valid local branch name: $deploy_ref"

service_host="${EC2_SERVICE_HOST:-$(env_value EC2_SERVICE_HOST)}"
service_user="${EC2_SERVICE_USER:-$(env_value EC2_SERVICE_USER)}"
service_path="${EC2_SERVICE_PATH:-$(env_value EC2_SERVICE_PATH)}"
service_env_file="${EC2_SERVICE_ENV_FILE:-$(env_value EC2_SERVICE_ENV_FILE)}"
data_host="${EC2_DATA_HOST:-$(env_value EC2_DATA_HOST)}"
data_user="${EC2_DATA_USER:-$(env_value EC2_DATA_USER)}"
data_path="${EC2_DATA_PATH:-$(env_value EC2_DATA_PATH)}"
data_env_file="${EC2_DATA_ENV_FILE:-$(env_value EC2_DATA_ENV_FILE)}"

ssh_user="${EC2_SSH_USER:-$(env_value EC2_DEPLOY_USER)}"
service_user="${service_user:-$ssh_user}"
data_user="${data_user:-$ssh_user}"
service_path="${service_path:-/opt/gitjob}"
data_path="${data_path:-/opt/gitjob}"
service_env_file="${service_env_file:-.env.service}"
data_env_file="${data_env_file:-.env.data}"

for value in "$service_host" "$data_host"; do
  require_value EC2_HOST "$value"
  valid_host "$value" || die "EC2 host contains unsupported characters: $value"
done
for value in "$service_user" "$data_user"; do
  valid_user "$value" || die "EC2 user contains unsupported characters: $value"
done
for value in "$service_path" "$data_path"; do
  valid_path "$value" || die "EC2 deploy path must be absolute and contain no whitespace: $value"
done
for value in "$service_env_file" "$data_env_file"; do
  valid_env_file "$value" || die "remote env file must be a simple filename: $value"
done

local_backend_image="gitjob/backend:local"
local_frontend_image="gitjob/frontend:local"
local_collector_image="gitjob/collector:local"
local_worker_image="gitjob/worker:local"
local_spark_image="gitjob/spark:local"

ssh_options=(
  -i "$ssh_key"
  -p "$ssh_port"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
)

remote_exec() {
  local host="$1"
  local user="$2"
  local command="$3"
  ssh "${ssh_options[@]}" "$user@$host" "$command"
}

refresh_checkout() {
  local host="$1"
  local user="$2"
  local deploy_path="$3"
  local ref="$4"
  local quoted_path
  local quoted_ref
  local quoted_remote_ref
  local quoted_local_ref
  quoted_path="$(quote_for_remote "$deploy_path")"
  quoted_ref="$(quote_for_remote "$ref")"
  quoted_remote_ref="$(quote_for_remote "refs/remotes/origin/$ref")"
  quoted_local_ref="$(quote_for_remote "refs/heads/$ref")"

  echo "Updating ${user}@${host}:${deploy_path} to ${ref}..."
  remote_exec "$host" "$user" \
    "set -Eeuo pipefail
     test -d ${quoted_path}/.git
     test -z \"\$(git -C ${quoted_path} status --porcelain)\" || {
       echo 'remote checkout has uncommitted changes' >&2
       exit 1
     }
     git -C ${quoted_path} fetch --prune origin ${quoted_ref}
     if git -C ${quoted_path} show-ref --verify --quiet ${quoted_remote_ref}; then
       if git -C ${quoted_path} show-ref --verify --quiet ${quoted_local_ref}; then
         git -C ${quoted_path} switch ${quoted_ref}
       else
         git -C ${quoted_path} switch --create ${quoted_ref} --track origin/${quoted_ref}
       fi
       git -C ${quoted_path} pull --ff-only origin ${quoted_ref}
     else
       echo \"remote branch not found: ${ref}\" >&2
       exit 1
     fi
     git -C ${quoted_path} rev-parse --verify HEAD"
}

build_service_images() {
  local quoted_path
  local quoted_backend_image
  local quoted_frontend_image
  quoted_path="$(quote_for_remote "$service_path")"
  quoted_backend_image="$(quote_for_remote "$local_backend_image")"
  quoted_frontend_image="$(quote_for_remote "$local_frontend_image")"

  echo "Building service images on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd ${quoted_path}
     docker build --tag ${quoted_backend_image} --file Infra/docker/backend/Dockerfile .
     docker build --tag ${quoted_frontend_image} \\
       --build-arg VITE_API_BASE_URL=/api \\
       --build-arg VITE_WS_URL=/ws \\
       --file Infra/docker/frontend/Dockerfile ."
}

build_data_images() {
  local quoted_path
  local quoted_collector_image
  local quoted_worker_image
  local quoted_spark_image
  quoted_path="$(quote_for_remote "$data_path")"
  quoted_collector_image="$(quote_for_remote "$local_collector_image")"
  quoted_worker_image="$(quote_for_remote "$local_worker_image")"
  quoted_spark_image="$(quote_for_remote "$local_spark_image")"

  echo "Building data images on ${data_user}@${data_host}..."
  remote_exec "$data_host" "$data_user" \
    "set -Eeuo pipefail
     cd ${quoted_path}
     docker build --tag ${quoted_collector_image} --tag ${quoted_worker_image} \\
       --file Infra/docker/worker/Dockerfile .
     docker build --tag ${quoted_spark_image} \\
       --file Infra/docker/spark/Dockerfile ."
}

service_compose_environment() {
  printf '%q ' \
    "COMPOSE_PROFILES=$1" \
    "BACKEND_IMAGE=$local_backend_image" \
    "FRONTEND_IMAGE=$local_frontend_image"
}

data_compose_environment() {
  printf '%q ' \
    "COMPOSE_PROFILES=data" \
    "COLLECTOR_IMAGE=$local_collector_image" \
    "WORKER_IMAGE=$local_worker_image" \
    "SPARK_IMAGE=$local_spark_image"
}

start_service_core() {
  local compose
  local compose_environment
  compose="$(compose_command "$service_path" "$service_env_file" compose.ec2.yaml)"
  compose_environment="$(service_compose_environment core)"

  echo "Starting service core on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$service_path")
     test -f $(quote_for_remote "$service_env_file")
     ${compose_environment}${compose} --profile core config --quiet
     ${compose_environment}${compose} --profile core up -d
     ENV_FILE=$(quote_for_remote "$service_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2.yaml) PROFILES=core HEALTHCHECK_TIMEOUT_SECONDS=180 bash Infra/scripts/healthcheck.sh"
}

start_service_app() {
  local compose
  local compose_environment
  compose="$(compose_command "$service_path" "$service_env_file" compose.ec2.yaml)"
  compose_environment="$(service_compose_environment core,app)"

  echo "Starting service app on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$service_path")
     ${compose_environment}${compose} --profile core --profile app config --quiet
     ${compose_environment}${compose} --profile core --profile app up -d --no-build
     ENV_FILE=$(quote_for_remote "$service_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2.yaml) PROFILES=core,app HEALTHCHECK_TIMEOUT_SECONDS=240 bash Infra/scripts/healthcheck.sh"
}

start_data_app() {
  local compose
  local compose_environment
  compose="$(compose_command "$data_path" "$data_env_file" compose.ec2-data.yaml)"
  compose_environment="$(data_compose_environment)"

  echo "Starting data app on ${data_user}@${data_host}..."
  remote_exec "$data_host" "$data_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$data_path")
     test -f $(quote_for_remote "$data_env_file")
     ${compose_environment}${compose} --profile data config --quiet
     ${compose_environment}${compose} --profile data up -d --no-build
     ENV_FILE=$(quote_for_remote "$data_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2-data.yaml) PROFILES=data HEALTHCHECK_TIMEOUT_SECONDS=300 bash Infra/scripts/healthcheck.sh"
}

refresh_checkout "$service_host" "$service_user" "$service_path" "$deploy_ref"
start_service_core
build_service_images
start_service_app

refresh_checkout "$data_host" "$data_user" "$data_path" "$deploy_ref"
build_data_images
start_data_app

echo "Split source-pull/build deployment completed for ${deploy_ref}."
