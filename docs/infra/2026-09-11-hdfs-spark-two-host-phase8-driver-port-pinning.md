# S15P21E102-207 Phase 8 Spark driver·BlockManager 주소·포트 고정

- 수행일: 2026-09-11 (UTC 기준 2026-09-10 23:54-23:58)
- 대상: `J15E102A` data 서버 `.env.data`, 양쪽 host의 Spark 실행 경로
- 상태: `PASS` — 두 host executor 참여와 교차 host task 수행까지 확인
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 7 Service Spark Worker-2 가입](2026-09-11-hdfs-spark-two-host-phase7-service-spark-worker2.md)

## 1. 범위와 작업 전 게이트

Phase 7에서 `CONDITIONAL`로 남긴 제약, 즉 service 호스트 executor가 driver에
연결하지 못하는 문제를 해소했다. 변경은 data 서버 `.env.data`의 Spark 실행 변수
8개뿐이며 컨테이너 재생성, 이미지 재빌드, Compose 파일 변경, HDFS 조작은 없다.

| 항목 | 작업 전 결과 |
|---|---|
| Phase 8 변수 | 전부 미설정 (`_lib.sh` 기본값 사용) |
| Spark alive worker / cores | 2 / 3 |
| data host `40001`, `40002`, `41000` | 미사용 |
| Live / Dead DataNode | 4 / 0 |
| fsck `/gitjob` | HEALTHY, under-replicated 0 |
| 양쪽 서버 checkout | `7405ddd`, clean |

