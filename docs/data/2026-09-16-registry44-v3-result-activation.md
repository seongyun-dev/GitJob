# Registry 44 활성화와 v3 결과 계약 전환 Runbook

- Jira: `S15P21E102-279` 후속
- 대상: `analysis-worker` → `gitjob.repository-analysis.results.v3` → `backend`
  → `analysis_job.rule_pack_version` / `analysis_technology_support`
- 성격: **실행·검증·롤백 절차**. 왜 이 계약이 필요한지는
  [기술 Registry DB 운영](technology-registry-db.md)과
  `BE/src/main/resources/db/migration/V17__analysis_rule_pack_lineage.sql`에 있고
  여기서 반복하지 않는다.
- 작성일: 2026-09-16

이 문서의 명령과 값은 전부 현재 코드에서 확인한 것이다. 근거 파일을 각 절에 적었다.

---

## 0. 무엇을 바꾸는가

지금 운영은 두 가지가 어긋나 있다.

1. `technology_registry`의 `CURRENT`가 `registry-20260910.2`다. 이 Registry에는
   Rule Pack이 없어서 워커가 v1 결과를 만든다. v1에는 `rule_pack_version`이 없고,
   그 값이 없으면 C는 근거의 범위를 검사할 수 없어 추천까지 이어지지 않는다.
2. `registry-20260911.4`는 `RETIRED`다.

이 절차는 **① v3 배선을 먼저 배포하고 ② Registry의 `CURRENT`를 옮긴다.** 두 단계를
나누는 이유는 §1에 있다.

### 0.1 이 절차가 하지 않는 것

- 기존 분석의 소급 재처리를 하지 않는다. `CURRENT`는 **새 분석 요청**이 읽는 값이고
  (`BE/.../service/CurrentRegistryVersion.java`), 이미 만들어진 요청은 payload에
  박힌 Registry 버전을 계속 쓴다.
- 이미 저장된 v1 결과에 `rule_pack_version`을 채우지 않는다. 그 값은 판정에 실제로
  쓴 Rule Pack이어야 하며, 나중에 추측으로 채우면 C가 근거를 전부 버린다.
  해당 분석은 재분석 대상이다.
- C alias를 건드리지 않는다. B의 `CURRENT`와 C alias는 별개의 활성화 단계다
  ([technology-registry-db.md](technology-registry-db.md) §B/C 전환 순서).

---

## 1. 왜 배선이 먼저인가

워커는 판정에 쓴 Rule Pack으로 발행 계약을 정하고, **v1을 함께 보내지 않는다**
(`AI/analysis/consumer.py`, `AI/analysis/results.py:schema_for_rule_pack`).

| CURRENT의 Rule Pack | 워커가 발행하는 계약 | 필요한 publisher |
|---|---|---|
| 없음 | `repository-analysis-result/v1` | 항상 있음 |
| `rule-pack-20260911.2` | `.../v2` | `KAFKA_TOPIC_..._RESULTS_V2` |
| `rule-pack-20260911.3` / `.4` | `.../v3` | `KAFKA_TOPIC_..._RESULTS_V3` |

`ANALYSIS_RESULT_SCHEMA_VERSION`은 **계약을 고르는 값이 아니라 준비하는 값**이다.
어떤 publisher를 만들지만 정하고, 실제 계약은 위 표가 정한다. 그래서:

- **배선을 먼저 켜도 동작이 바뀌지 않는다.** 지금 `CURRENT`에는 Rule Pack이 없어
  워커는 계속 v1로 발행한다.
- **배선 없이 Registry만 올리면 전부 실패한다.** v3 publisher가 없으면
  `UNSUPPORTED_RESULT_SCHEMA`로 분석이 실패한다(`AI/analysis/consumer.py`).
- **BE가 먼저 구독하고 있어야 한다.** 전환 직후 첫 v3 결과가 유실되지 않으려면
  `backend`가 이미 v3 토픽을 듣고 있어야 한다.

v2는 이 표에 있지만 **BE에 v2 결과 토픽 설정이 없다**. `registry-20260911.2`를
`CURRENT`로 올리면 워커는 v2로 발행하고 아무도 읽지 않는다. `verify-deployment.sh`가
이 조합을 ACTION으로 잡는다. 열려면 BE에 v2 구독을 먼저 추가해야 한다.

---

## 2. 배선 배포 (①)

리포지터리에 이미 반영된 기본값이라 `.env`에 아무것도 추가하지 않아도 된다.
값을 바꾸고 싶을 때만 env 파일에 쓴다.

| 변수 | 서비스 | 기본값 |
|---|---|---|
| `KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3` | backend, analysis-worker | `gitjob.repository-analysis.results.v3` |
| `ANALYSIS_RESULT_SCHEMA_VERSION` | analysis-worker | `repository-analysis-result/v3` |

### 2.1 순서

**토픽 → backend → analysis-worker.** 토픽 자동 생성은 꺼져 있고
(`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`), v3 토픽이 없으면 워커는 기동에서 멈춘다.

```bash
PROFILES=core bash Infra/scripts/kafka-topics.sh
```

그다음 backend, 그다음 analysis-worker를 새 설정으로 재기동한다. 두 값 모두
**기동 시점에만 읽는다** — 컨테이너를 다시 띄우지 않으면 반영되지 않는다.

### 2.2 확인

```bash
bash Infra/scripts/verify-deployment.sh
```

`analysis-result` 줄이 다음과 같아야 한다. 아직 Registry를 옮기지 않았으므로 v1이 맞다.

```text
analysis-result        OK      CURRENT=registry-20260910.2, 결과 계약 v1 (Rule Pack 없음)
```

