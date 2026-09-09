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

hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
raw_root="${RAW_ROOT:-$(env_value RAW_ROOT)}"
raw_root="${raw_root:-hdfs:///gitjob/raw}"
parquet_root="${PARQUET_ROOT:-$(env_value PARQUET_ROOT)}"
parquet_root="${parquet_root:-hdfs:///gitjob/parquet}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"

input_path="${GHARCHIVE_RAW_INPUT:-${raw_root%/}/gharchive/dt=2026-08-*/*.json.gz}"
output_path="${REPO_ACTIVITY_OUTPUT:-${parquet_root%/}/github/repo_activity/period=2026-08/snapshot=s15p21e102-109-baseline}"
expected_files="${GHARCHIVE_EXPECTED_FILES:-744}"
top_n="${REPO_ACTIVITY_TOP_N:-100,500,1000,3000,5000,10000,20000}"

echo "Running GH Archive Repo Activity input=${input_path} output=${output_path} expected_files=${expected_files}"
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  --conf spark.driver.bindAddress=0.0.0.0 \
  --conf spark.driver.host=spark-worker \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/repo_activity_topn.py \
  --input "$input_path" \
  --output "$output_path" \
  --expected-files "$expected_files" \
  --top-n "$top_n"
