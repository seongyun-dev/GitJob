#!/usr/bin/env bash

# Phase 9 step 1: force a real shuffle across the two-host Spark cluster without
# touching HDFS. Use this before the HDFS canary so a failure points at the
# Spark network boundary rather than at storage.
#
#   ./Infra/scripts/spark-shuffle-canary.sh
#   CANARY_PARTITIONS=16 CANARY_ROWS_PER_PARTITION=50000 ./Infra/scripts/spark-shuffle-canary.sh

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=core,app,data"

env_value() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

partitions="${CANARY_PARTITIONS:-8}"
rows_per_partition="${CANARY_ROWS_PER_PARTITION:-25000}"
# Not GROUPS: bash defines that as a readonly array of the caller's group IDs,
# so `${GROUPS:-64}` silently yields the primary GID instead of the default.
groups="${CANARY_GROUPS:-64}"
min_hosts="${CANARY_MIN_HOSTS:-2}"
for value in "$partitions" "$rows_per_partition" "$groups" "$min_hosts"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] \
    || die "CANARY_PARTITIONS/CANARY_ROWS_PER_PARTITION/CANARY_GROUPS/CANARY_MIN_HOSTS must be positive integers"
done
[[ "$rows_per_partition" -ge "$groups" ]] \
  || die "CANARY_ROWS_PER_PARTITION must be at least CANARY_GROUPS"
[[ "$min_hosts" -le "$partitions" ]] \
  || die "CANARY_MIN_HOSTS cannot exceed CANARY_PARTITIONS"

master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"
spark_submit_network_args
spark_submit_storage_args

# No --conf spark.hadoop.fs.defaultFS here on purpose: this canary must not
# depend on HDFS being reachable.
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  "${SPARK_NETWORK_ARGS[@]}" \
  "${SPARK_STORAGE_ARGS[@]}" \
  /opt/gitjob/spark/shuffle_canary.py \
  --partitions "$partitions" \
  --rows-per-partition "$rows_per_partition" \
  --groups "$groups" \
  --min-hosts "$min_hosts"
