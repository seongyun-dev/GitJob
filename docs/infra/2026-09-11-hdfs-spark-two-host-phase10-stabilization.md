# S15P21E102-207 Phase 10 서비스 재개와 안정화 관측

- 수행일: 2026-09-11 (UTC 기준 01:18-01:50)
- 대상: 양쪽 EC2 전체
- 상태: `PASS` — 31분 연속 관측에서 이상치 0건
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 9 분산 처리 검증](2026-09-11-hdfs-spark-two-host-phase9-distributed-verification.md)

## 1. 범위와 "재개"에 대한 정정

계획 7절 Phase 10은 "Collector와 분석 Worker를 재개하고 최소 30분 동안 관측한다"로
되어 있다. 그러나 이번 작업에서 두 컨테이너를 중지한 적이 없다.

```text
gitjob-data-collector-1   Up 10 hours (healthy)   restarts=0
gitjob-data-worker-1      Up 10 hours (healthy)   restarts=0
```

Phase 2와 Phase 3에서 HDFS write quiesce를 위해 중지했다가 같은 Phase 안에서
재개했고, Phase 4 이후로는 계속 실행 상태였다. 따라서 이 단계에서 재개할 대상이
없어 관측만 수행했다.

## 2. 관측 방법

양쪽 host에 읽기 전용 sampler를 설치해 2분 간격으로 16회, 총 31분을 기록했다.
증거는 양쪽 서버의 다음 경로에 있다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase10-20260911T011845Z/
  data-samples.tsv      (data host, 16 samples)
  service-samples.tsv   (service host, 16 samples)
  fsck-start.txt / fsck-end.txt
```

sampler는 컨테이너 제어, HDFS write, 설정 변경을 일절 하지 않는다.

## 3. Data host 관측 결과

16개 샘플 전 구간에서 다음 값이 변하지 않았다.

| 항목 | 값 |
|---|---|
| Live / Dead DataNode | 4 / 0 |
| under-replicated block | 0 |
| Spark alive worker | 2 |
| Collector | `healthy`, 재시작 0 |
| 분석 Worker | `healthy`, 재시작 0 |
| Tailscale direct 연결 | 유지 (VPC private 경유, DERP 아님) |
| root 여유 공간 | 175 GB |

변동이 있었던 값은 다음 범위였다.

| 항목 | 범위 |
|---|---|
| MemAvailable | 11-12 GiB |
| load1 | 0.97 - 2.26 |

시작·종료 fsck가 동일하다.

```text
Total blocks (validated): 21683
Under-replicated blocks:  0
Mis-replicated blocks:    0
Missing blocks:           0
Corrupt blocks:           0
Status: HEALTHY
```

## 4. Service host 관측 결과

16개 샘플 전 구간에서 다음 값이 변하지 않았다.

| 항목 | 값 |
|---|---|
| `GET /health` | `200` |
| `GET /nginx-health` (HTTPS) | `200` |
| core/app 컨테이너 ID 집합 | 불변 (해시 `f44d3238`) |
| backend/nginx/postgres/redis/kafka/kafka-connect 재시작 | `0/0/0/0/0/0` |
| Spark Worker-2 | `healthy`, 재시작 0 |
| DataNode-4 | `healthy`, 재시작 0 |
| OOM 발생 | 0 |
| MemAvailable | 8 GiB |
| root 여유 공간 | 278 GB |

load1은 0.59-1.80 범위였다. 자동 이상치 검사에서 걸린 샘플은 0개다.

public 경계도 관측 중 재확인했다.

| 경로 | 결과 |
|---|---|
| `https://j15e102.p.ssafy.io/` | `200` |
| `https://j15e102.p.ssafy.io/health` | `200` |
| `https://localhost/api/v1/analyses` | `401` (인증 요구, 정상) |
| Backend 최근 30분 오류 로그 | 0줄 |

계획 10절의 "자원 경합이나 API 지연이 확인되면 Spark Worker-2를 먼저 중지한다"
조건에는 해당하지 않았다.

## 5. 관측하지 못한 항목

### 5.1 분석 요청 접수와 완료

계획은 이 항목을 관측 대상으로 둔다. 그러나 현재 실사용자 트래픽이 없어 관측할
대상이 존재하지 않는다.

```text
analysis_job     0건
analysis_outbox  0건
analysis_evidence 0건
```

