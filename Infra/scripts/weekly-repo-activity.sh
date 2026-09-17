#!/usr/bin/env bash
#
# Run the weekly Repo Activity aggregation and keep its summary (S15P21E102-231).
#
# `jobs/repo_activity_weekly.py` has been runnable since `-166` and gained the
# streaming reader in `-224`, but nothing in `Infra/scripts` called it. The
# operator had to assemble the `compose exec` line by hand every time, and the
# summary JSON — which `-225`'s manifest needs the row digests from — went to a
# terminal instead of a file.
#
# ## Why the summary has to land on the host
#
# The job prints one JSON object holding, per week, the `uri`, `row_count` and
# `row_digest` it verified during read-back. `weekly-snapshot-publish.sh` reads
# exactly that file. Losing it means the digests would have to be recomputed
# with a second full scan of the same Parquet, which is the cost the split
# between the Spark and worker images was arranged to avoid.
#
# So this redirects stdout to a file and prints only progress on stderr.
#
#   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
#   PROFILES=data \
#   WEEKLY_SNAPSHOT_ID=s15p21e102-224-stream-20260913 \
#   WEEKLY_PERIOD=2026-09 \
#   WEEKLY_INPUT_FORMAT=stream-parquet \
#   WEEKLY_PERIOD_START=2026-09-01T00:00:00Z \
#   WEEKLY_PERIOD_END=2026-10-01T00:00:00Z \
#     ./Infra/scripts/weekly-repo-activity.sh

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

snapshot_id="${WEEKLY_SNAPSHOT_ID:-}"
[[ -n "$snapshot_id" ]] || die "WEEKLY_SNAPSHOT_ID is required"
# The id becomes a path segment and the publisher checks the manifest against
# it, so refuse anything that would not survive that round trip.
[[ "$snapshot_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || die "WEEKLY_SNAPSHOT_ID must be a safe path component: $snapshot_id"

period="${WEEKLY_PERIOD:-}"
[[ "$period" =~ ^[0-9]{4}-[0-9]{2}$ ]] || die "WEEKLY_PERIOD must be YYYY-MM: ${period:-<unset>}"

input_format="${WEEKLY_INPUT_FORMAT:-raw-json}"
case "$input_format" in
  raw-json | stream-parquet | transition | recovery-raw-json) ;;
  *) die "unsupported WEEKLY_INPUT_FORMAT: $input_format" ;;
esac

hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
parquet_root="${PARQUET_ROOT:-$(env_value PARQUET_ROOT)}"
parquet_root="${parquet_root:-hdfs:///gitjob/parquet}"
raw_root="${RAW_ROOT:-$(env_value RAW_ROOT)}"
raw_root="${raw_root:-hdfs:///gitjob/raw}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"

# The two readers default to different roots; neither default chains to the
# other, so the input is resolved here rather than left to the job.
if [[ "$input_format" == "stream-parquet" ]]; then
  input="${WEEKLY_INPUT:-${parquet_root%/}/stream/github.events}"
elif [[ "$input_format" == "raw-json" ]]; then
  input="${WEEKLY_INPUT:-${raw_root%/}/gharchive/dt=${period}-*/*.json.gz}"
else
  input=""
fi

output="${WEEKLY_OUTPUT:-${parquet_root%/}/github/repo_activity_weekly/period=${period}/snapshot=${snapshot_id}}"
period_start="${WEEKLY_PERIOD_START:-${period}-01T00:00:00Z}"
period_end="${WEEKLY_PERIOD_END:-}"
[[ -n "$period_end" ]] || die "WEEKLY_PERIOD_END is required (exclusive, hour-aligned UTC)"

state_root="${WEEKLY_STATE_ROOT:-$REPO_ROOT/.local/weekly-repo-activity}"
mkdir -p "$state_root"
summary_file="$state_root/${snapshot_id}-summary.json"
log_file="$state_root/${snapshot_id}.log"
[[ ! -e "$summary_file" ]] \
  || die "summary already exists for this snapshot id: $summary_file"

args=(
  --input-format "$input_format"
  --output "$output"
  --period-start "$period_start"
  --period-end "$period_end"
)
if [[ -n "$input" ]]; then
  args+=(--input "$input")
fi
# Raw counts its hourly files; the stream gate is hour coverage and ignores
# this, so it is only passed on the path that uses it.
if [[ "$input_format" == "raw-json" ]]; then
  args+=(--expected-files "${WEEKLY_EXPECTED_FILES:-744}")
elif [[ "$input_format" == "transition" ]]; then
  raw_input="${WEEKLY_RAW_INPUT:-}"
  stream_input="${WEEKLY_STREAM_INPUT:-}"
  [[ -n "$raw_input" ]] || die "WEEKLY_RAW_INPUT is required for transition"
  [[ -n "$stream_input" ]] || die "WEEKLY_STREAM_INPUT is required for transition"
  args+=(--raw-input "$raw_input" --stream-input "$stream_input")
elif [[ "$input_format" == "recovery-raw-json" ]]; then
  recovery_manifest="${WEEKLY_RECOVERY_MANIFEST:-}"
  [[ "$recovery_manifest" == /* ]] \
    || die "WEEKLY_RECOVERY_MANIFEST must be an absolute path inside spark-worker"
  args+=(--recovery-manifest "$recovery_manifest")
fi
# `LABEL=PATH`, repeatable. Space-separated here because a cron line cannot
# carry an array.
for cohort in ${WEEKLY_JOIN_IDS:-}; do
  args+=(--join-ids "$cohort")
done

spark_submit_network_args
spark_submit_storage_args

{
  echo "weekly repo activity: format=${input_format} snapshot=${snapshot_id}"
  if [[ "$input_format" == "recovery-raw-json" ]]; then
    echo "  manifest: ${recovery_manifest}"
  elif [[ "$input_format" == "transition" ]]; then
    echo "  raw input:    ${raw_input}"
    echo "  stream input: ${stream_input}"
  else
    echo "  input:  ${input}"
  fi
  echo "  output: ${output}"
  echo "  period: ${period_start} .. ${period_end}"
} >&2

set +e
compose exec -T spark-worker \
  /opt/spark/bin/spark-submit \
  --master "$master_url" \
  --deploy-mode client \
  "${SPARK_NETWORK_ARGS[@]}" \
  "${SPARK_STORAGE_ARGS[@]}" \
  --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
  /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  "${args[@]}" \
  >"$summary_file" 2>"$log_file"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
  # A failed run leaves no usable summary; removing it keeps the publisher from
  # being handed a truncated file that happens to parse.
  rm -f "$summary_file"
  echo "weekly repo activity failed (exit ${status}); see ${log_file}" >&2
  exit "$status"
fi

echo "summary: ${summary_file}" >&2
echo "log:     ${log_file}" >&2
exit 0
