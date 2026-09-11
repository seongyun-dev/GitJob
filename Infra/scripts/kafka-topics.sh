#!/usr/bin/env bash

# Declare the Kafka topics this project owns (S15P21E102-108).
#
# `KAFKA_AUTO_CREATE_TOPICS_ENABLE` is "false" in compose.yaml, so a producer
# that publishes to a topic nobody created fails instead of quietly getting a
# one-partition topic. That is the right setting — a partition count decided
# by accident cannot be reduced later — but it means the topics have to be
# declared somewhere, and until now they were not. `jobs.collected` was
# created by hand on 2026-09-09 and would have disappeared on a fresh
# environment.
#
# Partition counts come from S15P21E102-102 §3.2 and are the reason this
# script exists rather than a README instruction:
#
#   github.events    6   repo id        578k/hour burst from -144's hourly
#                                       files. Spark worker is 2 core today so
#                                       6 is more than can be consumed, and
#                                       that is deliberate — partitions grow
#                                       one way only.
#   so.raw           3   post id        10,000/day. 6 would be overkill.
#   jobs.collected   3   source_site    4 messages a day. The Claim Check
#                                       envelope carries a run location, not
#                                       postings, so volume never grows with
#                                       the number of collected postings.
#
# `retention.ms=-1` and `cleanup.policy=delete` are from §5: replay from the
# beginning is the design basis, so nothing may age out and nothing may be
# compacted away by key.
#
# Repository analysis owns three explicit topics. Auto-create is disabled and
# an empty deployment has no outbox event for Debezium to route yet, so relying
# on first traffic leaves both the consumer and result producer unready. Three
# partitions matches the connector's topic.creation.default.partitions setting
# and the existing result-topic contract.
#
# Idempotent: `--create --if-not-exists` leaves an existing topic alone. It
# does **not** change the partition count of a topic that already exists —
# Kafka cannot reduce partitions, and silently raising them would rehash every
# key and break per-key ordering. A mismatch is reported for a human instead.
#
#   infra/scripts/kafka-topics.sh          # create missing, then describe
#   infra/scripts/kafka-topics.sh --check  # report only, create nothing

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
elif [[ -n "${1:-}" ]]; then
  die "unknown argument: $1 (expected --check or nothing)"
fi

require_core_tools

# name:partitions
TOPICS=(
  "github.events:6"
  "so.raw:3"
  "jobs.collected:3"
  "gitjob.repository-analysis.requests.v1:3"
  "gitjob.repository-analysis.results.v1:3"
  "gitjob.repository-analysis.dlq.v1:3"
)

RETENTION_MS="-1"
CLEANUP_POLICY="delete"
# Single-broker KRaft in this environment; the compose file pins every internal
# replication factor to 1 for the same reason.
REPLICATION_FACTOR=1

kafka_topics() {
  # The leading `//` is not a typo. Git Bash rewrites an argument that looks
  # like an absolute path, so `/opt/kafka/...` reached docker as
  # `C:/Program Files/Git/opt/kafka/...` and exec failed inside the container.
  # A doubled slash survives that rewrite and means the same thing on Linux, so
  # this works on both without a platform-specific variable.
  #
  # MSYS_NO_PATHCONV=1 is not an option here: the same command line also
  # carries host paths (--env-file, -f) that do need converting.
  compose exec -T kafka //opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 "$@"
}

existing_partitions() {
  # `--describe` prints "PartitionCount: N" on the topic's summary line.
  local topic="$1"
  kafka_topics --describe --topic "$topic" 2>/dev/null |
    sed -n 's/.*PartitionCount:[[:space:]]*\([0-9]\+\).*/\1/p' |
    head -1
}

mismatch=0
created=0

for entry in "${TOPICS[@]}"; do
  topic="${entry%%:*}"
  want="${entry##*:}"
  have="$(existing_partitions "$topic" || true)"

  if [[ -z "$have" ]]; then
    if (( CHECK_ONLY )); then
      echo "MISSING  $topic (would create with $want partitions)"
      mismatch=1
      continue
    fi
    echo "Creating $topic with $want partitions"
    kafka_topics \
      --create --if-not-exists \
      --topic "$topic" \
      --partitions "$want" \
      --replication-factor "$REPLICATION_FACTOR" \
      --config "retention.ms=$RETENTION_MS" \
      --config "cleanup.policy=$CLEANUP_POLICY" >/dev/null
    created=$((created + 1))
    continue
  fi

  if [[ "$have" != "$want" ]]; then
    # Deliberately not repaired. Raising partitions rehashes keys and breaks
    # per-key ordering; lowering them is impossible. Whoever changes this has
    # to decide whether the topic can be recreated.
    echo "MISMATCH $topic has $have partitions, -102 §3.2 says $want" >&2
    mismatch=1
    continue
  fi

  echo "OK       $topic ($have partitions)"
done

echo
for entry in "${TOPICS[@]}"; do
  topic="${entry%%:*}"
  # `kafka-topics.sh` reports a missing topic on stdout, not stderr, so the
  # summary is filtered to real topic lines instead of redirecting.
  kafka_topics --describe --topic "$topic" 2>/dev/null |
    grep -E '^Topic:' | head -1 | sed 's/^/  /' || true
done

if (( mismatch )); then
  echo
  echo "One or more topics do not match S15P21E102-102 §3.2." >&2
  exit 1
fi

echo
if (( created )); then
  echo "Created $created topic(s); all topics now match -102 §3.2."
else
  echo "All topics already match -102 §3.2."
fi
