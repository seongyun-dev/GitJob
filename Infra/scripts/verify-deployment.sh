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
    from worker.postgres_env import dsn_from_postgres_env
    dsn = dsn_from_postgres_env()
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
          rearm_schema_ready="$(psql_query "SELECT CASE WHEN
            EXISTS (SELECT 1 FROM flyway_schema_history WHERE version = '26' AND success)
            AND to_regclass('public.user_c_compute_attempt_rearm_audit') IS NOT NULL
            AND EXISTS (
              SELECT 1 FROM pg_constraint
              WHERE conrelid = to_regclass('public.user_c_compute_attempt')
                AND conname = 'user_c_compute_attempt_attempt_count_check'
                AND pg_get_constraintdef(oid) LIKE '%attempt_count >= 0%'
            ) THEN 1 ELSE 0 END")"
          if [[ "$rearm_schema_ready" == "1" ]]; then
            ok schema "최신 ${latest:-unknown}; V26 rearm audit 계약 확인"
          else
            needs_action schema "V26 rearm audit 계약이 적용되지 않았다" \
              "backend Flyway V26 적용을 확인하고 flag를 legacy로 유지한다.
    SELECT version, description, success FROM flyway_schema_history WHERE version = '26';
    SELECT to_regclass('public.user_c_compute_attempt_rearm_audit');"
          fi
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

  # --- C completed-output intake ----------------------------------------------
  # The container healthcheck is liveness and /ready only looks at the database,
  # so an intake that cannot reach HDFS — or cannot write its staging directory —
  # leaves the deployment green. That is exactly how a root-owned c-job-staging
  # volume went unnoticed until someone read the logs. `last_poll.failed` counts
  # both a refresh failure and a discovery failure, which is the signal wanted.
  #
  # The healthcheck deliberately stays out of this: /intake/status needs the
  # bearer token, and a NameNode blip must not restart a worker that is still
  # computing on what it already staged.
  intake_config="$(read_env C_INTAKE_CONFIG)"
  if ! profile_enabled data; then
    skip worker-intake "data 프로필이 이 호스트에 없다"
  elif [[ -z "$intake_config" ]]; then
    # .env.example: empty means Worker stays HTTP-only. Not a deployment fault.
    skip worker-intake "C_INTAKE_CONFIG 미설정 — 자동 입력 감시가 설계상 비활성"
  elif ! running worker; then
    undetermined worker-intake "worker 컨테이너가 이 호스트에 없다"
  else
    # Same shape as worker-ready above: the call is made inside the container so
    # that the token stays there and never reaches this script or its output.
    intake_status="$(compose exec -T worker sh -c '
      code=$(curl -sS -o /tmp/verify-intake.json -w "%{http_code}" \
        -H "Authorization: Bearer $C_COMPUTE_TOKEN" \
        http://localhost:8080/internal/v1/c/intake/status 2>/dev/null || echo 000)
      printf "%s " "$code"
      tr -d "\n" < /tmp/verify-intake.json 2>/dev/null
      rm -f /tmp/verify-intake.json
    ' 2>/dev/null | tr -d '\r')"
    intake_code="${intake_status%% *}"
    intake_body="${intake_status#* }"
    intake_remedy="worker 로그에서 실패 유형을 먼저 읽는다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=data \\
      docker compose logs --tail 100 worker
  PermissionError 라면 staging 볼륨이 root 소유다. c-job-staging-init 가 완료됐는지 확인한다.
    ENV_FILE=$ENV_FILE COMPOSE_OVERRIDE_FILE=$COMPOSE_OVERRIDE_FILE PROFILES=data ./Infra/scripts/up.sh"
    if [[ "$intake_code" != "200" ]]; then
      undetermined worker-intake "/intake/status 응답 코드 $intake_code"
    else
      # No JSON parser is guaranteed in this shell, and the fields are flat
      # booleans and one integer, so the body is matched directly.
      configured=no; [[ "$intake_body" == *'"configured":true'* ]] && configured=yes
      intake_running=no; [[ "$intake_body" == *'"running":true'* ]] && intake_running=yes
      failed="$(printf '%s' "$intake_body" | sed -n 's/.*"failed":[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
      if [[ "$configured" != "yes" ]]; then
        needs_action worker-intake "C_INTAKE_CONFIG 는 설정됐는데 runner 가 구성되지 않았다" \
          "설정 파일이 컨테이너 안에 실제로 있는지, DB 와 32자 이상 토큰이 준비됐는지 확인한다.
    C_INTAKE_CONFIG=$intake_config
  /config 마운트는 compose.yaml 의 C_INTAKE_CONFIG_DIR 로 들어간다."
      elif [[ "$intake_running" != "yes" ]]; then
        needs_action worker-intake "intake runner 가 구성됐지만 동작하지 않는다" "$intake_remedy"
      elif [[ -z "$failed" ]]; then
        # A poll has not completed yet; poll_seconds defaults to 30.
        undetermined worker-intake "아직 완료된 poll 이 없다 — 잠시 뒤 다시 확인한다"
      elif [[ "$failed" != "0" ]]; then
        needs_action worker-intake "마지막 poll 실패 ${failed}건" "$intake_remedy"
      else
        ok worker-intake "입력 감시 동작 중, 마지막 poll 실패 0건"
      fi
    fi
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

  # --- Registry 발행(alias) -----------------------------------------------------
  # 분석 요청이 만들어지려면 Registry 가 **발행**돼 있어야 한다. 발행의 경계는
  # technology_registry.status='CURRENT' 가 아니라 technology_registry_alias 행이고,
  # 그 스냅샷에 content_sha256 이 있어야 한다(TechnologyRegistryVersionResolver).
  #
  # 마이그레이션은 Registry 행만 넣는다. alias 는 c-registry-import.sh 가 스냅샷과
  # Rule Pack 을 들여오면서 붙이는 별도 단계라, 새로 세운 환경에서는 비어 있다.
  # 그 상태에서는 제출이 전부 ANALYSIS-503-1 로 실패하는데 컨테이너는 모두 건강해
  # 보인다 -- 2026-09-21 로컬 e2e 에서 실제로 그렇게 막혔다.
  if ! profile_enabled core; then
    skip registry-alias "core 프로필이 이 호스트에 없다"
  elif ! running postgres; then
    undetermined registry-alias "postgres 컨테이너가 이 호스트에 없다"
  else
    alias_state="$(psql_query "SELECT coalesce(
            (SELECT alias.registry_version || ':' ||
                    CASE WHEN snapshot.content_sha256 IS NULL THEN 'n' ELSE 'y' END
               FROM technology_registry_alias alias
               JOIN technology_registry snapshot
                 ON snapshot.schema_version = alias.schema_version
                AND snapshot.registry_version = alias.registry_version
              WHERE alias.schema_version = 'technology-registry/v1'), 'none')")"
    alias_remedy="data 호스트에서 Registry 와 Rule Pack 을 들여오고 활성화한다.
    ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \\
      PROFILES=data ./Infra/scripts/c-registry-import.sh"
    case "$alias_state" in
      none)
        needs_action registry-alias \
          "technology_registry_alias 에 technology-registry/v1 활성 행이 없다 -- 분석 요청이 ANALYSIS-503-1 로 전부 실패한다" \
          "$alias_remedy" ;;
      *:n)
        needs_action registry-alias \
          "활성 Registry ${alias_state%%:*} 에 content_sha256 이 없다 -- 발행이 끝나지 않았다" \
          "$alias_remedy" ;;
      *)
        ok registry-alias "활성 Registry ${alias_state%%:*} (content_sha256 있음)" ;;
    esac
  fi

  # --- 분석 결과 계약 배선 ------------------------------------------------------
  # CURRENT Registry 가 요구하는 결과 계약과 실제 배선이 어긋나면 분석이 조용히 멈춘다.
  # 워커는 판정에 쓴 Rule Pack 으로 발행 계약을 정하고 v1 을 함께 보내지 않는다.
  # v3 publisher 가 없으면 UNSUPPORTED_RESULT_SCHEMA 로 실패하고, BE 가 v3 토픽을
  # 구독하지 않으면 결과가 도달하지 않아 분석이 QUEUED 에 남는다. 둘 다 컨테이너는
  # 건강해 보이므로 다른 검사로는 드러나지 않는다.
  #
  # 이 호스트의 env 파일을 본다. service 호스트는 backend 를, data 호스트는
  # analysis-worker 를 같은 두 변수로 설정하므로 양쪽에서 돌려야 한다.
  if ! profile_enabled core; then
    skip analysis-result "core 프로필이 이 호스트에 없다"
  elif ! running postgres; then
    undetermined analysis-result "postgres 컨테이너가 이 호스트에 없다"
  else
    current_registry="$(psql_query "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'")"
    current_rule_pack="$(psql_query "SELECT p.rule_pack_version FROM technology_rule_pack p JOIN technology_registry r ON r.registry_version = p.registry_version WHERE r.status = 'CURRENT'")"
    # compose.yaml 의 기본값과 같아야 한다. 미설정과 기본값을 구분하지 않는다.
    result_schema="$(read_env ANALYSIS_RESULT_SCHEMA_VERSION)"
    result_schema="${result_schema:-repository-analysis-result/v3}"
    result_topic_v3="$(read_env KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3)"
    result_topic_v3="${result_topic_v3:-gitjob.repository-analysis.results.v3}"

    case "$current_rule_pack" in
      "") required_contract="repository-analysis-result/v1" ;;
      rule-pack-20260911.2) required_contract="repository-analysis-result/v2" ;;
      rule-pack-20260911.3|rule-pack-20260911.4) required_contract="repository-analysis-result/v3" ;;
      *) required_contract="unknown" ;;
    esac

    if [[ -z "$current_registry" ]]; then
      needs_action analysis-result "technology_registry 에 CURRENT 가 없다" \
        "CURRENT 없이는 분석 요청 자체가 만들어지지 않는다. Registry 발행 상태를 확인한다.
    SELECT registry_version, status FROM technology_registry ORDER BY registry_version;"
    elif [[ "$required_contract" == "unknown" ]]; then
      undetermined analysis-result \
        "CURRENT=$current_registry 의 Rule Pack $current_rule_pack 을 이 스크립트가 모른다"
    elif [[ "$required_contract" == "repository-analysis-result/v2" ]]; then
      # BE 에는 v2 결과 토픽 설정이 없다. 워커가 v2 로 발행하면 아무도 읽지 않는다.
      needs_action analysis-result \
        "CURRENT=$current_registry 는 v2 결과를 만드는데 BE 는 v2 토픽을 구독하지 않는다" \
        "v2 를 쓰려면 BE 에 v2 결과 토픽 구독을 먼저 추가해야 한다. 그 전에는 .3/.4 로 올리거나 Rule Pack 이 없는 Registry 를 쓴다."
    elif [[ "$required_contract" == "repository-analysis-result/v1" ]]; then
      # Rule Pack 이 없는 Registry 다. 워커는 v1 로 발행하므로 v3 배선은 쓰이지 않는다.
      ok analysis-result "CURRENT=$current_registry, 결과 계약 v1 (Rule Pack 없음)"
    elif [[ "$result_schema" != "repository-analysis-result/v3" ]]; then
      needs_action analysis-result \
        "CURRENT=$current_registry 는 v3 결과를 요구하는데 ANALYSIS_RESULT_SCHEMA_VERSION=$result_schema" \
        "워커에 v3 publisher 가 없어 분석이 UNSUPPORTED_RESULT_SCHEMA 로 실패한다. env 파일에서 지우거나 v3 로 맞춘 뒤 analysis-worker 를 재시작한다."
    elif [[ -z "$result_topic_v3" ]]; then
      needs_action analysis-result \
        "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3 이 비어 있다" \
        "워커는 기동하지 못하고, BE 는 v3 토픽을 구독하지 않아 결과가 도달하지 않는다. env 파일에서 지워 기본값을 쓰게 한다."
    elif ! grep -Fq "\"$result_topic_v3:" "$SCRIPT_DIR/kafka-topics.sh"; then
      needs_action analysis-result \
        "v3 결과 토픽 $result_topic_v3 이 kafka-topics.sh 에 선언돼 있지 않다" \
        "자동 생성이 꺼져 있어 없는 토픽에는 발행도 구독도 되지 않는다. 기본 이름을 쓰거나 kafka-topics.sh 의 TOPICS 에 추가한다."
    else
      ok analysis-result "CURRENT=$current_registry, 결과 계약 v3, 토픽 $result_topic_v3"
    fi
  fi

  # --- Backend -> C Compute 배선 ------------------------------------------------
  # 분석이 정상 저장돼도 이 연결이 없으면 공고 매칭·Skill Gap·추천이 계산되지 않는다.
  # BE 는 주소나 토큰이 비면 C 를 아예 호출하지 않고 계산 결과를 "미준비"로 내리는데
  # (CComputeProperties#isConfigured), 화면에서는 아직 계산 전인 것과 구분되지 않는다.
  # 그래서 설정 누락이 장애로 보이지 않고 몇 주씩 남을 수 있다.
  if ! profile_enabled app; then
    skip backend-compute "app 프로필이 이 호스트에 없다"
  elif ! running backend; then
    undetermined backend-compute "backend 컨테이너가 이 호스트에 없다"
  else
    compute_url="$(read_env C_COMPUTE_URL)"
    compute_token="$(read_env C_COMPUTE_TOKEN)"
    if [[ -z "$compute_url" || -z "$compute_token" ]]; then
      needs_action backend-compute \
        "C_COMPUTE_URL/C_COMPUTE_TOKEN 이 비어 있어 BE 가 C 를 호출하지 않는다" \
        "분석은 저장되지만 추천까지 이어지지 않는다. env 파일에 두 값을 채우고 backend 를 재시작한다.