따라서 이 항목은 "API 경계가 정상 응답한다"까지만 확인됐다. 인증된 사용자의 실제
분석 요청이 접수되어 완료되는 경로는 이 단계에서 검증되지 않았으며, 이는
[2026-09-10 구현 상태 문서](../2026-09-10-current-status.md)가 "실계정 로그인부터
C 결과까지 E2E"를 미완료로 둔 것과 같은 경계다.

### 5.2 Kafka consumer lag

`kafka-consumer-groups.sh --list` 결과가 비어 있어 lag을 측정할 consumer group이
없다. topic 자체는 정상 존재한다(`github.events`, `jobs.collected`, `so.raw` 등).
분석 Worker는 현재 HTTP 서비스로 동작하며 관측 구간에 Kafka consume이 없었다.
실제 트래픽이 생긴 뒤 별도로 관측해야 한다.

## 6. 관측 중 확인한 Tailscale 노출 범위

Phase 8 2절에서 "`ts-input -i tailscale0 -j ACCEPT`는 peer 한 대가 아니라 tailnet
전체를 허용한다"고 가능성으로 적었다. 이번 단계에서 실측으로 확인했다.

현재 tailnet에는 peer 9대가 있다.

```text
linux    j15e102a          100.70.66.38
linux    j15e102           100.71.215.74
windows  desktop-* 7대
```

tailnet에 속한 작업 환경에서 인증 없이 다음 포트에 도달한다.

| 서버 | 도달 | 차단 |
|---|---|---|
| data `100.70.66.38` | `8020` NameNode RPC, `9870` UI, `9864`·`9866` DataNode, `7077` Spark Master, `8083`·`8084` UI | - |
| service `100.71.215.74` | `9864`·`9866` DataNode-4, `7078`·`8084` Worker-2 | `5432`, `6379`, `9092` |

PostgreSQL, Redis, Kafka는 Tailscale 주소에 bind되어 있지 않아 차단된다. 즉 core
상태 저장소는 노출되지 않는다.

요청된 public 경계 정책("SSH 22, HTTP 80, HTTPS 443만 public, 나머지는 Tailscale")은
정확히 지켜지고 있다. 다만 실효 경계가 "EC2 두 대"가 아니라 "tailnet 전체"라는 점을
기록한다. 특히 `8020`(HDFS RPC)과 `7077`(Spark Master)은 인증이 없어 tailnet 안이면
HDFS write나 Spark job 제출이 가능하다.

UFW로는 좁힐 수 없다. `ts-input` 체인이 UFW 체인보다 먼저 ACCEPT하므로 UFW 규칙은
`tailscale0` 트래픽에 적용되지 않는다. 좁히려면 Tailscale ACL에서 server tag 간에만
해당 포트를 허용하는 방식이어야 한다. 이는 운영 정책 결정이므로 이번 단계에서
변경하지 않았다.

## 7. sampler 구현 메모

service sampler의 OOM 집계에 `grep -ci ... || echo 0` 형태를 썼는데, `grep -c`가
0을 반환할 때 종료 코드가 1이라 `|| echo 0`이 함께 실행돼 파일에 `0` 줄이 하나씩 더
기록된다. 집계 값 자체(OOM 0)는 정확하고 판정에 영향은 없으나, 이 sampler를 재사용할
때는 `|| true`로 바꾸는 편이 낫다. sampler는 `/tmp`에만 두었고 저장소에 넣지 않았다.

## 8. 최종 상태

| 검증 | 결과 |
|---|---|
| 관측 시간 | 31분 (2분 간격 16 샘플 × 2 host) |
| 이상치 | 0건 |
| HDFS | Live 4 / Dead 0, fsck HEALTHY, under/mis/missing/corrupt 0 |
| Spark | Worker 2 `ALIVE` 유지 |
| service API | `/health` `200` 전 구간 |
| 컨테이너 재시작 | 전 서비스 0 |
| OOM | 0 |
| Tailscale | direct 유지 |

Phase 10은 `PASS`다. 계획 7절의 Phase 0-10이 모두 완료됐다.

## 9. 남은 항목

- **Tailscale ACL 범위**(6절). tailnet 전체가 HDFS/Spark 제어 평면에 접근 가능하다
- **실사용자 E2E**(5.1절). 분석 요청 접수·완료와 Kafka lag은 실제 트래픽이 필요하다
- **입력 규모 확대**. 계획 Phase 9는 1일치 이후 1개월로 확대하도록 한다. 6개월 전체는
  별도 승인 대상이다
- Phase 3의 Saramin `.uploading-*` 임시 파일 2개
- 계획 12절의 "호스트당 DataNode 1개 정리"는 별도 작업으로 남아 있다
