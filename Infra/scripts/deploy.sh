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
  shift 2
  local override_file
  local -a command=(
    docker compose
    --project-directory "$deploy_path"
    --env-file "$deploy_path/$env_file_name"
    -f "$deploy_path/Infra/compose/compose.yaml"
  )
  for override_file in "$@"; do
    command+=(-f "$deploy_path/Infra/compose/$override_file")
  done
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
service_path="${service_path:-/home/ubuntu/workspace/S15P21E102}"
data_path="${data_path:-/home/ubuntu/workspace/S15P21E102}"
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

# Compose treats ${VAR:?...} as mandatory and interpolates the whole file
# before profile filtering, so a variable used by any service breaks validation
# on every host regardless of the profiles selected. Collect those names from
# the compose files this deployment will actually use, taken from the Jenkins
# workspace at the commit being deployed.
required_compose_vars() {
  local override_file
  local -a compose_files=("$REPO_ROOT/Infra/compose/compose.yaml")
  for override_file in "$@"; do
    compose_files+=("$REPO_ROOT/Infra/compose/$override_file")
  done
  grep -hv '^[[:space:]]*#' \
    "${compose_files[@]}" \
    | grep -ohE '\$\{[A-Za-z_][A-Za-z0-9_]*:\?' \
    | sed -E 's/^\$\{//; s/:\?$//' \
    | sort -u
}

# Verify a host's remote env file before anything is pulled or started. Without
# this, the first `compose config` failure lands after refresh_checkout has
# already moved the checkout forward, leaving the host on a new commit while its
# containers still run the previous build.
preflight_remote_env() {
  local host="$1"
  local user="$2"
  local deploy_path="$3"
  local env_file_name="$4"
  shift 4
  local -a override_files=("$@")
  local -a required=()
  local key
  local keys_arg=""
  local quoted_env

  mapfile -t required < <(required_compose_vars "${override_files[@]}")
  if [[ ${#required[@]} -eq 0 ]]; then
    die "no required Compose variables found; expected at least one in ${override_files[*]}"
  fi
  for key in "${required[@]}"; do
    keys_arg+=" $(quote_for_remote "$key")"
  done
  quoted_env="$(quote_for_remote "$deploy_path/$env_file_name")"

  echo "Preflight: ${#required[@]} required keys in ${user}@${host}:${env_file_name}..."
  remote_exec "$host" "$user" \
    "set -Eeuo pipefail
     env_path=${quoted_env}
     test -f \"\$env_path\" || {
       echo \"remote env file is missing: \$env_path\" >&2
       exit 1
     }
     missing=
     for key in${keys_arg}; do
       grep -qE \"^[[:space:]]*\${key}[[:space:]]*=[[:space:]]*[^[:space:]]\" \"\$env_path\" \
         || missing=\"\$missing \$key\"
     done
     if [ -n \"\$missing\" ]; then
       echo \"remote env file \$env_path is missing required keys:\$missing\" >&2
       exit 1
     fi
     echo 'Preflight OK'"
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
  local quoted_worker_image
  quoted_path="$(quote_for_remote "$service_path")"
  quoted_backend_image="$(quote_for_remote "$local_backend_image")"
  quoted_frontend_image="$(quote_for_remote "$local_frontend_image")"
  quoted_worker_image="$(quote_for_remote "$local_worker_image")"

  echo "Building service images on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd ${quoted_path}
     docker build --tag ${quoted_backend_image} --file Infra/docker/backend/Dockerfile .
     docker build --tag ${quoted_frontend_image} \\
       --build-arg VITE_API_BASE_URL=/api \\
       --build-arg VITE_WS_URL=/ws \\
       --file Infra/docker/frontend/Dockerfile .
     docker build --tag ${quoted_worker_image} \\
       --file Infra/docker/worker/Dockerfile ."
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
     docker build --tag ${quoted_worker_image} \\
       --file Infra/docker/worker/Dockerfile .
     docker build --tag ${quoted_collector_image} \\
       --build-arg JOBKOREA_OCR_ENABLED=true \\
       --file Infra/docker/worker/Dockerfile .
     docker build --tag ${quoted_spark_image} \\
       --file Infra/docker/spark/Dockerfile ."
}

service_compose_environment() {
  printf '%q ' \
    "COMPOSE_PROFILES=$1" \
    "BACKEND_IMAGE=$local_backend_image" \
    "FRONTEND_IMAGE=$local_frontend_image" \
    "WORKER_IMAGE=$local_worker_image"
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

prepare_repository_analysis_schema() {
  echo "Preparing repository analysis schema on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$service_path")
     ENV_FILE=$(quote_for_remote "$service_env_file") \
       COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2.yaml) \
       PROFILES=core bash Infra/scripts/repo-analysis-migrate.sh"
}

prepare_kafka_topics() {
  echo "Preparing Kafka topics on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$service_path")
     ENV_FILE=$(quote_for_remote "$service_env_file") \
       COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2.yaml) \
       PROFILES=core bash Infra/scripts/kafka-topics.sh"
}

