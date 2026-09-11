#!/usr/bin/env bash

# Reports whether the deployed services can actually do their work.
#
# healthcheck.sh answers a different question: it asks whether containers are up.
# That is not the same thing, and the gap has bitten us. kafka-connect's healthcheck
# returns 200 with zero connectors registered, and the worker's /health never touches
# the database, so a deployment goes green while the analysis pipeline publishes
# nothing. This script asks the second question and says what to run when the answer
# is no.
#
# Three outcomes, and the difference between the last two matters:
#   OK      ready
#   SKIP    deliberately switched off by configuration; not a problem
#   ACTION  a human step is missing; the remedy is printed at the end
#
# Every check runs inside the container that already holds the credentials, so this
# script never reads or prints a secret.
#
# Usage mirrors healthcheck.sh:
#   ./Infra/scripts/verify-deployment.sh
#   ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
#     PROFILES=core,app ./Infra/scripts/verify-deployment.sh
#
# Checks are skipped when their service is not part of this host's profiles, so the
# same command is valid on the service host and the data host.
#
# VERIFY_TIMEOUT_SECONDS re-runs the checks until they pass or the budget runs out.
# It defaults to 0, a single pass, because a person running this wants an answer now.
# deploy.sh sets it, because a connector registered moments earlier reports RUNNING
# with no tasks yet, and that would read as a failure.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

action_count=0
error_count=0
remedies=()

report() { printf '%-22s %-7s %s\n' "$1" "$2" "${3:-}"; }
ok() { report "$1" OK "${2:-}"; }
skip() { report "$1" SKIP "${2:-}"; }
needs_action() {
  report "$1" ACTION "$2"
  action_count=$((action_count + 1))
  [[ -n "${3:-}" ]] && remedies+=("$1"$'\n'"$3")
  return 0
}
undetermined() {
  report "$1" ERROR "$2"
  error_count=$((error_count + 1))
  return 0
}

# Same resolution cdc-register.sh uses, so both scripts agree on the connector name.
read_env() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1
}

running() {
  local service="$1"
  [[ -n "$(service_container_id "$service" 2>/dev/null)" ]]
}

# The query text travels as an environment variable so that no quoting of ours ends
# up inside the container's shell, and so credentials stay in the container.
psql_query() {
  compose exec -T -e VERIFY_SQL="$1" postgres \
    sh -c 'psql -tAX -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$VERIFY_SQL"' 2>/dev/null \
    | tr -d '\r'
}

# Fed to `python -` on stdin so that none of our quoting has to survive a trip
# through the container's shell. The password is read from the container's own
# environment and never reaches this script. Kept outside run_all_checks: indenting
# it along with the function body would make Python reject it.
C_COMPUTE_SCHEMA_PROBE='
import os, sys
try:
    import psycopg
    dsn = "postgresql://%s:%s@%s:%s/%s" % (
        os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"],
        os.environ["POSTGRES_HOST"], os.environ["POSTGRES_PORT"], os.environ["POSTGRES_DB"])
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        row = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
            ("c_compute",)).fetchone()
    print(row[0])
except Exception:
    sys.exit(1)
'

