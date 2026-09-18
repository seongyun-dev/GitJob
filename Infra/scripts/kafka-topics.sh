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
#   gitjob.repo-activity-weekly.completed.v1
#                    1   snapshot/week  One message per published week (-225).
#                                       A week is announced once and C reads it
#                                       in order; a second partition would buy
#                                       parallelism nobody needs and give up
#                                       that ordering.
#   jobs.collected   3   source_site    4 messages a day. The Claim Check
#                                       envelope carries a run location, not
#                                       postings, so volume never grows with
#                                       the number of collected postings.
#
# `cleanup.policy=delete` is from §5: nothing may be compacted away by key.
#
# Retention is per topic, not one global value. §5's `retention.ms=-1` still
# holds for every topic whose replay-from-the-beginning is the design basis,
# but `github.events` is the exception and the reason this list carries a third
# column (S15P21E102-258).
#
#   github.events   86400000 (24h)   GH Archive hours. The only topic whose
#                                    volume is bounded by nothing but how fast
#                                    the publisher runs. On 2026-09-14 it filled
#                                    the service host root ("No space left on
#                                    device") and took Postgres down with it.
#                                    Kafka shares that root with the HDFS
#                                    DataNode4 volume, which is 192.5 GB of the
#                                    220 GB in use — so Kafka cannot be allowed
#                                    to grow without a ceiling. 24h is long
#                                    enough for C1 to fall a full day behind and
#                                    still catch up without a re-download, which
#                                    is the replay this topic actually needs.
#   everything else -1               Unchanged. These are small, and replay from
#                                    offset 0 is how they are consumed.
#
# 12h was the emergency value applied during the incident to reclaim space; it
# is not the operating policy. See
# `docs/data/2026-09-17-kafka-retention-and-connect-log-bounds.md`.
#
# Repository analysis owns five explicit topics. Auto-create is disabled and
# an empty deployment has no outbox event for Debezium to route yet, so relying
# on first traffic leaves both the consumer and result producer unready. Three
# partitions matches the connector's topic.creation.default.partitions setting
# and the existing result-topic contract.
#
# `results.v1` and `results.v3` are both result topics and both have to exist.
# The worker publishes one contract per analysis and picks the topic from the Rule
# Pack it judged with -- it does not also send v1. A missing v3 topic is therefore
# not a degraded mode: the worker refuses to start, and if it were started without
# one, registry-20260911.3/.4 analyses would fail with UNSUPPORTED_RESULT_SCHEMA.
#
# The two DLQs are not interchangeable. `...dlq.v1` takes requests the worker
# could not process; `...results.dlq.v1` takes results this service could not
# apply, and it has to exist before the backend starts -- the consumer stops on
# a record it cannot deliver there. That is deliberate. Without a DLQ at all, a
# result that failed to deserialize was logged once and committed, which is how
# four analyses were lost with consumer lag reading zero.
#
# Idempotent: `--create --if-not-exists` leaves an existing topic alone. It
# does **not** change the partition count of a topic that already exists —
# Kafka cannot reduce partitions, and silently raising them would rehash every
# key and break per-key ordering. A mismatch is reported for a human instead.
#
# Retention drift is a separate problem from a missing topic. `--create
# --if-not-exists` leaves an existing topic's config alone, so a topic whose
# `retention.ms` was changed by hand during an incident keeps that value for
# ever and nothing here notices. Every mode below therefore compares the live
# `retention.ms` against the table and reports a difference;
# `--enforce-retention` is the one mode that repairs it.
#
#   infra/scripts/kafka-topics.sh                     # create missing, then describe
#   infra/scripts/kafka-topics.sh --check             # report only, change nothing
#   infra/scripts/kafka-topics.sh --enforce-retention # also align existing topics

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

CHECK_ONLY=0
ENFORCE_RETENTION=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  --enforce-retention) ENFORCE_RETENTION=1 ;;
  "") ;;
  *) die "unknown argument: $1 (expected --check, --enforce-retention, or nothing)" ;;
