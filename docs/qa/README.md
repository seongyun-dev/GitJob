# QA·검증 계획

> 상태: 현재 MVP 기능·통합·데이터·복원력 검증 기준
>
> 기준일: 2026-09-10
>
> 검증 완료 주장과 남은 인수는 [현재 상태](../2026-09-10-current-status.md) 및 기능별 검증 기록을 함께 확인한다.

## 1. 품질 목표

GitJob의 품질은 “화면이 열리는가”만으로 판단하지 않는다. 동일한 분석을 다시 실행해도 기준과 결과를 추적할 수 있고, 근거 없는 수치가 노출되지 않으며, 외부 API·Kafka·Worker 장애가 전체 서비스 장애로 번지지 않는 것을 목표로 한다.

## 2. 검증 계층

| 계층 | 대상 | 방법 |
|---|---|---|
| Unit | Registry mapping, level rule, status transition, score/status derivation | JUnit/Pytest |
| Integration | PostgreSQL·Redis·Kafka·HDFS adapter, repository, event consumer | Testcontainers/Compose |
| API | auth, repository, analysis, profile, demand, recommendation, trend | REST contract test |
| E2E | 로그인→저장소→분석→Evidence→추천 흐름 | Browser test |
| Data | raw→Parquet→Fact→Snapshot, row/checksum/duplicate | fixture + SQL/assertion |
| Load | worker/partition/volume별 처리량·lag·p95 | 고정 dataset benchmark |
| Resilience | rewind, duplicate, late event, quota, worker kill/restart, DLQ | fault injection |
| Security | scope, ownership, cookie, secret/log, deletion | negative test + review |

## 3. 기능 수용 기준

### 인증·저장소

- OAuth `state` 불일치·만료를 거부한다.
- 승인된 scope와 사용자가 권한을 부여한 public/private 저장소 범위를 사용자에게 표시한다.
- 저장소 목록에 owner, visibility, fork, archived, default branch, language, last push가 포함된다.
- 접근 권한이 없는 저장소를 분석 대상으로 저장할 수 없다.
- 선택 목록은 최소 1건, 최대 정책값을 지키고 전체 교체(PUT) semantics를 유지한다.
- 로그아웃은 세션만 종료하고, 연결 해제는 Token revoke 정책과 분리한다.

### 분석 Job

- 분석 요청은 동기 처리로 오래 block하지 않고 `202 + analysisId`를 반환한다.
- 같은 사용자의 동일 진행 Job을 중복 생성하지 않는다.
- 저장소별 Commit·Registry·parser 기준이 결과에 남는다.
- `QUEUED → 수집 → 분석 → 완료/부분/실패` 상태가 유효한 전이만 허용한다.
- 부분 실패는 성공 저장소 결과를 잃지 않고 실패 원인·재시도 정보를 표시한다.
- 취소 후 부분 결과를 최신 결과로 승격하지 않는다.
- 재실행은 새 Snapshot을 만들며 과거 결과가 변경되지 않는다.

### Profile·Evidence

- Evidence에 기술, rule, level, repository, path, line, commit permalink가 있다.
- Repository Level과 Personal Level을 분리한다.
- bot·merge·fork base·generated·format-only noise가 제외 사유와 함께 처리된다.
- 원본 코드 전체, Token, 권한 없는 private 내용이 API 응답에 들어가지 않는다. private 원문은 해당 사용자 분석과 삭제 정책 범위 밖으로 유출되지 않는다.
- `unmetRules`와 `nextActions`가 현재 수준에 맞게 연결된다.

### 수요·추세·추천

- job demand는 중복 공고를 deduplicate한 분모와 기간을 함께 표시한다.
- JOB/GITHUB 지표는 단위·기간·source별로 분리된다.
- 출처가 없는 기간을 interpolation하거나 임의 composite score로 표시하지 않는다.
- Skill Gap 상태는 Personal Level에서 기계적으로 파생된다.
- 추천은 후보·점수 분해·Evidence 요구·반대 신호·data gap을 함께 반환한다.
- 데이터가 준비되지 않으면 dummy 대신 `PREPARING`/`INSUFFICIENT_DATA`를 반환한다.

### 근거 설명

