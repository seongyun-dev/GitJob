#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

topic="${1:-}"
payload_file="${2:-}"
[[ -n "$topic" && -n "$payload_file" ]] || die "usage: $0 <topic> <newline-delimited-payload-file>"
[[ "$topic" != -* ]] || die "topic must not start with '-'"
[[ -f "$payload_file" ]] || die "payload file not found: $payload_file"

"$SCRIPT_DIR/healthcheck.sh" >/dev/null
echo "Replaying $(wc -l < "$payload_file") records to Kafka topic '$topic'"
compose exec -T kafka \
  /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic "$topic" < "$payload_file"
echo "Replay completed."
