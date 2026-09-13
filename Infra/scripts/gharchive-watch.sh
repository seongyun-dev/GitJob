#!/usr/bin/env bash
#
# Poll GH Archive for newly published hours (S15P21E102-229).
#
# `python -m collector.gharchive watch` calls `watcher.poll()` once and exits,
# so this is cron-shaped work, not a service. `-228`'s C1 archiver is the other
# case — that one is a long-running query and became a Compose service.
#
# ## Why this is a separate run from publishing
#
# `-144` keeps two checkpoints on purpose: this one records what is on disk,
# and `gharchive-publish.sh`'s records what reached the broker. Merging them
# would make a broker outage either re-download every hour or silently skip
# publishing, which is the failure `S15P21E102-174` already paid for once on
# the collectors' cursor.
#
# So: this script downloads, and it never publishes. Run both from cron, in
# that order.
#
# ## Why flock
#
# `CheckpointStore` writes atomically (`os.replace`) but takes no exclusive
# lock. Two overlapping runs each read, decide, and write — and the later
# writer wins, dropping whatever the other one recorded. An hour lost that way
# looks exactly like an hour GH Archive never published.
#
# `repo-snapshot-monthly-top10k-chain.sh` guards itself the same way.
#
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
#     PROFILES=data ./Infra/scripts/gharchive-watch.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=data"

state_root="${GHARCHIVE_WATCH_STATE_ROOT:-$REPO_ROOT/.local/gharchive-watch}"
log_root="${GHARCHIVE_WATCH_LOG_ROOT:-$state_root/logs}"
mkdir -p "$state_root" "$log_root"

# The container sees the state directory here; WORKDIR is /app.
container_state="/data/gharchive-watch"
checkpoint="$container_state/watch-checkpoint.json"
output_root="$container_state/hours"

lag_minutes="${GHARCHIVE_WATCH_LAG_MINUTES:-30}"
grace_hours="${GHARCHIVE_WATCH_GRACE_HOURS:-3}"

exec 9>"$state_root/.watch.lock"
if command -v flock >/dev/null 2>&1; then
  # Non-blocking: a run still going means the previous poll has not finished,
  # and queueing another would put two writers on one checkpoint.
  flock -n 9 || die "gharchive watch is already running: $state_root"
fi

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log_file="$log_root/watch-$(date -u +%Y%m%d).log"
echo "[$started] gharchive watch lag=${lag_minutes}m grace=${grace_hours}h" >>"$log_file"

# `--user` so the files land owned by the operator rather than by root, matching
# `repo-snapshot-bootstrap.sh`.
set +e
compose run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$state_root:$container_state" \
  collector \
  python -m collector.gharchive watch \
  --output-root "$output_root" \
  --checkpoint "$checkpoint" \
  --lag-minutes "$lag_minutes" \
  --grace-hours "$grace_hours" \
  >>"$log_file" 2>&1
status=$?
set -e

finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[$finished] gharchive watch exit=${status}" >>"$log_file"
# Exit code is what cron logs and what an alert would key on: 0 = every
# expected hour is on disk, 1 = a gap or a download failure, 2 = a bad range or
# checkpoint. `not_yet_published` is not a failure and does not reach here.
exit "$status"
