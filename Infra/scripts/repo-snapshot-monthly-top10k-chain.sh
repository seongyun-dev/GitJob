#!/usr/bin/env bash

# Detached, restart-safe monthly Top-10k Repo Artifact chain.
# Durable checkpoint/HDFS gates are authoritative; Spark application ids and
# tmux state are informational only.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"
require_core_tools
profile_enabled data || die "data profile is not enabled; use PROFILES=data"

env_value() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

raw_root="${RAW_ROOT:-$(env_value RAW_ROOT)}"
raw_root="${raw_root:-hdfs:///gitjob/raw}"
parquet_root="${PARQUET_ROOT:-$(env_value PARQUET_ROOT)}"
parquet_root="${parquet_root:-hdfs:///gitjob/parquet}"
hdfs_uri="${HDFS_URI:-$(env_value HDFS_URI)}"
hdfs_uri="${hdfs_uri:-hdfs://hdfs-namenode:8020}"
master_url="${SPARK_MASTER_URL:-$(env_value SPARK_MASTER_URL)}"
master_url="${master_url:-spark://spark-master:7077}"

run_date="${MONTHLY_ARTIFACT_RUN_DATE:-$(date -u +%Y%m%d)}"
chain_root="${MONTHLY_ARTIFACT_CHAIN_ROOT:-$REPO_ROOT/.local/gharchive-monthly-artifact}"
state_file="$chain_root/chain-state.json"
marker_root="$chain_root/pass-markers"
summary_root="$chain_root/summaries"
candidate_root="${MONTHLY_ARTIFACT_CANDIDATE_ROOT:-$REPO_ROOT/.local/repo-fetch-monthly}"
log_root="$chain_root/logs"
mkdir -p "$chain_root" "$marker_root" "$summary_root" "$candidate_root" "$log_root"

exec 9>"$chain_root/.chain.lock"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || die "monthly chain is already running: $chain_root"
fi

months=(2026-07 2026-06 2026-05 2026-04 2026-03)

month_config() {
  local month="$1"
  case "$month" in
    2026-07) expected_files=744; end_exclusive=2026-08-01T00:00:00Z; end_date=2026-07-31 ;;
    2026-06) expected_files=720; end_exclusive=2026-07-01T00:00:00Z; end_date=2026-06-30 ;;
    2026-05) expected_files=744; end_exclusive=2026-06-01T00:00:00Z; end_date=2026-05-31 ;;
    2026-04) expected_files=720; end_exclusive=2026-05-01T00:00:00Z; end_date=2026-04-30 ;;
    2026-03) expected_files=744; end_exclusive=2026-04-01T00:00:00Z; end_date=2026-03-31 ;;
    *) die "unsupported month: $month" ;;
  esac
  start="${month}-01T00:00:00Z"
  activity_snapshot="s15p21e102-194-activity-${month//-/}-${run_date}"
  artifact_snapshot="s15p21e102-194-monthly-top10k-${month//-/}-${run_date}"
  pipeline_run="s15p21e102-194-${month//-/}-${run_date}-run-001"
  activity_root="${parquet_root%/}/github/repo_activity/period=${month}/snapshot=${activity_snapshot}"
  publish_root="hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=${artifact_snapshot}"
  candidate_file="$candidate_root/$month/candidates.json"
  validation_file="$candidate_root/$month/validation.json"
  bootstrap_root="$REPO_ROOT/.local/repo-snapshot-bootstrap/$artifact_snapshot"
  bootstrap_log="$log_root/artifact-${month}.log"
  activity_log="$log_root/activity-${month}.log"
  canary_file="$candidate_root/$month/canary.json"
  canary_snapshot="s15p21e102-194-monthly-${month//-/}-canary-${run_date}"
  canary_run="s15p21e102-194-${month//-/}-canary-${run_date}-run-001"
}

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
host_df() { df -Pk "$REPO_ROOT" | tail -n 1; }

write_chain_state() {
  local month="$1" phase="$2" status="$3" candidate="$4" artifact="$5"
  local processed="$6" validation="$7" reason="$8" next_month="${9:-}"
  python3 - "$state_file" "$month" "$phase" "$status" "$candidate" "$artifact" \
    "$processed" "$validation" "$reason" "$next_month" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "month": sys.argv[2],
    "phase": sys.argv[3],
    "status": sys.argv[4],
    "candidate_snapshot": sys.argv[5] or None,
    "artifact_snapshot_id": sys.argv[6] or None,
    "current_app_id": None,
    "processed": int(sys.argv[7]),
    "last_heartbeat_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "validation_status": sys.argv[8],
    "error_reason": sys.argv[9] or None,
    "next_month": sys.argv[10] or None,
}
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_name(path.name + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, path)
PY
}

