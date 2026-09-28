#!/usr/bin/env bash
#
# Start the WSL-native Ollama server and make sure the summary model is present.
#
# Idempotent: running it against an already-serving instance only re-checks the
# model and exits. Safe to call before any task that needs the model.

set -Eeuo pipefail

OLLAMA_HOME="${OLLAMA_HOME:-$HOME/.local/ollama}"
OLLAMA_BIN="$OLLAMA_HOME/bin/ollama"
# Loopback only. Nothing about this host should be reachable from the LAN.
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
# -1 keeps the weights resident. A profile screen asks for a dozen technologies
# back to back, and reloading 3.4 GiB between them costs more than the
# generations themselves.
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:--1}"
LLM_MODEL="${LLM_MODEL:-qwen3.5:4b}"
LOG_FILE="${OLLAMA_LOG_FILE:-$HOME/.ollama/serve.log}"

[[ -x "$OLLAMA_BIN" ]] || {
  echo "error: $OLLAMA_BIN not found. Run bash Infra/scripts/llm-install-wsl.sh first" >&2
  exit 1
}

export OLLAMA_HOST OLLAMA_KEEP_ALIVE

if curl --fail --silent --max-time 3 "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
  echo "Ollama already serving on ${OLLAMA_HOST}"
else
  mkdir -p "$(dirname "$LOG_FILE")"
  echo "Starting Ollama on ${OLLAMA_HOST} (log: $LOG_FILE)"
  nohup "$OLLAMA_BIN" serve >>"$LOG_FILE" 2>&1 &
  for _ in {1..30}; do
    if curl --fail --silent --max-time 3 \
        "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  curl --fail --silent --max-time 3 "http://${OLLAMA_HOST}/api/version" >/dev/null || {
    tail -n 30 "$LOG_FILE" >&2
    echo "error: Ollama did not become ready on ${OLLAMA_HOST}" >&2
    exit 1
  }
fi

curl --fail --silent --max-time 5 "http://${OLLAMA_HOST}/api/version"
echo

if "$OLLAMA_BIN" list | awk 'NR > 1 {print $1}' | grep -qx "$LLM_MODEL"; then
  echo "Model present: $LLM_MODEL"
else
  echo "Pulling $LLM_MODEL (about 3.4 GB)..."
  "$OLLAMA_BIN" pull "$LLM_MODEL"
fi

# The GPU line in the log is the only place that says whether inference is
# actually on the card; a CPU fallback is many times slower but not an error.
grep -m 1 "inference compute" "$LOG_FILE" 2>/dev/null | tail -n 1 || true
