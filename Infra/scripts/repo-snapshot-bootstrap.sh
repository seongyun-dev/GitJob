#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=data"

env_value() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

snapshot_id="${REPO_SNAPSHOT_ID:-}"
pipeline_run_id="${REPO_PIPELINE_RUN_ID:-}"
candidate_file="${REPO_FETCH_CANDIDATES_OUTPUT:-$REPO_ROOT/.local/repo-fetch-benchmark/candidates.json}"
phase_top_n="${REPO_FETCH_PHASE_TOP_N:-20000}"
period_start="${REPO_ACTIVITY_PERIOD_START:-2026-08-01}"
period_end="${REPO_ACTIVITY_PERIOD_END:-2026-08-31}"
host_bootstrap_root="${REPO_BOOTSTRAP_STATE_ROOT:-$REPO_ROOT/.local/repo-snapshot-bootstrap}"
host_state_root="${host_bootstrap_root}/${snapshot_id}"
container_bootstrap_root="/var/lib/gitjob/repo-bootstrap"
container_state_root="${container_bootstrap_root}/${snapshot_id}"
publish_root="/gitjob/analysis_input/github/repo_snapshot/snapshot_id=${snapshot_id}"
webhdfs_url="${WEBHDFS_URL:-$(env_value WEBHDFS_URL)}"
webhdfs_url="${webhdfs_url:-http://hdfs-namenode:9870/webhdfs/v1}"
webhdfs_user="${WEBHDFS_USER:-$(env_value WEBHDFS_USER)}"
webhdfs_user="${webhdfs_user:-hadoop}"
historical_head_args=()
if [[ "${REPO_REQUIRE_HISTORICAL_HEAD:-0}" == "1" ]]; then
  historical_head_args+=(--require-historical-head)
fi

[[ -n "$snapshot_id" ]] || die "REPO_SNAPSHOT_ID is required and must stay stable across resume"
[[ "$snapshot_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || die "REPO_SNAPSHOT_ID must be a safe path component"
[[ -n "$pipeline_run_id" ]] || die "REPO_PIPELINE_RUN_ID is required and must stay stable across resume"
[[ -f "$candidate_file" ]] || die "candidate file is missing: $candidate_file"
[[ "$phase_top_n" =~ ^[1-9][0-9]*$ ]] || die "REPO_FETCH_PHASE_TOP_N must be positive"

mkdir -p "$host_state_root"
if [[ -f "$host_state_root/candidates.json" ]]; then
  cmp --silent "$candidate_file" "$host_state_root/candidates.json" \
    || die "candidate file differs from the immutable snapshot input"
else
  cp -- "$candidate_file" "$host_state_root/candidates.json"
fi

compose run --rm --no-deps -T repo-snapshot-bootstrap \
  sh -c 'test -n "$GITHUB_API_TOKEN"' \
  || die "worker GITHUB_API_TOKEN is missing; configure it without printing the value"

echo "Starting Repo Snapshot bootstrap snapshot_id=${snapshot_id} top_n=${phase_top_n}"
echo "WebHDFS namespace: hdfs://${publish_root}"
compose run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$host_bootstrap_root:${container_bootstrap_root}" \
  repo-snapshot-bootstrap \
  python -m github.repo_snapshot_bootstrap \
  --candidates "${container_state_root}/candidates.json" \
  --output "${container_state_root}/snapshot.json" \
  --summary-output "${container_state_root}/run-summary.json" \
  --failure-output "${container_state_root}/failures.json" \
  --state-output "${container_state_root}/state.json" \
  --checkpoint "${container_state_root}/checkpoint.json" \
  --cache "${container_bootstrap_root}/cache.json" \
  --artifact-store webhdfs \
  --webhdfs-artifact-root "hdfs://${publish_root}/artifacts" \
  --webhdfs-url "$webhdfs_url" \
  --webhdfs-user "$webhdfs_user" \
  --publish-root "hdfs://${publish_root}" \
  --dataset-snapshot-id "$snapshot_id" \
  --pipeline-run-id "$pipeline_run_id" \
  --period-start "$period_start" \
  --period-end "$period_end" \
  --limit "$phase_top_n" \
  "${historical_head_args[@]}" \
  --token-env GITHUB_API_TOKEN