service 호스트에서 주소는 compose 내부 이름이 아니라 데이터 노드의 Tailscale 주소다.
토큰은 worker 의 C_COMPUTE_TOKEN 과 같은 값이어야 한다."
    else
      # 토큰은 컨테이너 안에서만 읽는다. 이 스크립트로도, 로그로도 나오지 않는다.
      compute_code="$(compose exec -T backend sh -c '
        curl -sS -o /dev/null -w "%{http_code}" --max-time 5 \
          -H "Authorization: Bearer $C_COMPUTE_TOKEN" \
          "$C_COMPUTE_URL/ready" 2>/dev/null || echo 000
      ' 2>/dev/null | tr -d '\r' | tail -n 1)"
      case "$compute_code" in
        200)
          ok backend-compute "BE 에서 C /ready 도달" ;;
        000)
          needs_action backend-compute \
            "BE 컨테이너에서 $compute_url 에 닿지 않는다" \
            "주소가 이 호스트 기준인지 확인한다. split 배포에서는 compose 내부 이름이 아니라 데이터 노드의 Tailscale 주소여야 한다." ;;
        401|403)
          needs_action backend-compute \
            "C 가 인증을 거절했다 (code=$compute_code)" \
            "backend 와 worker 의 C_COMPUTE_TOKEN 이 같은 값인지 확인한다." ;;
        503)
          needs_action backend-compute \
            "C 가 아직 준비되지 않았다 (code=503)" \
            "위 worker-ready 결과를 먼저 본다. Registry 미활성이면 C 를 재기동해야 한다." ;;
        *)
          undetermined backend-compute "C /ready 응답이 예상 밖이다 (code=${compute_code:-unknown})" ;;
      esac
    fi
  fi

  # --- 개인 귀속 산출물 ---------------------------------------------------------
  # personalLevel 은 Evidence 의 commit_sha 에서 나온다. ANALYSIS_ATTRIBUTE_AUTHORS 가
  # 꺼져 있으면 워커가 얕은 체크아웃으로 돌고 그 값이 전부 NULL 로 남는데, 분석은
  # SUCCEEDED 로 끝나고 기술 목록도 보인다. 설정만 봐서는 드러나지 않으므로 결과를 본다.
  #
  # 설정 자체는 data 호스트에 있고 근거 행은 DB 에 있다. DB 를 보는 쪽이 진실이다.
  if ! profile_enabled core; then
    skip analysis-personal "core 프로필이 이 호스트에 없다"
  elif ! running postgres; then
    undetermined analysis-personal "postgres 컨테이너가 이 호스트에 없다"
  else
    personal_row="$(psql_query "SELECT j.analysis_id || '|'
           || (SELECT count(*) FROM analysis_evidence e
                WHERE e.analysis_id = j.analysis_id AND e.commit_sha IS NOT NULL) || '|'
           || (SELECT count(*) FROM analysis_evidence e WHERE e.analysis_id = j.analysis_id)
      FROM analysis_job j
     WHERE j.status = 'SUCCEEDED'
     ORDER BY j.completed_at DESC NULLS LAST
     LIMIT 1")"
    if [[ -z "$personal_row" ]]; then
      skip analysis-personal "성공한 분석이 아직 없다"
    else
      personal_analysis="${personal_row%%|*}"
      personal_rest="${personal_row#*|}"
      personal_attributed="${personal_rest%%|*}"
      personal_total="${personal_rest##*|}"
      if [[ "$personal_total" == "0" ]]; then
        ok analysis-personal "최근 성공 분석 $personal_analysis 의 근거가 0건 (등록 기술 미관측)"
      elif [[ "$personal_attributed" == "0" ]]; then
        needs_action analysis-personal \
          "최근 성공 분석 $personal_analysis 의 근거 $personal_total 건에 commit_sha 가 하나도 없다" \
          "ANALYSIS_ATTRIBUTE_AUTHORS 가 꺼져 있으면 personalLevel 을 만들 수 없다. data 호스트에서 켜고 analysis-worker 를 재시작한다.