이 단계에서 ACTION이 나오면 **Registry를 옮기지 않는다.** 그대로 진행하면 분석이
전부 실패하거나 결과가 도달하지 않는다.

---

## 3. Registry 전환 (②)

### 3.1 사전 조건

대상 Registry에 Rule Pack이 발행돼 있어야 한다. 없으면 워커는 v1을 만들고, 이 전환은
아무 의미가 없다.

```sql
SELECT r.registry_version, r.status, r.published_at, p.rule_pack_version
  FROM technology_registry r
  LEFT JOIN technology_rule_pack p ON p.registry_version = r.registry_version
 ORDER BY r.registry_version;
```

`registry-20260911.4` 행에 `rule_pack_version = 'rule-pack-20260911.4'`가 보여야 한다.
없으면 여기서 멈추고 Rule Pack import부터 한다(`AI/registry/rulepack_db.py`).

### 3.2 전환

`status = 'CURRENT'`는 부분 유니크 인덱스가 하나로 강제하므로
(`V5__registry_lifecycle.sql`), **먼저 내리고 올려야 한다.** 한 트랜잭션에서 한다.

`published_at`은 `COALESCE`로 둔다. `DRAFT`는 `published_at`이 `NULL`이어야 하고
`CURRENT`는 `NULL`이면 안 된다는 CHECK가 있는데, 이미 발행된 적 있는 `RETIRED` 행은
그때의 시각을 지우지 않는 편이 맞다.

```sql
DO $$
DECLARE moved int;
BEGIN
  UPDATE technology_registry SET status = 'RETIRED' WHERE status = 'CURRENT';
  UPDATE technology_registry
     SET status = 'CURRENT', published_at = COALESCE(published_at, now())
   WHERE registry_version = 'registry-20260911.4';
  GET DIAGNOSTICS moved = ROW_COUNT;
  IF moved <> 1 THEN
    RAISE EXCEPTION 'registry-20260911.4 not found';
  END IF;
END $$;
```

**재기동은 필요 없다.** 워커는 이벤트마다 Registry를 읽고(`RegistryStore.load`),
publisher는 §2에서 이미 만들어져 있다. BE도 요청을 만들 때마다 `CURRENT`를 조회한다.

### 3.3 확인

```bash
bash Infra/scripts/verify-deployment.sh
```

```text
analysis-result        OK      CURRENT=registry-20260911.4, 결과 계약 v3, 토픽 gitjob.repository-analysis.results.v3
```

---

## 4. 실제 분석으로 확인

저장소 하나를 새로 분석한 뒤 아래를 본다. **전환 전에 만들어진 요청은 옛 Registry를
그대로 쓰므로, 반드시 전환 뒤에 새로 요청한 분석이어야 한다.**

```sql
SELECT analysis_id, status, registry_version, result_schema_version,
       rule_pack_version, skipped_reasons
  FROM analysis_job
 ORDER BY requested_at DESC LIMIT 5;
```

기대값:

- `result_schema_version = 'repository-analysis-result/v3'`
- `rule_pack_version = 'rule-pack-20260911.4'` — **이것이 이 전환의 목적이다.**
  비어 있으면 v1 결과가 온 것이고, C는 이 분석을 쓸 수 없다.
- `skipped_reasons`가 `NULL`이 아님 — v1에는 없던 필드다.

```sql
SELECT count(*) FROM analysis_technology_support WHERE analysis_id = '<analysis_id>';
```

0이면 기술별 판정 상한이 오지 않은 것이다. C의 `assessment_ceiling`이 이 값에서
나오므로, 0이면 추천 단계에서 다시 막힌다.

### 4.1 결과가 도달하지 않을 때

분석이 QUEUED에 남으면 **먼저 DLQ를 본다.** 적용하지 못한 결과는 조용히 사라지지
않고 `gitjob.repository-analysis.results.dlq.v1`에 원본 바이트와 예외가 함께 남는다.

```bash
compose exec -T kafka //opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic gitjob.repository-analysis.results.dlq.v1 \
  --from-beginning --property print.headers=true --max-messages 5
```

DLQ가 비어 있는데 결과가 없다면 도달 자체를 못 한 것이다. 컨슈머가 v3 토픽을
구독하는지(backend 재기동 여부)와 워커가 어느 토픽에 발행했는지를 본다.

---

## 5. 롤백

Registry만 되돌린다. 배선(§2)은 되돌리지 않는다 — v3 publisher가 있어도 Rule Pack이
없는 Registry에서는 v1로 발행되므로, 남겨 두는 편이 안전하고 다음 시도가 쉽다.

```sql
DO $$
BEGIN
  UPDATE technology_registry SET status = 'RETIRED' WHERE status = 'CURRENT';
  UPDATE technology_registry
     SET status = 'CURRENT', published_at = COALESCE(published_at, now())
   WHERE registry_version = 'registry-20260910.2';
END $$;
```

되돌린 뒤 `verify-deployment.sh`의 `analysis-result`가 다시 v1로 보이면 된다.
전환 중에 만들어진 분석은 payload에 `registry-20260911.4`가 박혀 있어 그대로
v3로 완료된다. BE는 v1·v3 양쪽을 구독하므로 그 결과도 정상 적용된다.

---

## 6. 남은 것

이 절차를 마쳐도 다음 두 가지는 아직 꺼져 있다. 5단계 이후 작업이다.

- `ANALYSIS_ATTRIBUTE_AUTHORS=false` — Evidence의 `commit_sha`가 계속 비어
  `personalLevel`을 만들 수 없다. 켜면 full clone으로 바뀌므로 워커 디스크를 먼저 본다.
- `C_COMPUTE_URL`이 빈 값 — 결과를 정상 저장해도 공고 매칭·Skill Gap 계산이 돌지 않는다.