- AI 설명의 모든 수치·레벨·순위가 Fact Pack 또는 Evidence에 연결된다.
- 검증 실패 시 `RULE_TEMPLATE` 또는 `INSUFFICIENT_EVIDENCE`로 안전하게 fallback한다.
- 설명에 사용한 Fact Pack·Evidence·규칙 버전과 미확정 상태를 보존한다.
- Stack Overflow/Pain/FAQ/RAG와 프로젝트 Template 추천은 현재 MVP 수용 기준에서 제외한다.

## 4. 데이터 품질 검사

각 pipeline run에서 다음을 기록하고 임계값을 초과하면 warning 또는 실패로 처리한다.

| 검사 | 확인 내용 |
|---|---|
| Completeness | 필수 source id, occurred/ingested time, tech id 누락 |
| Uniqueness | event id, source/source id/version 중복 |
| Validity | schema version, enum, date, URL, checksum |
| Consistency | PostgreSQL row와 Parquet manifest·row count 일치 |
| Timeliness | late event, watermark, source update 시각 |
| Parse | XML/HTML/body/code 파싱 성공·실패 수 |
| Lineage | 분석 결과에서 dataset·event·quality로 역추적 가능 |

검사 실패 메시지는 DLQ와 pipeline run에 연결하고, 원인 수정 후 동일 dataset hash로 replay해 결과를 비교한다.

## 5. 성능·복원력 실험

고정된 dataset hash, 동일한 Registry/parser version으로 다음 조합을 측정한다.

| 축 | 값 |
|---|---|
| Worker | 1 / 2 / 4 |
| Kafka partition | 1 / 3 / 6 |
| 저장 volume | 1 / 2 / 4 |
| 반복 | warmup 후 3회 median |
| 관측 | throughput, p50/p95, end-to-end latency, consumer lag, error/retry, CPU/RAM |

장애 시나리오:

1. consumer를 한 partition offset으로 rewind한다.
2. Worker를 종료하고 재기동한다.
3. GitHub rate limit 응답을 주입한다.
4. 동일 event와 늦게 도착한 event를 넣는다.
5. C2 mapping 실패를 DLQ로 보낸다.
6. DLQ를 수정 후 replay하고 중복 없이 Snapshot이 복구되는지 확인한다.

## 6. 현재 인프라 검증 명령

```bash
./Infra/scripts/init-wsl.sh
PROFILES=core ./Infra/scripts/up.sh
./Infra/scripts/healthcheck.sh
./Infra/scripts/kafka-smoke.sh
./Infra/scripts/backup-postgres.sh
PROFILES=core,app,data ./Infra/scripts/up.sh
./Infra/scripts/spark-smoke.sh
./Infra/scripts/spark-benchmark.sh

# 기본값은 Worker 1/2/4 × dataset 1x/2x/4x, 반복 3회이며 TSV 결과를
# .local/benchmarks/에 기록한다. worker_count, Spark version, throughput,
# p50/p95, 실패 건수와 dataset hash를 함께 비교한다.
./Infra/scripts/spark-benchmark.sh

# Compose 병합 확인
docker compose --env-file .env.wsl --project-directory . \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data \
  config --quiet
```

이 문서 작성 시점에 직접 확인한 범위는 PostgreSQL·Redis·Kafka core healthcheck, Kafka 송수신 smoke, WSL/HA Compose 설정 병합, HDFS/Spark 최소 smoke다. 재시작 영속성·PostgreSQL backup/restore의 통과 결과는 기존 [인프라 준비도 문서](../infra/2026-08-27-infra-readiness.md)의 기록을 참조하되, 이 문서에서는 직접 재실행한 결과로 표현하지 않는다. BE/FE/AI source가 추가되기 전에는 실제 API·화면·분석 Worker·Collector end-to-end를 통과한 것으로 표시하지 않는다.

## 7. 결함 분류

| 등급 | 기준 | 예시 |
|---|---|---|
| Blocker | 사용자 데이터 유출·분석 결과 손실·기동 불가 | Token 노출, Snapshot overwrite |
| Critical | 핵심 흐름 중단 또는 잘못된 판정 | OAuth callback 실패, Evidence 규칙 오판 |
| Major | 기능 우회 가능하지만 계약 위반 | 부분 실패 상태 누락, 잘못된 분모 |
| Minor | 표시·문구·접근성 문제 | 날짜 포맷, empty state |

## 8. 원문 출처

- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [인프라 준비도](../infra/2026-08-27-infra-readiness.md)
- [데이터 파이프라인](../data/README.md)
