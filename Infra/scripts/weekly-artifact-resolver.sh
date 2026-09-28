#!/usr/bin/env bash
#
# Run the Weekly Repository Artifact Resolver (S15P21E102-323).
#
# The third wrapper in the Weekly set, after `weekly-repo-activity.sh` and
# `weekly-snapshot-publish.sh`, and it exists for the same reason they do: the
# CLI lives in the worker image and the candidate/output files live on the host,
# so something has to carry one across to the other.
#
# ## Why the service is pinned to `worker`
#
# Only `worker` declares the REDIS_* block. A resolver started in `collector`
# builds no Redis index even when the flag is passed, and the run summary cannot
# tell that apart from a genuinely cold namespace — every Redis metric simply
# reads zero. `-323` refuses that configuration in the orchestrator; this
# wrapper makes sure the supported one is what gets run.
#
# ## Why some values are passed explicitly
#
# `worker` has no GITHUB_API_TOKEN / WEBHDFS_URL / WEBHDFS_USER in its
# environment block, so they are resolved from ENV_FILE here and handed over on
# the command line. `weekly-snapshot-publish.sh` passes KAFKA_BOOTSTRAP_SERVERS
# the same way and for the same reason: the value the wrapper resolved is the
# value the process uses.
#
# ## Redis
#
# The index is on by default (compose sets WEEKLY_REDIS_ARTIFACT_INDEX_ENABLED).
# Production uses db 1 and namespace gitjob:weekly:artifact-index:v1, both code
# defaults; the benchmark's db 3 / gitjob:benchmark:... namespace is never used
# from here. Redis is an index, not the source of truth — a hit is only reused
# after the durable artifact validates, and a broker failure falls back to the
# normal resolver path.
#
# ## Usage
#
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
#   PROFILES=data \
#   WEEKLY_CANDIDATES=.local/weekly-artifact/weekly-candidates-2026-09-07.json \
#   WEEKLY_ARTIFACT_STATE_ROOT=.local/weekly-artifact \
#   WEEKLY_SNAPSHOT_ID=s15p21e102-296-weekly-20260907-20260918-v1 \
#   WEEKLY_RUN_ID=s15p21e102-296-weekly-20260907-run-001 \
#     ./Infra/scripts/weekly-artifact-resolver.sh

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

snapshot_id="${WEEKLY_SNAPSHOT_ID:-}"
[[ -n "$snapshot_id" ]] || die "WEEKLY_SNAPSHOT_ID is required"
run_id="${WEEKLY_RUN_ID:-${snapshot_id}-run-001}"

state_root="${WEEKLY_ARTIFACT_STATE_ROOT:-$REPO_ROOT/.local/weekly-artifact}"
candidates="${WEEKLY_CANDIDATES:-$state_root/weekly-candidates.json}"
[[ -f "$candidates" ]] \
  || die "candidates not found: $candidates (run the candidate export first)"

# The `-274` contract. Named here so a Weekly run cannot quietly inherit the
# Historical Top-10000 pool by way of a stray environment variable.
pool_limit="${WEEKLY_CANDIDATE_POOL_LIMIT:-1500}"
quota="${WEEKLY_ARTIFACT_QUOTA:-100}"
batch_size="${WEEKLY_CANDIDATE_BATCH_SIZE:-1}"
for value in "$pool_limit" "$quota" "$batch_size"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "pool/quota/batch must be positive: $value"
done

token="${GITHUB_API_TOKEN:-$(env_value GITHUB_API_TOKEN)}"
[[ -n "$token" ]] || die "GITHUB_API_TOKEN is required (set it in $ENV_FILE)"

webhdfs_url="${WEBHDFS_URL:-$(env_value WEBHDFS_URL)}"
webhdfs_url="${webhdfs_url:-http://hdfs-namenode:9870/webhdfs/v1}"
webhdfs_user="${WEBHDFS_USER:-$(env_value WEBHDFS_USER)}"
webhdfs_user="${webhdfs_user:-hadoop}"

container_state="/data/weekly-artifact"
container_candidates="${container_state}/$(basename -- "$candidates")"

mkdir -p "$state_root"

echo "weekly artifact resolver: ${snapshot_id}" >&2
echo "  service        : worker (carries REDIS_*; collector does not)" >&2
echo "  candidates     : ${candidates}" >&2
echo "  pool/quota/batch: ${pool_limit}/${quota}/${batch_size}" >&2
echo "  redis index    : enabled (Production db/namespace defaults)" >&2

compose run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$state_root:${container_state}" \
  --env "GITHUB_API_TOKEN=$token" \
  --env "WEBHDFS_URL=$webhdfs_url" \
  --env "WEBHDFS_USER=$webhdfs_user" \
  worker \
  python -m github.weekly_artifact_resolver \
  --candidates "$container_candidates" \
  --output "${container_state}/${snapshot_id}-snapshot.json" \
  --summary-output "${container_state}/${snapshot_id}-run-summary.json" \
  --failure-output "${container_state}/${snapshot_id}-failures.json" \
  --state-output "${container_state}/${snapshot_id}-state.json" \
  --checkpoint "${container_state}/${snapshot_id}-checkpoint.json" \
  --cache "${container_state}/${snapshot_id}-cache.json" \
  --artifact-root "${container_state}/artifacts" \
  --dataset-snapshot-id "$snapshot_id" \
  --pipeline-run-id "$run_id" \
  --candidate-pool-limit "$pool_limit" \
  --valid-artifact-quota "$quota" \
  --candidate-batch-size "$batch_size" \
  --enable-redis-artifact-index \
  --webhdfs-url "$webhdfs_url" \
  --webhdfs-user "$webhdfs_user" \
  --token-env GITHUB_API_TOKEN