hdfs_exists() {
  compose exec -T hdfs-namenode hdfs dfs -test -e "$1"
}

hdfs_json_readable() {
  compose exec -T hdfs-namenode hdfs dfs -cat "$1" | python3 -c 'import json,sys; json.load(sys.stdin)' >/dev/null
}

run_activity() {
  if hdfs_exists "$activity_root/repo_activity/_SUCCESS" \
    && hdfs_exists "$activity_root/data_quality/_SUCCESS" \
    && hdfs_exists "$activity_root/topn_coverage/_SUCCESS"; then
    return 0
  fi
  if hdfs_exists "$activity_root"; then
    die "activity output exists but is incomplete: $activity_root"
  fi
  local container_activity_script="/tmp/gitjob-repo-activity-topn-${month//-/}.py"
  write_chain_state "$month" activity RUNNING "$activity_root" "$artifact_snapshot" 0 PENDING "" "$next_month"
  # Run through the already-running Spark worker so spark.driver.host=spark-worker
  # resolves to the driver container.  The current worktree source is copied to
  # a unique /tmp path; no service recreate or image rebuild is required.
  compose cp "$REPO_ROOT/Infra/spark/repo_activity_topn.py" \
    "spark-worker:${container_activity_script}"
  compose exec -T spark-worker /opt/spark/bin/spark-submit \
      --master "$master_url" --deploy-mode client \
      --conf spark.driver.bindAddress=0.0.0.0 \
      --conf spark.driver.host=spark-worker \
      --conf "spark.hadoop.fs.defaultFS=${hdfs_uri}" \
      "$container_activity_script" \
      --input "${raw_root%/}/gharchive/dt=${month}-*/*.json.gz" \
      --output "$activity_root" --expected-files "$expected_files" \
      --top-n "10000,20000" --period-start "$start" --period-end "$end_exclusive" \
      >"$activity_log" 2>&1
  hdfs_exists "$activity_root/repo_activity/_SUCCESS" \
    && hdfs_exists "$activity_root/data_quality/_SUCCESS" \
    && hdfs_exists "$activity_root/topn_coverage/_SUCCESS" \
    || die "activity durable gate failed: $activity_root"
}

validate_candidate() {
  python3 - "$candidate_file" "$validation_file" "$activity_root" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

candidate_path = Path(sys.argv[1])
validation_path = Path(sys.argv[2])
expected_input = sys.argv[3].rstrip("/")
payload = json.loads(candidate_path.read_text(encoding="utf-8"))
if payload.get("schema_version") != "repo-fetch-candidates/v1":
    raise SystemExit("candidate schema mismatch")
if str(payload.get("input_root", "")).rstrip("/") != expected_input:
    raise SystemExit("candidate input_root mismatch")
rows = payload.get("candidates")
if not isinstance(rows, list) or len(rows) != 10_000:
    raise SystemExit("candidate row count mismatch")
ranks = [row.get("rank") for row in rows]
if ranks != list(range(1, 10_001)):
    raise SystemExit("candidate ranks are not 1..10000")
repo_ids = [row.get("repo_id") for row in rows]
if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in repo_ids):
    raise SystemExit("candidate repo_id contains an invalid value")
if len(set(repo_ids)) != 10_000:
    raise SystemExit("candidate repo_id is not unique")
names = [row.get("repo_name") for row in rows]
if any(not isinstance(value, str) or not value.strip() or "/" not in value for value in names):
    raise SystemExit("candidate repo_name contains an invalid value")
if len({value.casefold() for value in names}) != 10_000:
    raise SystemExit("candidate repo_name.casefold is not unique")
if any(row.get("stratum") != "phase_top_10000" for row in rows):
    raise SystemExit("candidate stratum mismatch")
result = {
    "schema_version": payload["schema_version"],
    "input_root": payload["input_root"],
    "row_count": len(rows),
    "rank_min": ranks[0],
    "rank_max": ranks[-1],
    "repo_id_unique": True,
    "repo_name_casefold_unique": True,
    "stratum": "phase_top_10000",
    "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
}
validation_path.parent.mkdir(parents=True, exist_ok=True)
temporary = validation_path.with_name(validation_path.name + ".tmp")
temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, validation_path)
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
}

