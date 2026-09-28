# 유실된 분석 결과 재생 절차

- Jira: `S15P21E102-279` 후속
- 대상: `gitjob.repository-analysis.results.v1` → `backend` → `analysis_job`
- 성격: **일회성 복구 절차**. 왜 유실됐는지는
  `BE/.../messaging/RepositoryAnalysisKafkaConfiguration.java`의
  `resultErrorHandler` 주석에 있다.
- 작성일: 2026-09-16

---

## 0. 무엇이 일어났는가

워커는 결과를 정상 발행했다. BE가 그것을 역직렬화하지 못했고
(`syntax_node_count`가 primitive `int`였다), `DefaultErrorHandler`는 역직렬화 오류를
재시도 불가로 분류한다. 그 판단 자체는 옳다 — 같은 바이트를 다시 읽어도 결과는 같다.

문제는 그다음이었다. **recoverer가 없어서 그 레코드는 로그 한 줄만 남기고
커밋됐다.** 오프셋은 끝까지 진행돼 컨슈머 lag는 0이고, 컨테이너는 건강하고,
화면만 `QUEUED`에 남았다. 최초 장애 당시 확인한 4건 이후에도 대상 수는 바뀔 수
있으므로 실행 때마다 DB와 토픽을 다시 대조한다.

### 0.1 그래서 이 절차가 필요한 이유

DLQ가 없었으므로 **무엇을 재생해야 하는지가 어디에도 남아 있지 않다.** 토픽의 원본
레코드를 직접 찾아야 한다. 다행히 이 토픽은 `retention.ms=-1`이라
(`Infra/scripts/kafka-topics.sh`) 레코드가 아직 남아 있다.

같은 일이 다시 일어나면 이 문서는 필요 없다. 이제 적용하지 못한 결과는
`gitjob.repository-analysis.results.dlq.v1`에 원본 바이트와 예외가 함께 남는다.

---

## 1. 전제

**1~3단계가 먼저 배포돼 있어야 한다.** 고치지 않은 BE에 재생하면 같은 이유로
다시 버려지고, 이번에는 DLQ에 쌓이기만 한다.

```bash
bash Infra/scripts/verify-deployment.sh
```

확인할 것:

- BE 이미지가 계약 수정본인가 — `AnalysisStats.syntaxNodeCount`가 `Integer`
- `gitjob.repository-analysis.results.dlq.v1` 토픽이 있는가 (`kafka-topics` OK)

---

## 2. 왜 오프셋을 되감지 않는가

두 가지 방법이 있다.

| | 컨슈머 그룹 오프셋 되감기 | **원본 레코드 재발행** |
|---|---|---|
| BE 중단 | 필요 (그룹이 활성이면 reset 불가) | 불필요 |
| 재처리 범위 | 되감은 시점 이후 전부 | 유실된 4건만 |
| 남는 것 | 없음 | 토픽에 중복 레코드 |

**재발행을 쓴다.** 되감기는 BE를 내려야 하고, 그 사이 도착하는 새 결과까지 밀린다.
재발행은 중복 레코드를 남기지만 그건 무해하다 — `AnalysisResultService.apply()`가
잡 상태를 멱등성 마커로 쓰기 때문에, 이미 끝난 분석에 결과가 또 오면
`ALREADY_TERMINAL`로 건너뛴다.

재발행 직전에도 대상이 비종료 상태인지 확인해야 한다. 이미 종료된 결과는 멱등하게
건너뛰지만, 실행 목록을 넓게 잡는 근거로 사용하지 않는다.

---

## 3. 절차

### 3.1 대상 확인

```sql
SELECT analysis_id, user_id, repository_full_name, status, current_stage, requested_at
  FROM analysis_job
 WHERE status IN ('QUEUED', 'COLLECTING', 'RUNNING', 'ANALYZING', 'RATE_LIMITED')
 ORDER BY requested_at;
```

결과가 실제로 발행된 것으로 별도 확인한 `analysis_id`만 한 줄에 하나씩
`/tmp/replay-analysis-ids.txt`에 적는다. 감사 시점의 "11건" 같은 개수만 믿고 전체
비종료 행을 자동 재생하지 않는다. 이 값이 곧 Kafka 레코드의 **키**다
(`AI/analysis/publish.py`: `key=result.payload.analysis_id`).

### 3.2 토픽에서 원본 추출

키와 값을 탭으로 구분해 받는다. 워커는 값을 한 줄짜리 compact JSON으로 발행하므로
(`model_dump_json()`) 레코드 하나가 파일 한 줄이다.

