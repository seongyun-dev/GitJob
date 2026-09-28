#!/usr/bin/env bash

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

dataset_id="${DATASET_ID:-gitjob-smoke-v1}"
dataset_multiplier="${DATASET_MULTIPLIER:-1}"
rows_per_multiplier="${ROWS_PER_MULTIPLIER:-3}"
[[ "$dataset_multiplier" =~ ^[1-9][0-9]*$ ]] || die "DATASET_MULTIPLIER must be a positive integer"
[[ "$rows_per_multiplier" =~ ^[1-9][0-9]*$ ]] || die "ROWS_PER_MULTIPLIER must be a positive integer"
hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
parquet_root="${PARQUET_ROOT:-$(env_value PARQUET_ROOT)}"
parquet_root="${parquet_root:-hdfs:///gitjob/parquet}"
output="${parquet_root%/}/smoke/${dataset_id}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"
spark_submit_network_args
spark_submit_storage_args

echo "Running dataset=${dataset_id} multiplier=${dataset_multiplier} rows_per_multiplier=${rows_per_multiplier} workers=${worker_count} output=${output}"
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  "${SPARK_NETWORK_ARGS[@]}" \
  "${SPARK_STORAGE_ARGS[@]}" \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/smoke_job.py \
  --dataset-id "$dataset_id" \
  --dataset-multiplier "$dataset_multiplier" \
  --rows-per-multiplier "$rows_per_multiplier" \
  --worker-count "$worker_count" \
  --output "$output"