run_candidate() {
  if [[ -f "$candidate_file" ]]; then
    validate_candidate
    return 0
  fi
  mkdir -p "$(dirname -- "$candidate_file")"
  write_chain_state "$month" candidate RUNNING "$activity_root" "$artifact_snapshot" 0 PENDING "" "$next_month"
  ENV_FILE="$ENV_FILE" \
    COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
    PROFILES="$PROFILE_SET" \
    REPO_ACTIVITY_INPUT_ROOT="$activity_root" \
    REPO_FETCH_CANDIDATE_MODE=top-n \
    REPO_FETCH_PHASE_TOP_N=10000 \
    REPO_FETCH_CANDIDATES_OUTPUT="$candidate_file" \
    "$REPO_ROOT/Infra/scripts/spark-repo-fetch-candidates.sh" \
    >"$log_root/candidate-${month}.log" 2>&1
  validate_candidate
}

make_canary_candidate() {
  [[ -f "$canary_file" ]] && return 0
  python3 - "$candidate_file" "$canary_file" <<'PY'
import json
import os
import sys
from pathlib import Path

source = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
source["candidates"] = source["candidates"][:1]
target = Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_name(target.name + ".tmp")
temporary.write_text(json.dumps(source, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, target)
PY
}

run_bootstrap() {
  local snapshot="$1" pipeline="$2" candidate="$3" limit="$4" log="$5"
  REPO_SNAPSHOT_ID="$snapshot" \
    REPO_PIPELINE_RUN_ID="$pipeline" \
    REPO_FETCH_CANDIDATES_OUTPUT="$candidate" \
    REPO_FETCH_PHASE_TOP_N="$limit" \
    REPO_ACTIVITY_PERIOD_START="${month}-01" \
    REPO_ACTIVITY_PERIOD_END="$end_date" \
    ENV_FILE="$ENV_FILE" \
    COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
    PROFILES="$PROFILE_SET" \
    "$REPO_ROOT/Infra/scripts/repo-snapshot-bootstrap.sh" \
    >"$log" 2>&1
}

validate_bootstrap() {
  local state_path="$1" checkpoint_path="$2" limit="$3" output_root="$4"
  python3 - "$state_path" "$checkpoint_path" "$limit" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checkpoint = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
limit = int(sys.argv[3])
progress = state.get("progress") or {}
if state.get("published") is not True:
    raise SystemExit("bootstrap state is not published")
if int(progress.get("terminal", -1)) != limit or int(progress.get("total", -1)) != limit:
    raise SystemExit("bootstrap terminal progress mismatch")
rows = checkpoint.get("repos")
if not isinstance(rows, dict) or len(rows) != limit:
    raise SystemExit("checkpoint repo count mismatch")
checkpoint_counts = Counter(str(row.get("status")) for row in rows.values())
state_counts = Counter({str(key): int(value) for key, value in (progress.get("status_counts") or {}).items()})
if checkpoint_counts != state_counts:
    raise SystemExit("state/checkpoint status counts disagree")
if any(status not in {"COMPLETE", "PARTIAL", "NOT_FOUND", "FAILED", "REUSED"} for status in checkpoint_counts):
    raise SystemExit("checkpoint contains non-terminal status")
print(json.dumps(dict(sorted(checkpoint_counts.items())), sort_keys=True))
PY
  for object in snapshot.json run-summary.json failures.json _SUCCESS.json; do
    hdfs_exists "$output_root/$object" || die "missing HDFS object: $output_root/$object"
    hdfs_json_readable "$output_root/$object" || die "unreadable HDFS object: $output_root/$object"
  done
}

write_month_summary() {
  local month_name="$1" summary_path="$2" marker_path="$3" candidate_input="$4"
  local candidate_path="$5" snapshot="$6" candidate_sha="$7" started_at="$8"
  local finished_at="$9" df_before_line="${10}" df_after_line="${11}"
  local state_path="${12}" run_summary_path="${13}"
  python3 - "$month_name" "$summary_path" "$marker_path" "$candidate_input" "$candidate_path" \
    "$snapshot" "$candidate_sha" "$started_at" "$finished_at" "$df_before_line" \
    "$df_after_line" "$state_path" "$run_summary_path" <<'PY'
import json
import os
import sys
from pathlib import Path

month, summary_name, marker_name = sys.argv[1:4]
candidate_input, candidate_path = sys.argv[4:6]
snapshot, candidate_sha = sys.argv[6:8]
started_at, finished_at = sys.argv[8:10]
df_before, df_after = sys.argv[10:12]
state_path, run_summary_path = (Path(value) for value in sys.argv[12:14])
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
run_summary = (
    json.loads(run_summary_path.read_text(encoding="utf-8"))
    if run_summary_path.exists()
    else {}
)
progress = state.get("progress") or {}
summary = {
    "month": month,
    "candidate_snapshot": candidate_input,
    "candidate_file": candidate_path,
    "candidate_checksum": candidate_sha,
    "artifact_snapshot_id": snapshot,
    "started_at": started_at,
    "finished_at": finished_at,
    "runtime_seconds": run_summary.get("wall_runtime_seconds", state.get("wall_runtime_seconds")),
    "processed": progress.get("terminal"),
    "status_counts": progress.get("status_counts", {}),
    "github_api_requests": run_summary.get("actual_requests"),
    "github_core_requests": run_summary.get("actual_core_requests"),
    "github_raw_requests": run_summary.get("actual_raw_requests"),
    "rate_limit_wait_count": run_summary.get("rate_limit_wait_count", state.get("rate_limit_wait_count", 0)),
    "rate_limit_wait_seconds": run_summary.get("rate_limit_wait_seconds", state.get("rate_limit_wait_seconds", 0)),
    "hdfs_output": f"hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id={snapshot}",
    "read_back": True,
    "host_df_before": df_before,
    "host_df_after": df_after,
    "status": "PASS",
    "error_reason": None,
}
for name in (summary_name, marker_name):
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
PY
}

month=""
next_month=""
current_phase="starting"
on_error() {
  local exit_code="$?"
  set +e
  if [[ -n "$month" ]]; then
    write_chain_state "$month" "$current_phase" STOPPED "" "" 0 FAIL "exit_code=${exit_code}" "$next_month" || true
  fi
  exit "$exit_code"
}
trap on_error ERR

df_before="$(host_df)"
for index in "${!months[@]}"; do
  month="${months[$index]}"
  next_month=""
  if (( index + 1 < ${#months[@]} )); then
    next_month="${months[$((index + 1))]}"
  fi
  month_config "$month"
  marker="$marker_root/${month}.pass.json"
  summary_path="$summary_root/monthly-artifact-${month}-summary.json"
  if [[ -f "$marker" ]]; then
    write_chain_state "$month" finalized PASS "$activity_root" "$artifact_snapshot" 10000 PASS "" "$next_month"
    continue
  fi

  started_at="$(utc_now)"
  current_phase=activity
  write_chain_state "$month" activity RUNNING "$activity_root" "$artifact_snapshot" 0 PENDING "" "$next_month"
  run_activity

  current_phase=candidate
  run_candidate
  candidate_sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$candidate_file")"

  if [[ "$month" == "2026-07" ]]; then
    make_canary_candidate
    canary_state="$REPO_ROOT/.local/repo-snapshot-bootstrap/$canary_snapshot/state.json"
    canary_checkpoint="$REPO_ROOT/.local/repo-snapshot-bootstrap/$canary_snapshot/checkpoint.json"
    canary_root="hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=${canary_snapshot}"
    if [[ ! -f "$canary_state" ]] || ! hdfs_exists "$canary_root/_SUCCESS.json"; then
      current_phase=canary
      write_chain_state "$month" canary RUNNING "$candidate_file" "$canary_snapshot" 0 PENDING "" "$next_month"
      run_bootstrap "$canary_snapshot" "$canary_run" "$canary_file" 1 "$log_root/canary-${month}.log"
      validate_bootstrap "$canary_state" "$canary_checkpoint" 1 "$canary_root"
    fi
  fi

  current_phase=artifact
  write_chain_state "$month" artifact RUNNING "$candidate_file" "$artifact_snapshot" 0 PENDING "" "$next_month"
  run_bootstrap "$artifact_snapshot" "$pipeline_run" "$candidate_file" 10000 "$bootstrap_log"
  state_path="$bootstrap_root/state.json"
  checkpoint_path="$bootstrap_root/checkpoint.json"
  local_summary="$bootstrap_root/run-summary.json"
  validate_bootstrap "$state_path" "$checkpoint_path" 10000 "$publish_root"
  finished_at="$(utc_now)"
  df_after="$(host_df)"
  write_month_summary "$month" "$summary_path" "$marker" "$activity_root" "$candidate_file" \
    "$artifact_snapshot" "$candidate_sha" "$started_at" "$finished_at" "$df_before" \
    "$df_after" "$state_path" "$local_summary"
  write_chain_state "$month" finalized PASS "$candidate_file" "$artifact_snapshot" 10000 PASS "" "$next_month"
  df_before="$df_after"
done

write_chain_state "2026-03" chain COMPLETE "" "" 50000 PASS "" ""
echo "monthly Top10k Artifact chain complete"