run_all_checks() {
  action_count=0
  error_count=0
  remedies=()

  outbox_mode="$(read_env ANALYSIS_OUTBOX_MODE)"
  # application.yaml and compose.yaml both default this to CDC, so an unset value means CDC.
  outbox_mode="${outbox_mode:-CDC}"

  echo "env file: $ENV_FILE"
  echo "profiles: $PROFILE_SET"
  echo

  # --- schema -----------------------------------------------------------------
  # Flyway runs inside the backend at startup, so this doubles as evidence that a
  # backend carrying the current migrations actually started against this database.
  if profile_enabled core; then
    if ! running postgres; then
      undetermined schema "postgres 컨테이너가 이 호스트에 없다"
    else
      history_present="$(psql_query "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='flyway_schema_history'")"
      if [[ "$history_present" != "1" ]]; then
        needs_action schema "flyway_schema_history 없음 — 마이그레이션이 한 번도 적용되지 않았다" \
          "backend를 기동한다. Flyway는 backend 시작 시 실행된다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core,app ./Infra/scripts/up.sh
  기동에 실패하면 backend 로그의 flywayInitializer 항목을 먼저 확인한다."
      else
        failed="$(psql_query "SELECT count(*) FROM flyway_schema_history WHERE success = false")"
        if [[ "${failed:-0}" != "0" ]]; then
          # Flyway refuses to run again while a failed row is present, so restarting
          # the backend cannot clear this by itself.
          needs_action schema "실패한 마이그레이션 ${failed}건 — 재기동으로는 해소되지 않는다" \
            "실패한 버전을 확인하고, 원인을 고친 뒤 이력에서 제거한다.
    SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank;
  부분 적용된 DDL을 직접 되돌린 다음 실패 행을 지워야 다음 기동에서 재시도한다."
        else
          latest="$(psql_query "SELECT version || ' ' || description FROM flyway_schema_history WHERE success ORDER BY installed_rank DESC LIMIT 1")"
          ok schema "최신 ${latest:-unknown}"
        fi
      fi
    fi
  else
    skip schema "core 프로필이 이 호스트에 없다"
  fi

  # --- Kafka topic contract --------------------------------------------------
  if ! profile_enabled core; then
    skip kafka-topics "core 프로필이 이 호스트에 없다"
  elif ! running kafka; then
    undetermined kafka-topics "kafka 컨테이너가 이 호스트에 없다"
  else
    if kafka_topic_check="$($SCRIPT_DIR/kafka-topics.sh --check 2>&1)"; then
      ok kafka-topics "필수 topic과 partition 계약 일치"
    else
      needs_action kafka-topics "필수 topic 검증 실패" \
        "service 호스트에서 확인·생성한다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core \\
      ./Infra/scripts/kafka-topics.sh"
    fi
  fi

  # --- CDC database objects ---------------------------------------------------
  # cdc_heartbeat comes from a migration; the role and the publication do not, because
  # they need a password substituted in and cannot be re-run. See db/README.md.
  if ! profile_enabled core; then
    skip cdc-objects "core 프로필이 이 호스트에 없다"
  elif [[ "$outbox_mode" != "CDC" ]]; then
    skip cdc-objects "ANALYSIS_OUTBOX_MODE=$outbox_mode — CDC를 쓰지 않는다"
  elif ! running postgres; then
    undetermined cdc-objects "postgres 컨테이너가 이 호스트에 없다"
  else
    cdc_state="$(psql_query "SELECT current_setting('wal_level')
        || ':' || coalesce((SELECT 'y' FROM pg_roles WHERE rolname='gitjob_cdc'), 'n')
        || ':' || coalesce((SELECT 'y' FROM pg_publication WHERE pubname='gitjob_analysis_outbox_pub'), 'n')
        || ':' || coalesce((SELECT 'y' FROM information_schema.tables WHERE table_schema='public' AND table_name='cdc_heartbeat'), 'n')")"
    IFS=':' read -r wal role publication heartbeat <<< "${cdc_state:-::::}"
    cdc_remedy="Flyway 적용이 끝난 뒤 한 번만 실행한다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core \\
      ./Infra/scripts/cdc-apply-prerequisites.sh"
    if [[ "$heartbeat" != "y" ]]; then
      needs_action cdc-objects "cdc_heartbeat 없음 — 마이그레이션이 먼저다" \
        "schema 항목을 먼저 해결한다. cdc_heartbeat는 V2 마이그레이션이 만든다."
    elif [[ "$wal" != "logical" ]]; then
      # Restart-only setting; compose sets it, so an old container is the usual cause.
      needs_action cdc-objects "wal_level=$wal — logical 이어야 한다" \
        "postgres 컨테이너가 새 compose 설정으로 재생성되어야 한다. command 가 바뀌었으므로 up 하면 재생성된다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core ./Infra/scripts/up.sh"
    elif [[ "$role" != "y" || "$publication" != "y" ]]; then
      needs_action cdc-objects "role=$role publication=$publication — 전제조건 미적용" "$cdc_remedy"
    else
      ok cdc-objects "wal_level=logical, 역할·publication·heartbeat 존재"
    fi
  fi

  # --- Debezium connector -----------------------------------------------------
  # The container healthcheck only asks whether the REST API answers, and it answers
  # with an empty list, so registration has to be checked separately.
  connector_name="${CDC_CONNECTOR_NAME:-$(read_env CDC_CONNECTOR_NAME)}"
  connector_name="${connector_name:-analysis-outbox}"

  if ! profile_enabled core; then
    skip cdc-connector "core 프로필이 이 호스트에 없다"
  elif [[ "$outbox_mode" != "CDC" ]]; then
    skip cdc-connector "ANALYSIS_OUTBOX_MODE=$outbox_mode — CDC를 쓰지 않는다"
  elif ! running kafka-connect; then
    undetermined cdc-connector "kafka-connect 컨테이너가 이 호스트에 없다"
  else
    # Ask inside the container: the EC2 override publishes no host port for Connect.
    connector_status="$(compose exec -T -e CONNECTOR="$connector_name" kafka-connect sh -c '
      code=$(curl -sS -o /tmp/verify-connector.json -w "%{http_code}" \
        "http://localhost:8083/connectors/$CONNECTOR/status" 2>/dev/null || echo 000)
      printf "%s " "$code"
      tr -d "\n" < /tmp/verify-connector.json 2>/dev/null
      rm -f /tmp/verify-connector.json
    ' 2>/dev/null | tr -d '\r')"
    connector_code="${connector_status%% *}"
    connector_body="${connector_status#* }"
    register_remedy="ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core ./Infra/scripts/cdc-register.sh"
    case "$connector_code" in
      404)
        needs_action cdc-connector "커넥터 '$connector_name' 미등록" "$register_remedy" ;;
      200)
        # A connector can report RUNNING while its task has died, which is the state
        # that silently stops delivery, so both are inspected.
        if [[ "$connector_body" != *'"state":"RUNNING"'* ]]; then
          needs_action cdc-connector "커넥터가 RUNNING 이 아니다: $connector_body" "$register_remedy"
        elif [[ "$connector_body" == *'"tasks":[]'* ]]; then
          needs_action cdc-connector "커넥터는 RUNNING 이지만 task 가 없다" "$register_remedy"
        elif [[ "$connector_body" == *'FAILED'* ]]; then
          needs_action cdc-connector "task 가 FAILED: $connector_body" \
            "먼저 로그에서 원인을 본다. 재등록만으로는 같은 이유로 다시 실패한다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=core \\
      ./Infra/scripts/logs.sh kafka-connect 2>/dev/null || docker logs --tail=200 \$(docker ps -qf name=kafka-connect)
  원인을 고친 뒤 재등록한다.
    $register_remedy"
        else
          ok cdc-connector "'$connector_name' RUNNING"
        fi ;;
      *)
        undetermined cdc-connector "Connect API 응답 코드 $connector_code" ;;
    esac
  fi

  # --- entry point ------------------------------------------------------------
  # The container healthcheck for nginx did not save us on 2026-09-09: a deploy
  # recreated backend, nginx kept using the address it had resolved at startup, and
  # the deploy passed because nginx had not yet exhausted its retry budget. It then
  # served 502 for two hours. This asks the question the healthcheck's timing can
  # miss — does a request actually reach the backend through nginx right now.
  if ! profile_enabled app; then
    skip entry-point "app 프로필이 이 호스트에 없다"
  elif ! running nginx; then
    undetermined entry-point "nginx 컨테이너가 이 호스트에 없다"
  else
    entry_status="$(compose exec -T nginx sh -c '
      code=$(wget -q -O /tmp/verify-entry.out -T 5 -S http://127.0.0.1/health 2>&1 \
        | awk "/HTTP\\//{print \$2; exit}") || true
      printf "%s " "${code:-000}"
      tr -d "\n" < /tmp/verify-entry.out 2>/dev/null
      rm -f /tmp/verify-entry.out
    ' 2>/dev/null | tr -d '\r' || true)"
    entry_code="${entry_status%% *}"
    entry_body="${entry_status#* }"
    if [[ "$entry_body" == *'"status":"UP"'* ]]; then
      ok entry-point "nginx → backend /health UP"
    elif [[ "$entry_code" == "502" || "$entry_code" == "504" ]]; then
      # The usual cause is a stale upstream address, which a restart clears.
      needs_action entry-point "nginx 가 backend 에 도달하지 못한다 (HTTP $entry_code)" \
        "backend 는 살아 있는데 nginx 만 못 붙는 경우, upstream 주소가 낡았을 수 있다. 먼저 확인한다.
  docker exec \$(docker ps -qf name=nginx) sh -c 'wget -q -O- -T3 http://backend:8080/actuator/health'