켜면 전체 히스토리를 클론하므로 worker 디스크 여유를 먼저 본다.
이미 저장된 분석은 자동으로 채워지지 않는다 -- 그 사용자는 재분석이 필요하다."
      else
        ok analysis-personal "최근 성공 분석 $personal_analysis 근거 $personal_attributed/$personal_total 건에 commit_sha 있음"
      fi
    fi
  fi

  # --- Weekly Trend consumer placement --------------------------------------
  # The base service historically belonged to the data profile. The production
  # topology now runs it only on the Service host, where host networking can
  # follow every WebHDFS DataNode redirect. Check both the positive placement
  # and absence of the legacy data-host container.
  weekly_consumer_id="$(compose ps -a -q weekly-trend-consumer 2>/dev/null | head -n 1)"
  if profile_enabled weekly; then
    if [[ -z "$weekly_consumer_id" ]]; then
      needs_action weekly-consumer-ready "서비스 서버의 weekly-trend-consumer 컨테이너가 없다" \
        "weekly-host overlay로 Consumer를 배포한다. Jenkins 배포는 이 단계를 자동 수행한다."
    else
      weekly_consumer_status="$(docker inspect --format '{{.State.Status}}' "$weekly_consumer_id" 2>/dev/null || true)"
      weekly_consumer_restarts="$(docker inspect --format '{{.RestartCount}}' "$weekly_consumer_id" 2>/dev/null || true)"
      if [[ "$weekly_consumer_status" == "running" ]]; then
        ok weekly-consumer-ready "서비스 서버 Consumer 실행 중 (restarts=${weekly_consumer_restarts:-unknown})"
      else
        needs_action weekly-consumer-ready \
          "상태=${weekly_consumer_status:-unknown}, restarts=${weekly_consumer_restarts:-unknown}" \
          "Consumer 로그와 Kafka·WebHDFS·PUBLIC_GITHUB/export 준비 상태를 확인한다."
      fi
    fi
  elif profile_enabled data; then
    if [[ -n "$weekly_consumer_id" ]]; then
      weekly_consumer_status="$(docker inspect --format '{{.State.Status}}' "$weekly_consumer_id" 2>/dev/null || true)"
      needs_action weekly-consumer-placement \
        "데이터 서버에 구형 weekly-trend-consumer가 남아 있다 (상태=${weekly_consumer_status:-unknown})" \
        "최신 deploy.sh를 실행해 데이터 서버의 구형 Consumer를 제거한다."
    else
      ok weekly-consumer-placement "데이터 서버에서 제외됨"
    fi
  else
    skip weekly-consumer-ready "weekly/data 프로필이 이 호스트에 없다"
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
