#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
"$SCRIPT_DIR/healthcheck.sh" >/dev/null

topic_base="${KAFKA_SMOKE_TOPIC:-gitjob.smoke}"
topic="${topic_base}.$(date -u +%Y%m%dT%H%M%SZ)-$$"
message="gitjob-wsl-smoke-$(date -u +%Y%m%dT%H%M%SZ)-$$"

cleanup() {
  compose exec -T kafka \
    /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --delete --topic "$topic" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Creating smoke-test topic: $topic"
compose exec -T kafka \
  /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic "$topic" --partitions 1 --replication-factor 1 >/dev/null

printf '%s\n' "$message" | compose exec -T kafka \
  /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic "$topic" >/dev/null

received="$(compose exec -T kafka \
  /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic "$topic" \
  --from-beginning --max-messages 1 --timeout-ms 10000 2>/dev/null | tr -d '\r')"

if [[ "$received" != "$message" ]]; then
  echo "Kafka smoke test failed: expected '$message', got '$received'" >&2
  exit 1
fi

echo "Kafka smoke test passed: $topic"
