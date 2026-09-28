#!/usr/bin/env bash
#
# Publish downloaded GH Archive hours to `github.events` (S15P21E102-229).
#
# The other half of `gharchive-watch.sh`. That one puts hours on disk; this one
# sends them to the broker, and the two keep separate checkpoints so a broker
# outage never turns into a re-download and a download failure never turns into
# a silent publishing gap (`-144`).
#
# Run it after the watcher, from its own cron line. Ordering matters only in
# that publishing an hour the watcher has not fetched yet is a no-op — the next
# run picks it up.
#
# ## What one run does
#
# An hour is published all-or-nothing: the checkpoint records it only after the
# whole file went out, so a failure part-way re-sends the part that already
# landed. `-102` §4.1 makes `(source, source_id, schema_version)` the
# consumer-side dedup key precisely so that re-send is absorbed — losing events
# is worse than repeating them.
#
# `--max-hours` bounds one pass. The first run after the bootstrap cutoff has
# every hour since it to send, which on 2026-09-09 was over 200; publishing
# them in one go would hold the container for a long time and give no partial
# progress.
#
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
#     PROFILES=data ./Infra/scripts/gharchive-publish.sh

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

# Same state root the watcher writes into: this reads the hours it downloaded.
state_root="${GHARCHIVE_WATCH_STATE_ROOT:-$REPO_ROOT/.local/gharchive-watch}"
log_root="${GHARCHIVE_WATCH_LOG_ROOT:-$state_root/logs}"
[[ -d "$state_root" ]] || die "watch state root does not exist yet: $state_root"
mkdir -p "$log_root"

container_state="/data/gharchive-watch"
output_root="$container_state/hours"
# Deliberately not the watcher's checkpoint. See the header.
publish_checkpoint="$container_state/publish-checkpoint.json"

# No fallback, for the reason `-211` removed one from the archiver: the data
# host runs no broker, so a default would name something that does not resolve
# and the failure would surface at the first send instead of here.
bootstrap="${KAFKA_BOOTSTRAP_SERVERS:-$(env_value KAFKA_BOOTSTRAP_SERVERS)}"
[[ -n "$bootstrap" ]] \
  || die "KAFKA_BOOTSTRAP_SERVERS is not set in the environment or in $ENV_FILE"

max_hours="${GHARCHIVE_PUBLISH_MAX_HOURS:-24}"
[[ "$max_hours" =~ ^[1-9][0-9]*$ ]] || die "GHARCHIVE_PUBLISH_MAX_HOURS must be positive"

exec 9>"$state_root/.publish.lock"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || die "gharchive publish is already running: $state_root"
fi

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log_file="$log_root/publish-$(date -u +%Y%m%d).log"
echo "[$started] gharchive publish max_hours=${max_hours}" >>"$log_file"

set +e
compose run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$state_root:$container_state" \
  --env "KAFKA_BOOTSTRAP_SERVERS=$bootstrap" \
  collector \
  python -m collector.gharchive publish \
  --output-root "$output_root" \
  --publish-checkpoint "$publish_checkpoint" \
  --max-hours "$max_hours" \
  >>"$log_file" 2>&1
status=$?
set -e

finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[$finished] gharchive publish exit=${status}" >>"$log_file"
# 0 = nothing failed and nothing expected was missing, 1 = a failed or missing
# hour, 2 = a checkpoint or configuration error.
exit "$status"