`--timeout-ms`가 없으면 콘솔 컨슈머가 끝나지 않는다. `//opt`의 앞 슬래시 두 개는
오타가 아니라 Git Bash의 경로 변환을 피하기 위한 것이다(`kafka-topics.sh` 참고).

```bash
docker compose --project-directory . --env-file .env -f Infra/compose/compose.yaml \
  exec -T kafka //opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 \
    --topic gitjob.repository-analysis.results.v1 \
    --from-beginning --timeout-ms 30000 \
    --property print.key=true > /tmp/results-all.tsv
```

대상만 남긴다. 이 단계는 토픽을 바꾸지 않는 dry-run이다.

```bash
awk -F '\t' 'NR==FNR { wanted[$1]=1; next } ($1 in wanted) { print }' \
  /tmp/replay-analysis-ids.txt /tmp/results-all.tsv > /tmp/replay.tsv
wc -l /tmp/replay.tsv
cut -f1 /tmp/replay.tsv | sort | uniq -c
```

**줄 수가 대상 수와 같은지 확인한다.** 적으면 그 분석은 결과가 발행된 적이 없다는
뜻이고(워커가 아예 처리하지 못한 것), 재생이 아니라 재분석 대상이다. 많으면 워커가
같은 분석을 두 번 발행한 것이며 멱등성이 처리하므로 그대로 둬도 된다.

각 줄이 `COMPLETED`인지도 눈으로 본다. `FAILED` 결과라면 재생해도 화면에는 실패로
보인다 — 그게 맞는 결과다.

### 3.3 재발행

키를 보존해야 파티션과 순서가 원본과 같다.

```bash
docker compose --project-directory . --env-file .env -f Infra/compose/compose.yaml \
  exec -T kafka //opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server localhost:9092 \
    --topic gitjob.repository-analysis.results.v1 \
    --property parse.key=true < /tmp/replay.tsv
```

### 3.4 검증

```sql
SELECT analysis_id, status, current_stage, completed_at, result_schema_version
  FROM analysis_job
 WHERE analysis_id IN ('<ID1>', '<ID2>', '<ID-N>');
```

`SUCCEEDED`로 바뀌어야 한다. 근거도 들어왔는지 본다.

```sql
SELECT analysis_id, count(*) FROM analysis_evidence
 WHERE analysis_id IN ('<ID1>', '<ID2>', '<ID-N>')
 GROUP BY analysis_id;
```

v3 결과라면 사용자별 C 계산 상태도 이어서 확인한다. 새 복구 스케줄러는
snapshot과 attempt가 모두 없는 사용자를 제한된 배치로 시작하지만, replay 직후
아래 상태가 생기는지 확인해야 분석 완료와 추천 복구를 구분할 수 있다.

```sql
SELECT user_id, target_key, status, reason, attempt_count, updated_at
  FROM user_c_compute_attempt
 WHERE user_id IN (<USER_ID_LIST>);

SELECT user_id, target_key, evidence_version, computed_at
  FROM user_c_snapshot
 WHERE user_id IN (<USER_ID_LIST>)
 ORDER BY user_id, computed_at DESC;
```

여전히 `QUEUED`면 **DLQ를 본다.** 이제는 실패가 조용히 사라지지 않는다.

```bash
docker compose --project-directory . --env-file .env -f Infra/compose/compose.yaml \
  exec -T kafka //opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 \
    --topic gitjob.repository-analysis.results.dlq.v1 \
    --from-beginning --timeout-ms 15000 --property print.headers=true
```

---

## 4. 재생해도 끝나지 않는 것

**이 4건은 v1 결과다.** `rule_pack_version`이 없다.

화면의 "분석 완료"와 기술 목록은 복구되지만, C는 `evidence_rule_version`으로 근거의
범위를 검사하므로 이 분석들은 **공고 매칭·추천에 쓸 수 없다.** Registry 버전을 대신
넣으면 C가 모든 근거를 범위 불일치로 버리고 화면은 "근거는 있는데 아무것도 보유가
아닌" 상태가 된다.

이 사용자들을 추천까지 보내려면
[Registry 44 전환](2026-09-16-registry44-v3-result-activation.md) 뒤에 **재분석**이
필요하다. 재생은 그 전에 화면을 정상으로 되돌리고 파이프라인이 실제로 동작하는지
확인하는 단계다.

같은 이유로 개인 귀속도 비어 있다. 이 결과들은 `ANALYSIS_ATTRIBUTE_AUTHORS`가 꺼진
채로 만들어져 Evidence의 `commit_sha`가 전부 `NULL`이고, 나중에 채울 수 없다.
