#!/usr/bin/env bash
#
# Publish a weekly Repo Activity snapshot to C (S15P21E102-231).
#
# The other half of `weekly-repo-activity.sh`. That one leaves a summary JSON
# on the host; this one hands it to `github.weekly_activity_publish_cli` inside
# the worker container, which writes one `_SUCCESS.json` per week and sends one
# completion event per week.
#
# ## Why a wrapper is needed at all
#
# The summary lives on the host and the CLI lives in the worker image. Without
# a volume the container cannot see the file, and running the CLI on the host
# instead fails differently — the dependencies are not installed there and
# `hdfs-namenode` / `kafka` do not resolve outside the Compose network.
#
# `repo-snapshot-bootstrap.sh` crosses the same boundary the same way.
#
# ## Run the dry run first
#
# The first real run writes immutable objects. A wrong `--dataset-snapshot-id`
# becomes a directory nobody meant to create and `store_immutable` will not let
# it be rewritten, so the correction is a new snapshot id rather than an edit.
#
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
#   PROFILES=data WEEKLY_SNAPSHOT_ID=s15p21e102-224-stream-20260913 \
#     ./Infra/scripts/weekly-snapshot-publish.sh --dry-run
#   ... same command without --dry-run

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

dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
  shift
fi
[[ $# -eq 0 ]] || die "unexpected argument: $1 (only --dry-run is accepted)"

snapshot_id="${WEEKLY_SNAPSHOT_ID:-}"
[[ -n "$snapshot_id" ]] || die "WEEKLY_SNAPSHOT_ID is required"

state_root="${WEEKLY_STATE_ROOT:-$REPO_ROOT/.local/weekly-repo-activity}"
summary_file="${WEEKLY_SUMMARY:-$state_root/${snapshot_id}-summary.json}"
[[ -f "$summary_file" ]] \
  || die "summary not found: $summary_file (run weekly-repo-activity.sh first)"

webhdfs_url="${WEBHDFS_URL:-$(env_value WEBHDFS_URL)}"
webhdfs_url="${webhdfs_url:-http://hdfs-namenode:9870/webhdfs/v1}"
webhdfs_user="${WEBHDFS_USER:-$(env_value WEBHDFS_USER)}"
webhdfs_user="${webhdfs_user:-hadoop}"

# No fallback, for the reason `-211` removed one from the archiver: the data
# host runs no broker, so a default would name something that does not resolve
# and the failure would arrive at the first send instead of here. Unset is
# still allowed — the publisher then writes manifests and announces nothing.
bootstrap="${KAFKA_BOOTSTRAP_SERVERS:-$(env_value KAFKA_BOOTSTRAP_SERVERS)}"

container_state="/data/weekly-repo-activity"
container_summary="${container_state}/$(basename -- "$summary_file")"

cli_args=(
  --summary "$container_summary"
  --dataset-snapshot-id "$snapshot_id"
  --webhdfs-url "$webhdfs_url"
  --webhdfs-user "$webhdfs_user"
)
[[ "$dry_run" == "1" ]] && cli_args+=(--dry-run)

run_args=(
  --rm --no-deps -T
  --user "$(id -u):$(id -g)"
  --volume "$state_root:${container_state}:ro"
)
# Passed explicitly rather than relying on the service's environment block, so
# the value the wrapper resolved is the value the publisher uses.
[[ -n "$bootstrap" ]] && run_args+=(--env "KAFKA_BOOTSTRAP_SERVERS=$bootstrap")

if [[ "$dry_run" == "1" ]]; then
  echo "weekly snapshot publish (dry run): ${snapshot_id}" >&2
else
  echo "weekly snapshot publish: ${snapshot_id}" >&2
  [[ -n "$bootstrap" ]] \
    || echo "  KAFKA_BOOTSTRAP_SERVERS is unset; manifests only, no events" >&2
fi

compose run "${run_args[@]}" worker \
  python -m github.weekly_activity_publish_cli "${cli_args[@]}"
