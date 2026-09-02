#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/Infra/compose/compose.llm.yaml"

PROJECT_NAME="${LLM_COMPOSE_PROJECT_NAME:-gitjob-llm}"
VOLUME_NAME="${LLM_VOLUME_NAME:-gitjob-ollama-models}"

command -v docker >/dev/null 2>&1 || {
  echo "error: Docker is not on PATH" >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "error: curl is not on PATH" >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "error: Docker daemon is not reachable" >&2
  exit 1
}

if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "Creating persistent Ollama model cache volume: $VOLUME_NAME"
  docker volume create "$VOLUME_NAME" >/dev/null
fi

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --project-directory "$REPO_ROOT" \
    -f "$COMPOSE_FILE" \
    "$@"
}

echo "Validating local LLM Compose configuration..."
compose config --quiet

echo "Starting Ollama GPU service..."
if ! compose up -d --wait --wait-timeout 210; then
  compose ps
  compose logs --no-color --tail=100 ollama >&2 || true
  exit 1
fi

PUBLISHED_ADDRESS="$(compose port ollama 11434 | tail -n 1 | tr -d '\r')"
if [[ -z "$PUBLISHED_ADDRESS" ]]; then
  compose ps
  echo "error: Compose did not publish Ollama port 11434" >&2
  exit 1
fi

for _ in {1..30}; do
  if curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
      "http://${PUBLISHED_ADDRESS}/api/version" >/dev/null; then
    compose ps
    curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
      "http://${PUBLISHED_ADDRESS}/api/version"
    echo
    exit 0
  fi
  sleep 2
done

compose ps
compose logs --no-color --tail=100 ollama >&2 || true
echo "error: Ollama did not become ready on ${PUBLISHED_ADDRESS}" >&2
exit 1
