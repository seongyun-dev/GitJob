#!/usr/bin/env bash

# Checks whether this host's services are alive, independently of any deployment.
#
# On 2026-09-09 nginx served 502 for two hours and nobody knew. The deploy that broke
# it had reported success, and the failure only surfaced when a later deploy happened
# to fail. Nothing was watching in between. This is what watches in between.
#
# It is deliberately narrower than verify-deployment.sh. That script answers "is this
# deployment complete", which includes states that are fine to sit in for days (CDC
# not provisioned, C compute switched off). This one answers "is something that was
# working now broken", which is the only question worth waking someone for.
#
# Alerts fire on a change of state, not on every run. A service that has been down for
# an hour should not send twelve alerts an hour; a service that just came back should
# say so once.
#
# Usage:
#   ./Infra/scripts/health-probe.sh                  # one check, exit 0 if healthy
#   HEALTH_ALERT_WEBHOOK=https://... ./Infra/scripts/health-probe.sh
#
# Environment:
#   HEALTH_ALERT_WEBHOOK  POST target for alerts. Without it the probe still runs and
#                         records to the journal, but nothing reaches a person.
#   HEALTH_PROBE_URL      Entry point to check. Defaults to the local HTTPS endpoint.
#   HEALTH_STATE_FILE     Where the previous verdict is kept, to detect transitions.

set -Eeuo pipefail

PROBE_URL="${HEALTH_PROBE_URL:-https://127.0.0.1/health}"
STATE_FILE="${HEALTH_STATE_FILE:-/var/tmp/gitjob-health-probe.state}"
WEBHOOK="${HEALTH_ALERT_WEBHOOK:-}"
HOST_LABEL="${HEALTH_HOST_LABEL:-$(hostname)}"

failures=()

# --- entry point ------------------------------------------------------------
# Only meaningful where something serves it; the data host has no nginx.
if docker ps --format '{{.Names}}' | grep -q 'nginx'; then
  # Self-signed or hostname-mismatched certificates are not what this is testing.
  body="$(curl -sS -k --max-time 10 "$PROBE_URL" 2>&1 || true)"
  if [[ "$body" != *'"status":"UP"'* ]]; then
    failures+=("entry point $PROBE_URL did not report UP: ${body:0:200}")
  fi
fi

# --- container states -------------------------------------------------------
# Anything that exited, died, is looping, or has gone unhealthy. Containers with no
# healthcheck are only judged on whether they are running at all.
while IFS=$'\t' read -r name state health; do
  [[ -z "$name" ]] && continue
  case "$state" in
    running)
      [[ "$health" == "unhealthy" ]] && failures+=("$name is unhealthy")
      ;;
    restarting)
      failures+=("$name is restarting in a loop")
      ;;
    *)
      failures+=("$name is $state")
      ;;
  esac
done < <(docker ps -a \
  --filter 'name=gitjob-' \
  --format '{{.Names}}\t{{.State}}\t{{if .Status}}{{.Status}}{{end}}' \
  | sed -E 's/\t[^\t]*\(healthy\)[^\t]*$/\thealthy/; s/\t[^\t]*\(unhealthy\)[^\t]*$/\tunhealthy/; s/\t[^\t]*$/\tnone/')

# One-shot containers finish and stay exited on purpose; they are not failures.
filtered=()
for f in "${failures[@]:-}"; do
  [[ -z "$f" ]] && continue
  [[ "$f" == *-init-1\ is\ exited* || "$f" == *bootstrap-1\ is\ exited* ]] && continue
  filtered+=("$f")
done
failures=("${filtered[@]:-}")
failure_count=0
for f in "${failures[@]:-}"; do [[ -n "$f" ]] && failure_count=$((failure_count + 1)); done

# --- verdict and transition -------------------------------------------------
if [[ "$failure_count" -eq 0 ]]; then
  verdict="OK"
  summary="all services healthy"
else
  verdict="FAIL"
  summary="$(printf '%s; ' "${failures[@]}")"
  summary="${summary%; }"
fi

previous="$(cat "$STATE_FILE" 2>/dev/null || echo "UNKNOWN")"
printf '%s\n' "$verdict" > "$STATE_FILE" 2>/dev/null || true

echo "[$HOST_LABEL] $verdict: $summary"

notify() {
  local text="$1"
  logger -t gitjob-health "$text" 2>/dev/null || true
  if [[ -n "$WEBHOOK" ]]; then
    # Payload shape suits Slack and Mattermost incoming webhooks.
    curl -sS --max-time 10 -X POST -H 'Content-Type: application/json' \
      --data "$(printf '{"text":"%s"}' "${text//\"/\\\"}")" \
      "$WEBHOOK" >/dev/null 2>&1 || echo "alert webhook failed" >&2
  fi
}

# Only transitions are announced. Repeating an unchanged failure every few minutes
# trains people to ignore it, which is the state we are trying to get out of.
if [[ "$verdict" != "$previous" ]]; then
  if [[ "$verdict" == "FAIL" ]]; then
    notify "🔴 [$HOST_LABEL] $summary"
  elif [[ "$previous" == "FAIL" ]]; then
    notify "🟢 [$HOST_LABEL] recovered: all services healthy"
  fi
fi

[[ "$failure_count" -eq 0 ]]
