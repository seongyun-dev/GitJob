#!/usr/bin/env bash
#
# Run the C1 Archiver stream (S15P21E102-112).
#
# Defaults to a single micro-batch (`--once`) so the skeleton can be verified
# without leaving a query running. Set ONCE=0 for the continuous form.
#
# The Kafka connector is baked into the Spark image (Infra/docker/spark),
# so no `--packages` is passed: a restart must not depend on reaching Maven.

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

worker_count="$(compose ps -q spark-worker | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
[[ "$worker_count" =~ ^[1-9][0-9]*$ ]] || die "no running Spark worker was found"

bootstrap="${KAFKA_BOOTSTRAP_SERVERS:-$(env_value KAFKA_BOOTSTRAP_SERVERS)}"
# No fallback. This script runs where the `data` profile is enabled, and the
# data host does not run a broker at all (see compose.ec2-data.yaml) — there is
# no `kafka` to resolve there, so a default of `kafka:9092` did not stand in for
# a working endpoint, it only postponed the report. `c1_archiver_stream.py`
# already makes `--bootstrap-servers` required; filling it in unconditionally
# was what kept that check from ever running.
[[ -n "$bootstrap" ]] || die "KAFKA_BOOTSTRAP_SERVERS is not set in the environment or in $ENV_FILE"
hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
parquet_root="${PARQUET_ROOT:-$(env_value PARQUET_ROOT)}"
parquet_root="${parquet_root:-hdfs:///gitjob/parquet}"
checkpoint_root="${CHECKPOINT_ROOT:-hdfs:///gitjob/checkpoints}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"
topics="${TOPICS:-github.events,so.raw}"
max_offsets="${MAX_OFFSETS_PER_TRIGGER:-10000}"
once="${ONCE:-1}"
spark_submit_network_args
spark_submit_storage_args

args=(
  --bootstrap-servers "$bootstrap"
  --topics "$topics"
  --parquet-root "$parquet_root"
  --checkpoint-root "$checkpoint_root"
  --max-offsets-per-trigger "$max_offsets"
)
[[ "$once" == "1" ]] && args+=(--once)

echo "C1 archiver: topics=${topics} bootstrap=${bootstrap} out=${parquet_root}/stream once=${once}"
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  "${SPARK_NETWORK_ARGS[@]}" \
  "${SPARK_STORAGE_ARGS[@]}" \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/c1_archiver_stream.py \
  "${args[@]}"
