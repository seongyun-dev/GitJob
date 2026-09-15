#!/usr/bin/env bash
#
# Start the technology-summary HTTP server inside WSL, bound where the Tailscale
# bridge expects it.
#
# 0.0.0.0 rather than loopback because the listener has to be reachable from the
# Windows side: the bridge (Infra/scripts/llm-tailscale-bridge.ps1) connects to
# this distro's address, and a loopback bind is invisible to it. WSL sits behind
# its own NAT, so this does not put the port on the LAN.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
# 18080 is the port the Windows firewall rule opens on the Tailscale address.
APP_PORT="${APP_PORT:-18080}"
APP_HOST="${APP_HOST:-0.0.0.0}"
LOG_FILE="${LLM_SUMMARY_LOG_FILE:-$HOME/.ollama/summary-server.log}"

[[ -x "$PYTHON" ]] || { echo "error: $PYTHON not found" >&2; exit 1; }

# The summary server answers 200 with a FALLBACK body when the model is down, so
# a missing Ollama would look healthy. Check it here instead.
bash "$SCRIPT_DIR/llm-serve-wsl.sh" >/dev/null

if curl --fail --silent --max-time 3 "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
  echo "summary server already serving on 127.0.0.1:${APP_PORT}"
else
  mkdir -p "$(dirname "$LOG_FILE")"
  ( cd "$REPO_ROOT/AI" \
    && APP_HOST="$APP_HOST" APP_PORT="$APP_PORT" nohup "$PYTHON" -m llm >>"$LOG_FILE" 2>&1 & )
  for _ in {1..20}; do
    curl --fail --silent --max-time 2 "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

curl --fail --silent --max-time 5 "http://127.0.0.1:${APP_PORT}/health" || {
  tail -n 20 "$LOG_FILE" >&2
  echo "error: summary server did not become ready on ${APP_HOST}:${APP_PORT}" >&2
  exit 1
}
echo
echo "WSL address for the bridge: $(hostname -I | awk '{print $1}'):${APP_PORT}"