# nginx is recreated explicitly at the end. Two separate reasons make a plain
# `up -d` insufficient, and both were found the hard way on 2026-09-09.
#
# Its configuration is bind-mounted file by file, and a single-file bind mount pins
# that file's inode. git replaces the file on checkout, so the running container
# keeps reading the version it started with: a deploy could change nginx
# configuration and have no effect at all.
#
# And nginx reads its configuration only at start, so even once the new file is
# visible it is not in use until the process restarts.
#
# The configuration is validated in a throwaway container first. `nginx -t` inside
# the running container would test the stale file, and restarting into a broken
# config would leave the entry point down with no previous container to fall back to.
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
     ${compose_environment}${compose} --profile core --profile app run --rm --no-deps --entrypoint nginx nginx -t
     ${compose_environment}${compose} --profile core --profile app up -d --no-deps --force-recreate --no-build nginx
     ENV_FILE=$(quote_for_remote "$service_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2.yaml) PROFILES=core,app HEALTHCHECK_TIMEOUT_SECONDS=240 bash Infra/scripts/healthcheck.sh"
}

start_service_weekly_consumer() {
  local compose
  local compose_environment
  compose="$(compose_command "$service_path" "$service_env_file" \
    compose.ec2.yaml compose.weekly-host.yaml)"
  compose_environment="$(service_compose_environment weekly)"

  echo "Starting weekly Trend consumer on ${service_user}@${service_host}..."
  remote_exec "$service_host" "$service_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$service_path")
     ${compose_environment}${compose} --profile weekly config --quiet
     ${compose_environment}${compose} --profile weekly up -d --no-deps --force-recreate --no-build weekly-trend-consumer
     ENV_FILE=$(quote_for_remote "$service_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.weekly-host.yaml) PROFILES=weekly HEALTHCHECK_TIMEOUT_SECONDS=120 bash Infra/scripts/healthcheck.sh"
}

remove_legacy_data_weekly_consumer() {
  local compose
  local compose_environment
  compose="$(compose_command "$data_path" "$data_env_file" compose.ec2-data-cluster.yaml)"
  compose_environment="$(data_compose_environment)"

  echo "Removing legacy weekly Trend consumer from ${data_user}@${data_host}..."
  remote_exec "$data_host" "$data_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$data_path")
     ${compose_environment}${compose} --profile weekly rm --stop --force weekly-trend-consumer"
}

start_data_app() {
  local compose
  local compose_environment
  compose="$(compose_command "$data_path" "$data_env_file" compose.ec2-data-cluster.yaml)"
  compose_environment="$(data_compose_environment)"

  echo "Starting data app on ${data_user}@${data_host}..."
  remote_exec "$data_host" "$data_user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$data_path")
     test -f $(quote_for_remote "$data_env_file")
     ${compose_environment}${compose} --profile data config --quiet
     ${compose_environment}${compose} --profile data up -d --no-build
     ENV_FILE=$(quote_for_remote "$data_env_file") COMPOSE_OVERRIDE_FILE=$(quote_for_remote Infra/compose/compose.ec2-data-cluster.yaml) PROFILES=data HEALTHCHECK_TIMEOUT_SECONDS=300 bash Infra/scripts/healthcheck.sh"
}

# Both hosts are checked before either is modified, so one run reports every
# missing key instead of stopping at the first host.
preflight_failures=0
preflight_remote_env "$service_host" "$service_user" "$service_path" \
  "$service_env_file" compose.ec2.yaml compose.weekly-host.yaml \
  || preflight_failures=$((preflight_failures + 1))
preflight_remote_env "$data_host" "$data_user" "$data_path" \
  "$data_env_file" compose.ec2-data-cluster.yaml || preflight_failures=$((preflight_failures + 1))
[[ "$preflight_failures" -eq 0 ]] \
  || die "preflight failed on $preflight_failures host(s); no host was modified"

# healthcheck.sh above only asks whether containers are up. It cannot see that a
# database has no schema, that the Debezium connector was never registered, or that
# a worker has no c_compute tables — all of which have shipped as a green deploy.
# This runs after BOTH hosts are deployed: stopping at the first failure would leave
# the data host untouched, and the operator needs to see the state of both.
verify_deployment() {
  local host="$1"
  local user="$2"
  local deploy_path="$3"
  local env_file_name="$4"
  local override_file="$5"
  local profiles="$6"

  echo "Verifying readiness on ${user}@${host}..."
  remote_exec "$host" "$user" \
    "set -Eeuo pipefail
     cd $(quote_for_remote "$deploy_path")
     ENV_FILE=$(quote_for_remote "$env_file_name") \
       COMPOSE_OVERRIDE_FILE=$(quote_for_remote "Infra/compose/$override_file") \
       PROFILES=${profiles} VERIFY_TIMEOUT_SECONDS=120 \
       bash Infra/scripts/verify-deployment.sh"
}

refresh_checkout "$service_host" "$service_user" "$service_path" "$deploy_ref"
start_service_core
prepare_kafka_topics
prepare_repository_analysis_schema
build_service_images
start_service_app
start_service_weekly_consumer

refresh_checkout "$data_host" "$data_user" "$data_path" "$deploy_ref"
remove_legacy_data_weekly_consumer
build_data_images
start_data_app

echo "Split source-pull/build deployment completed for ${deploy_ref}."

verify_failures=0
verify_deployment "$service_host" "$service_user" "$service_path" \
  "$service_env_file" compose.ec2.yaml core,app || verify_failures=$((verify_failures + 1))
verify_deployment "$service_host" "$service_user" "$service_path" \
  "$service_env_file" compose.weekly-host.yaml weekly || verify_failures=$((verify_failures + 1))
verify_deployment "$data_host" "$data_user" "$data_path" \
  "$data_env_file" compose.ec2-data-cluster.yaml data || verify_failures=$((verify_failures + 1))
[[ "$verify_failures" -eq 0 ]] \
  || die "deployment finished but ${verify_failures} host(s) are not ready; the checks above name the missing step"

echo "Both hosts verified ready."