증거는 data 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase8-20260910T235439Z
```

`.env.data`의 변경 전 사본을 `env.data.before`로 권한 `0600`으로 보존했다.

## 2. Public 경계 재확인 — UFW 변경이 필요하지 않다

계획 4.3절은 "UFW 또는 동등한 host 경계에서 `tailscale0`로 들어오는 peer
Tailscale IP만 허용한다"고 적었다. 실제 경계를 확인한 결과 이번 단계에서 UFW에
규칙을 추가할 필요가 없다.

양쪽 서버의 `INPUT` 체인에서 Tailscale 체인이 UFW 체인보다 먼저 실행된다.

```text
-P INPUT DROP
-A INPUT -j ts-input
-A INPUT -j ufw-before-logging-input
...
-A ts-input -i tailscale0 -j ACCEPT
```

즉 `tailscale0`로 들어온 패킷은 UFW 체인에 도달하기 전에 ACCEPT된다. Tailscale
주소에만 bind된 포트는 UFW 규칙 없이 peer에서 닿고, public interface는 UFW의
기본 deny와 아래 허용 목록만으로 계속 보호된다.

| 서버 | public 허용 |
|---|---|
| `J15E102A` data | `22` |
| `J15E102` service | `22`, `80`, `443` |

이번 단계에서 이 목록을 바꾸지 않았다. 신규 포트 `40001`, `40002`, `41000`은
양쪽 서버 public FQDN probe에서 모두 차단됐고 `80`, `443`은 정상이다.

> 주의로 남길 점: `-i tailscale0 -j ACCEPT`는 peer 한 대가 아니라 **tailnet 전체**를
> 허용한다. 두 EC2 외의 tailnet 기기도 HDFS·Spark 포트에 접근할 수 있다. peer 단위로
> 더 좁히려면 UFW가 아니라 Tailscale ACL 또는 Tailscale netfilter 모드 조정이
> 필요하다. UFW 규칙을 추가해도 `ts-input`이 먼저 ACCEPT하므로 효과가 없다.

## 3. 설정 변경

`.env.data`에 계획 7절 Phase 8의 값을 추가했다. 기존 줄은 바꾸지 않고 주석과 함께
덧붙였다.

```text
SPARK_DRIVER_BIND_ADDRESS=100.70.66.38
SPARK_DRIVER_HOST=100.70.66.38
SPARK_DRIVER_PORT=40001
SPARK_DRIVER_BLOCK_MANAGER_PORT=40002
SPARK_EXECUTOR_BLOCK_MANAGER_PORT=41000
SPARK_PORT_MAX_RETRIES=15
SPARK_EXECUTOR_CORES=1
SPARK_CORES_MAX=2
```

`Infra/scripts/_lib.sh`의 `spark_submit_network_args`가 이 값을 읽어 네 개의 Spark
wrapper 전체에 동일하게 적용한다. 조립 결과를 실행 전에 확인했다.

```text
--conf spark.driver.bindAddress=100.70.66.38
--conf spark.driver.host=100.70.66.38
--conf spark.hadoop.dfs.client.use.datanode.hostname=true
--conf spark.driver.port=40001
--conf spark.driver.blockManager.port=40002
--conf spark.blockManager.port=41000
--conf spark.port.maxRetries=15
--conf spark.executor.cores=1
--conf spark.cores.max=2
```

Phase 7에서 문제가 된 기본값은 다음 한 줄이었다.

```text
driver_host="$(spark_setting SPARK_DRIVER_HOST spark-worker)"
```

`SPARK_DRIVER_HOST`가 비어 있어 driver가 자기 주소를 Compose hostname
`spark-worker`로 광고했고, 그 이름은 data 서버에서만 해석됐다. 이제 Tailscale
주소를 광고하므로 양쪽 host에서 동일하게 해석된다.

## 4. 검증 결과

Phase 7과 동일한 smoke job을 별도 경로로 실행했다.

| 검증 | 결과 |
|---|---|
| job 종료 코드 | 0 |
| `row_count` | 3 |
| content digest | `4b460b76…92476` (기준선과 동일) |
| `sparkDriver` 포트 | `40001` (고정값 사용) |
| driver BlockManager | `100.70.66.38:40002` |
| executor BlockManager (data) | `100.70.66.38:41000` |
| executor BlockManager (service) | `100.71.215.74:41000` |

executor가 양쪽 host에 하나씩 배치되고 **둘 다 등록에 성공했다.** Phase 7에서
service 호스트 executor가 반복 실패하던 현상이 사라졌다.

```text
Granted executor ID app-.../0 on hostPort 100.70.66.38:7078
Granted executor ID app-.../1 on hostPort 100.71.215.74:7078
Registered executor ... (100.70.66.38:53770)
Registered executor ... (100.71.215.74:55074)
```

task도 두 host에서 실제로 수행됐다.

```text
Starting task 0.0 in stage 0.0 (TID 0) (100.70.66.38,  executor 0, partition 0)
Starting task 1.0 in stage 0.0 (TID 1) (100.71.215.74, executor 1, partition 1)
Finished task 0.0 in stage 0.0 (TID 0) in 2943 ms on 100.70.66.38  (executor 0) (1/2)
Finished task 1.0 in stage 0.0 (TID 1) in 3698 ms on 100.71.215.74 (executor 1) (2/2)
Starting task 0.0 in stage 2.0 (TID 2) (100.71.215.74, executor 1, partition 0, NODE_LOCAL)
```

계획 Phase 9의 완료 조건 중 "서로 다른 두 Tailscale IP에서 executor 실행"과
"양쪽 executor가 각각 하나 이상의 task 수행"은 이 시점에 이미 충족됐다. 다만 Phase 9가
요구하는 shuffle read/write 관측과 실제 GH Archive 입력 검증은 아직 수행하지 않았다.

## 5. Under-replicated 재발과 정리

검증 후 전체 fsck의 under-replicated가 0에서 3으로 올라갔다. Phase 6 7절에 기록한
것과 같은 원인이다. Spark 클라이언트는 `replication=3`으로 쓰는데 `/rack-b`에
DataNode가 한 대뿐이라 세 번째 replica를 배치하지 못한다.

> 2026-09-11 추가: 이 단계 이후 확인한 바로는 단순한 rack-b 노드 부족이 아니라
> rack-a DataNode가 DataNode-4로 블록을 전송하지 못하는 결함이 겹쳐 있었다.
> 수정 후 같은 job의 두 블록이 모두 rack 교차 배치에 성공한다.
> [DataNode 간 재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md) 참조.

대상은 전부 이번·직전 단계의 테스트 출력이었다.

```text
/gitjob/demo/phase7/smoke/gitjob-smoke-v1/part-00000-...
/gitjob/demo/phase7/smoke/gitjob-smoke-v1/part-00001-...
/gitjob/demo/phase8/smoke/gitjob-smoke-v1/part-00001-...
```

클러스터 기본값과 맞추기 위해 `setrep -w 1`로 되돌려 under-replicated를 0으로
복구했다. 운영 데이터의 배치는 바꾸지 않았고 mis-replicated 240건도 그대로다.

이 문제는 Phase 9 이전에 결정하는 편이 낫다. Phase 9는 1일치 GH Archive 실제 job을
포함하므로, 그 출력이 같은 조건이면 운영 경로에서 under-replicated가 누적된다.
계획 7절 Phase 8이 정한 공통 설정 지점(`spark_submit_network_args`)에
`spark.hadoop.dfs.replication`을 함께 넣는 것이 가장 적은 변경이다.

## 6. 기존 서비스 영향

컨테이너를 재생성하지 않았으므로 영향이 없다. service 서버 core/app 컨테이너 ID는
작업 전후 동일하고 `/health`는 `200`, MemAvailable은 9 GiB다. HDFS는 Live 4 /
Dead 0, fsck HEALTHY, missing/corrupt/under-replicated 0이다.

data 서버에서 driver가 사용하는 `40001`, `40002`는 job 실행 중에만 열리고
`spark.driver.bindAddress=100.70.66.38`로 Tailscale 주소에만 bind된다. service
서버 executor의 `41000`도 Worker-2의 `SPARK_LOCAL_IP`가 Tailscale 주소이므로
동일하다.

## 7. 롤백

`.env.data`에서 3절의 8개 줄을 제거하거나 `env.data.before`로 되돌린다. 컨테이너
재생성은 필요하지 않고 다음 job 제출부터 이전 동작으로 돌아간다. 단, 그 상태는
Phase 7 4절의 제약, 즉 Worker-2 executor가 참여하지 못하고 매 job마다 기동·실패를
반복하는 상태다.

## 8. 남은 한계와 다음 Phase

- **replication 3 배치 문제**(5절)는 Phase 9 전에 결정하는 것을 권장한다
- `ts-input`의 tailnet 전체 허용 범위(2절)는 peer 단위로 좁힐지 별도 판단이 필요하다
- Phase 5의 재복제 미검증, mis-replicated 240건, Phase 3의 Saramin `.uploading-*`
  임시 파일 2개는 그대로 남아 있다
- 동시 Spark job은 계획 6절대로 1개로 제한된 상태다(`spark.cores.max=2`,
  `spark.executor.cores=1`)

Phase 8은 `PASS`다. Phase 9에서 synthetic shuffle canary, `/gitjob/demo/distributed-proof`
HDFS canary, 1일치 GH Archive Repo Activity 실제 job 순서로 확대하고, 결과 비교에는
Phase 6에서 추가한 내용 기반 digest 도구를 사용한다.