위가 성공하는데 127.0.0.1/health 가 502 면 nginx 를 재시작한다.
  docker restart \$(docker ps -qf name=nginx)
재발한다면 Infra/nginx 의 resolver 설정이 적용되었는지 확인한다."
    else
      undetermined entry-point "예상하지 못한 응답: code=$entry_code body=$entry_body"
    fi
  fi

  # --- C compute worker -------------------------------------------------------
  # /health says the process is up. /ready is the one that looks at the database.
  if ! profile_enabled data; then
    skip worker-ready "data 프로필이 이 호스트에 없다"
  elif ! running worker; then
    undetermined worker-ready "worker 컨테이너가 이 호스트에 없다"
  else
    ready_status="$(compose exec -T worker sh -c '
      code=$(curl -sS -o /tmp/verify-ready.json -w "%{http_code}" \
        -H "Authorization: Bearer $C_COMPUTE_TOKEN" \
        http://localhost:8080/ready 2>/dev/null || echo 000)
      printf "%s " "$code"
      tr -d "\n" < /tmp/verify-ready.json 2>/dev/null
      rm -f /tmp/verify-ready.json
    ' 2>/dev/null | tr -d '\r')"
    ready_code="${ready_status%% *}"
    ready_body="${ready_status#* }"
    case "$ready_code" in
      200)
        ok worker-ready "C compute 준비됨" ;;
      503)
        if [[ "$ready_body" == *C_COMPUTE_NOT_CONFIGURED* ]]; then
          # .env.example: "Empty means computation APIs are disabled." Reporting this
          # as a failure would send the next person chasing a bug that is not there.
          #
          # But the auth check runs before the schema check, so a disabled token hides
          # whether the migration was ever applied. That is exactly how a data host was
          # left without its c_compute schema after a deployment: everything read SKIP.
          # Ask the database directly so the two states stay distinguishable.
          # A probe failure must not end the run: pipefail would turn it into an exit.
          c_compute_tables="$(printf '%s\n' "$C_COMPUTE_SCHEMA_PROBE" \
            | compose exec -T worker python - 2>/dev/null | tr -d '\r' || true)"
          if [[ "$c_compute_tables" =~ ^[0-9]+$ && "$c_compute_tables" -gt 0 ]]; then
            skip worker-ready "C_COMPUTE_TOKEN 미설정 — 계산 API가 설계상 비활성 (스키마는 적용됨)"
          elif [[ "$c_compute_tables" == "0" ]]; then
            needs_action worker-ready "API는 설계상 비활성이지만 c_compute 스키마가 없다" \
              "토큰을 켜기 전에 미리 적용해 두는 편이 낫다. 재실행해도 안전하다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=data \\
      ./Infra/scripts/c-compute-migrate.sh"
          else
            skip worker-ready "C_COMPUTE_TOKEN 미설정 — 계산 API가 설계상 비활성 (스키마 확인 불가)"
          fi
        elif [[ "$ready_body" == *C_REGISTRY_UNAVAILABLE* ]]; then
          needs_action worker-ready "Registry 미준비 — 승인 snapshot과 Worker 시작 로그 확인 필요" \
            "Registry V11 migration, 승인 C snapshot import/alias 활성화를 확인한다.
    docs/data/technology-registry-db.md의 B/C 전환 순서에 따라 Worker를 재시작하고,
    C /registry의 version/hash를 승인 import와 비교한다. B CURRENT는 별도이며 연결 전 호환을 확인한다.
    이후 완료 공고 입력을 새 event로 처리하여 /job-cohorts/resolve 성공까지 확인한다.
    /health 성공만으로 분석 트래픽을 열지 않는다."
        elif [[ "$ready_body" == *C_MIGRATION_REQUIRED* ]]; then
          needs_action worker-ready "c_compute 스키마 없음" \
            "worker 컨테이너 안에서 실행한다. 컨테이너가 이미 가진 값으로 DSN을 만들므로 env 파일에 추가할 것은 없다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=data \\
      ./Infra/scripts/c-compute-migrate.sh"
        else
          undetermined worker-ready "503 이지만 알 수 없는 본문: $ready_body"
        fi ;;
      401)
        undetermined worker-ready "401 — 컨테이너 자신의 토큰으로 호출했는데 거부됐다" ;;
      404)
        # /ready 는 C compute 와 함께 들어왔다. 없다는 것은 이미지가 그보다 오래됐다는 뜻이다.
        undetermined worker-ready "404 — 이 worker 이미지에는 /ready 가 없다. 배포되지 않은 구버전이다" ;;
      *)
        undetermined worker-ready "응답 코드 $ready_code" ;;
    esac
  fi

  # --- Repository analysis consumer -----------------------------------------
  # This process has no HTTP endpoint. Its startup checks Kafka, PostgreSQL,
  # repo_analysis.event_claim and tree-sitter grammars before entering the
  # consumer loop, so a stable running state is its readiness contract.
  if ! profile_enabled data; then
    skip analysis-worker-ready "data 프로필이 이 호스트에 없다"
  else
    analysis_worker_id="$(service_container_id analysis-worker 2>/dev/null || true)"
    if [[ -z "$analysis_worker_id" ]]; then
      needs_action analysis-worker-ready "analysis-worker 컨테이너가 없다" \
        "data profile 배포와 repo_analysis migration 적용 여부를 확인한다."
    else
      analysis_worker_status="$(docker inspect --format '{{.State.Status}}' "$analysis_worker_id" 2>/dev/null || true)"
      analysis_worker_restarts="$(docker inspect --format '{{.RestartCount}}' "$analysis_worker_id" 2>/dev/null || true)"
      if [[ "$analysis_worker_status" == "running" ]]; then
        ok analysis-worker-ready "repository analysis consumer 실행 중 (restarts=${analysis_worker_restarts:-unknown})"
      else
        needs_action analysis-worker-ready \
          "analysis-worker 상태=${analysis_worker_status:-unknown}, restarts=${analysis_worker_restarts:-unknown}" \
          "로그를 확인한다.
    docker logs --tail 100 $analysis_worker_id