esac

require_core_tools

# name:partitions:retention.ms
TOPICS=(
  "github.events:6:86400000"
  "so.raw:3:-1"
  "jobs.collected:3:-1"
  "gitjob.repository-analysis.requests.v1:3:-1"
  "gitjob.repository-analysis.results.v1:3:-1"
  "gitjob.repository-analysis.results.v3:3:-1"
  "gitjob.repository-analysis.dlq.v1:3:-1"
  "gitjob.repository-analysis.results.dlq.v1:3:-1"
  # 진행 단계. 요청·결과와 같은 키(analysis_id)를 쓰므로 파티션 수도 같게 둔다.
  #
  # 유일하게 retention.ms 가 -1 이 아닌 repository-analysis 토픽이다. 처음부터
  # 재생하는 것이 설계의 근거인 다른 토픽들과 달리, 지나간 진행은 화면에 보여 줄
  # 곳이 없다 -- 그 분석은 이미 끝나 있어 backend 가 전부 무시한다. 24시간은
  # 어제 난 장애를 들여다볼 수 있을 만큼 길고, 쌓이지 않을 만큼 짧다.
  "gitjob.repository-analysis.progress.v1:3:86400000"
  "gitjob.repo-activity-weekly.completed.v1:1:-1"
)

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

kafka_configs() {
  # Same doubled-slash reason as `kafka_topics`.
  compose exec -T kafka //opt/kafka/bin/kafka-configs.sh \
    --bootstrap-server localhost:9092 --entity-type topics "$@"
}

existing_retention() {
  # Prints the topic's `retention.ms` override. A topic without an override
  # inherits the broker default, which is not `-1`, so an absent override is
  # reported as `<broker-default>` rather than silently passing the comparison.
  local topic="$1" found
  found="$(kafka_configs --entity-name "$topic" --describe 2>/dev/null |
    grep -o 'retention[.]ms=[-0-9]*' | head -1)" || true
  if [[ -z "$found" ]]; then
    echo "<broker-default>"
  else
    echo "${found#retention.ms=}"
  fi
}

mismatch=0
created=0
retention_fixed=0

for entry in "${TOPICS[@]}"; do
  IFS=: read -r topic want want_retention <<<"$entry"
  have="$(existing_partitions "$topic" || true)"

  if [[ -z "$have" ]]; then
    if (( CHECK_ONLY )); then
      echo "MISSING  $topic (would create with $want partitions, retention.ms=$want_retention)"
      mismatch=1
      continue
    fi
    echo "Creating $topic with $want partitions, retention.ms=$want_retention"
    kafka_topics \
      --create --if-not-exists \
      --topic "$topic" \
      --partitions "$want" \
      --replication-factor "$REPLICATION_FACTOR" \
      --config "retention.ms=$want_retention" \
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

  # Retention is repairable in a way partitions are not: `--alter` changes only
  # how long records are kept, never how they are distributed, so it cannot
  # break ordering or rehash a key.
  have_retention="$(existing_retention "$topic")"
  if [[ "$have_retention" == "$want_retention" ]]; then
    echo "OK       $topic ($have partitions, retention.ms=$have_retention)"
    continue
  fi

  if (( ENFORCE_RETENTION )); then
    echo "ALTER    $topic retention.ms $have_retention -> $want_retention"
    kafka_configs --entity-name "$topic" \
      --alter --add-config "retention.ms=$want_retention" >/dev/null
    retention_fixed=$((retention_fixed + 1))
    continue
  fi

  echo "DRIFT    $topic retention.ms=$have_retention, this table says $want_retention" >&2
  echo "         re-run with --enforce-retention to align it" >&2
  mismatch=1
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
  echo "One or more topics do not match S15P21E102-102 §3.2 or the retention table." >&2
  exit 1
fi

echo
if (( created )) || (( retention_fixed )); then
  echo "Created $created topic(s), aligned retention on $retention_fixed; all topics now match."
else
  echo "All topics already match -102 §3.2 and the retention table."
fi
