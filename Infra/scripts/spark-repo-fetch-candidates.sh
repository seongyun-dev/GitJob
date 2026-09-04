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
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"
input_root="${REPO_ACTIVITY_INPUT_ROOT:-hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=s15p21e102-109-20260902}"
coverage_n="${REPO_FETCH_COVERAGE_N:-20000,50000,100000,200000,300000,500000}"
sample_size="${REPO_FETCH_SAMPLE_SIZE:-50}"
candidate_mode="${REPO_FETCH_CANDIDATE_MODE:-stratified}"
phase_top_n="${REPO_FETCH_PHASE_TOP_N:-20000}"
host_output="${REPO_FETCH_CANDIDATES_OUTPUT:-$REPO_ROOT/.local/repo-fetch-benchmark/candidates.json}"
container_output="/tmp/gitjob-repo-fetch-candidates.json"

mkdir -p "$(dirname -- "$host_output")"

echo "Reading immutable Repo Activity input=${input_root} candidate_mode=${candidate_mode}"
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  --conf spark.driver.bindAddress=0.0.0.0 \
  --conf spark.driver.host=spark-worker \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/repo_fetch_candidates.py \
  --input-root "$input_root" \
  --coverage-n "$coverage_n" \
  --sample-size "$sample_size" \
  --candidate-mode "$candidate_mode" \
  --phase-top-n "$phase_top_n" \
  --output "$container_output"

compose cp "spark-worker:${container_output}" "$host_output"
echo "Candidate summary copied to ${host_output}"