repo_analysis.event_claim 누락이면 service 호스트에서 실행한다.
    ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core \\
      ./Infra/scripts/repo-analysis-migrate.sh"
      fi
    fi
  fi
}

timeout_seconds="${VERIFY_TIMEOUT_SECONDS:-0}"
deadline=$((SECONDS + timeout_seconds))
checks_output="$(mktemp)"
trap 'rm -f "$checks_output"' EXIT

while :; do
  # Redirection alone keeps this in the current shell, so the counters survive.
  run_all_checks > "$checks_output"
  if [[ "$action_count" -eq 0 && "$error_count" -eq 0 ]] || (( SECONDS >= deadline )); then
    break
  fi
  sleep 5
done
cat "$checks_output"

echo
if [[ "$action_count" -eq 0 && "$error_count" -eq 0 ]]; then
  echo "확인된 항목은 모두 준비됐다. SKIP은 설정상 꺼둔 것이므로 문제가 아니다."
  exit 0
fi

if [[ "$action_count" -gt 0 ]]; then
  echo "조치가 필요한 항목 ${action_count}건:"
  for entry in "${remedies[@]}"; do
    name="${entry%%$'\n'*}"
    body="${entry#*$'\n'}"
    printf '\n[%s]\n%s\n' "$name" "$body"
  done
fi

if [[ "$error_count" -gt 0 ]]; then
  [[ "$action_count" -gt 0 ]] && echo
  echo "판정할 수 없는 항목 ${error_count}건. 위 ERROR 줄의 사유를 먼저 해소해야 한다."
fi
exit 1
