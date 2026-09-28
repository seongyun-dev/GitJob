#!/usr/bin/env bash

set -Eeuo pipefail

container_id="$(
  docker ps --quiet \
    --filter label=com.docker.compose.project=gitjob-service \
    --filter label=com.docker.compose.service=nginx \
    | head -n 1
)"

if [[ -z "$container_id" ]]; then
  echo "GitJob Nginx container is not running; skipping certificate reload."
  exit 0
fi

docker exec "$container_id" nginx -t >/dev/null 2>&1
docker exec "$container_id" nginx -s reload >/dev/null 2>&1
