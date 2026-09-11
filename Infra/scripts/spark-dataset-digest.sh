#!/usr/bin/env bash

# Print a deterministic content digest for one Parquet dataset.
#
# Use this to compare two runs of the same job. `hdfs dfs -checksum` compares
# file bytes, which differ between runs of an identical job because Parquet
# embeds a build string and random part-file UUIDs; this compares the rows.
#
#   INPUT=hdfs:///gitjob/demo/phase6-pre/smoke/gitjob-smoke-v1 \
#     ./Infra/scripts/spark-dataset-digest.sh

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

input="${INPUT:-${1:-}}"
[[ -n "$input" ]] || die "set INPUT=<parquet path> or pass it as the first argument"

max_rows="${MAX_ROWS:-1000000}"
[[ "$max_rows" =~ ^[1-9][0-9]*$ ]] || die "MAX_ROWS must be a positive integer"

hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"
spark_submit_network_args
spark_submit_storage_args

compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  "${SPARK_NETWORK_ARGS[@]}" \
  "${SPARK_STORAGE_ARGS[@]}" \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/dataset_digest.py \
  --input "$input" \
  --max-rows "$max_rows"
