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

# The benchmark scales multiple workers inside one Compose project. In the
# two-host layout every worker has a fixed host-network RPC/UI port, so local
# --scale would collide and no longer measure the intended topology.
cluster_data_ip="${DATA_TS_IP:-$(env_value DATA_TS_IP)}"
[[ -z "$cluster_data_ip" ]] \
  || die "spark-benchmark.sh --scale is single-host only; run the Phase 9 two-host canary instead"

worker_values="${BENCHMARK_WORKERS:-1,2,4}"
dataset_values="${BENCHMARK_DATASET_MULTIPLIERS:-1,2,4}"
repeat_count="${BENCHMARK_REPEATS:-3}"
rows_per_multiplier="${BENCHMARK_ROWS_PER_MULTIPLIER:-1000}"
dataset_prefix="${BENCHMARK_DATASET_ID:-gitjob-benchmark-v1}"
output_file="${BENCHMARK_OUTPUT:-$REPO_ROOT/.local/benchmarks/spark-$(date -u +%Y%m%dT%H%M%SZ).tsv}"

[[ "$repeat_count" =~ ^[1-9][0-9]*$ ]] || die "BENCHMARK_REPEATS must be a positive integer"
[[ "$rows_per_multiplier" =~ ^[1-9][0-9]*$ ]] || die "BENCHMARK_ROWS_PER_MULTIPLIER must be a positive integer"

IFS=',' read -r -a worker_counts <<< "$worker_values"
IFS=',' read -r -a dataset_multipliers <<< "$dataset_values"

for value in "${worker_counts[@]}" "${dataset_multipliers[@]}"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "benchmark dimensions must contain positive integers"
done

mkdir -p "$(dirname -- "$output_file")"
summary_file="${output_file%.tsv}.summary.tsv"
printf 'worker_count\tdataset_multiplier\trepeat\tstatus\tduration_ms\trow_count\tspark_version\tdataset_id\tdataset_hash\n' > "$output_file"
printf 'worker_count\tdataset_multiplier\tsuccessful_runs\tfailure_count\tp50_ms\tp95_ms\trows_per_sec_at_p50\tspark_version\tdataset_hash\n' > "$summary_file"

wait_for_workers() {
  local expected="$1"
  local -a ids=()
  local all_healthy
  local id
  local health

  for _ in $(seq 1 "${BENCHMARK_WORKER_WAIT_ATTEMPTS:-60}"); do
    mapfile -t ids < <(compose ps -q spark-worker | sed '/^[[:space:]]*$/d')
    if [[ "${#ids[@]}" -eq "$expected" ]]; then
      all_healthy=true
      for id in "${ids[@]}"; do
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$id")"
        if [[ "$health" != healthy ]]; then
          all_healthy=false
          break
        fi
      done
      if [[ "$all_healthy" == true ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  compose ps spark-worker >&2 || true
  return 1
}

percentile() {
  local percentile_value="$1"
  shift
  printf '%s\n' "$@" | sort -n | awk -v p="$percentile_value" ' {
    values[NR] = $1
  } END {
    position = int((NR * p) + 0.999999)
    if (position < 1) position = 1
    if (position > NR) position = NR
    print values[position]
  }'
}

for worker_count in "${worker_counts[@]}"; do
  echo "Scaling Spark workers to ${worker_count}..."
  compose up -d --scale "spark-worker=${worker_count}" spark-worker >/dev/null
  wait_for_workers "$worker_count" || die "Spark workers did not become healthy: ${worker_count}"

  for dataset_multiplier in "${dataset_multipliers[@]}"; do
    dataset_id="${dataset_prefix}-d${dataset_multiplier}"
    dataset_spec="${dataset_id}:${dataset_multiplier}:${rows_per_multiplier}"
    dataset_hash="$(printf '%s' "$dataset_spec" | sha256sum | awk '{print $1}')"
    durations=()
    successful_runs=0
    failure_count=0
    row_count='-'
    spark_version='-'

    for repeat in $(seq 1 "$repeat_count"); do
      start_ns="$(date +%s%N)"
      set +e
      result="$(DATASET_ID="$dataset_id" DATASET_MULTIPLIER="$dataset_multiplier" ROWS_PER_MULTIPLIER="$rows_per_multiplier" "$SCRIPT_DIR/spark-smoke.sh" 2>&1)"
      exit_code=$?
      set -e
      end_ns="$(date +%s%N)"
      duration_ms=$(( (end_ns - start_ns) / 1000000 ))
      json_line="$(printf '%s\n' "$result" | sed -n '/^{.*}$/p' | tail -n 1)"
      current_row_count="$(printf '%s' "$json_line" | sed -n 's/.*"row_count": \([0-9][0-9]*\).*/\1/p')"
      current_spark_version="$(printf '%s' "$json_line" | sed -n 's/.*"spark_version": "\([^"]*\)".*/\1/p')"

      if [[ "$exit_code" -eq 0 && -n "$current_row_count" && -n "$current_spark_version" ]]; then
        status=success
        successful_runs=$((successful_runs + 1))
        durations+=("$duration_ms")
        row_count="$current_row_count"
        spark_version="$current_spark_version"
      else
        status=failed
        failure_count=$((failure_count + 1))
        echo "$result" >&2
      fi

      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$worker_count" "$dataset_multiplier" "$repeat" "$status" "$duration_ms" \
        "${current_row_count:--}" "${current_spark_version:--}" "$dataset_id" "$dataset_hash" \
        >> "$output_file"
    done

    if [[ "$successful_runs" -gt 0 ]]; then
      p50_ms="$(percentile 0.50 "${durations[@]}")"
      p95_ms="$(percentile 0.95 "${durations[@]}")"
      rows_per_sec="$(awk -v rows="$row_count" -v duration="$p50_ms" 'BEGIN { if (duration > 0) printf "%.3f", rows * 1000 / duration; else print "-" }')"
    else
      p50_ms='-'
      p95_ms='-'
      rows_per_sec='-'
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$worker_count" "$dataset_multiplier" "$successful_runs" "$failure_count" \
      "$p50_ms" "$p95_ms" "$rows_per_sec" "$spark_version" "$dataset_hash" \
      >> "$summary_file"
  done
done

echo "Benchmark results: $output_file"
echo "Benchmark summary: $summary_file"

if awk -F '\t' 'NR > 1 && $4 > 0 { failed = 1 } END { exit failed }' "$summary_file"; then
  exit 0
fi
exit 1
