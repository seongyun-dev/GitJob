# S15P21E102-207 Phase 7 Service Spark Worker-2 가입

- 수행일: 2026-09-11 (UTC 기준 2026-09-10 23:42-23:52)
- 대상: `J15E102` service 서버, `J15E102A` Spark Master
- 상태: `CONDITIONAL` — Worker-2 등록은 완료, executor 참여는 Phase 8 필요
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 6 Spark Master·Worker-1 전환](2026-09-10-hdfs-spark-two-host-phase6-spark-master-tailscale.md)

## 1. 범위와 작업 전 게이트

service 서버의 기존 `gitjob-cluster-worker` project에 Spark Worker-2만 추가했다.
DataNode-4는 재생성하지 않았고 core/app stack, data 서버의 HDFS·Spark daemon도
건드리지 않았다. balancer, `setrep`, 운영 데이터 배치 변경은 없다.

| 항목 | 작업 전 결과 |
|---|---|
| service disk / MemAvailable | 282 GiB free (9% 사용) / 10 GiB |
| service core/app 컨테이너 | 15개 모두 실행, 주요 서비스 healthy |
| cluster-worker project | DataNode-4만 실행 (healthy, 8시간) |
| service host `7078`, `8084` | 미사용 |
| Spark Master / Worker-1 | 둘 다 healthy, host network |
| Live / Dead DataNode | 4 / 0 |
| fsck `/gitjob` | HEALTHY, missing/corrupt/under-replicated 0 / 0 / 0 |
| 양쪽 서버 checkout | `5eaf595`, clean |

증거는 service 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase7-20260910T234233Z
```

## 2. Phase 6 결함의 선반영

Phase 6에서 data 서버 Spark daemon이 겪은 두 결함은 Worker-2에도 그대로 해당한다.
`compose.ec2-cluster-worker.yaml`의 `spark-worker2`도 `network_mode: host`이면서
`hostname:`과 `SPARK_LOCAL_IP`가 없었다. 런타임에서 다시 발견하지 않도록 가입 전에
같은 수정을 적용했다.

- `hostname: spark-worker2`와 `extra_hosts`로 자기 이름을 Tailscale 주소에 매핑
- `SPARK_LOCAL_IP`로 관리 UI bind 주소 고정

두 번째 항목은 data 서버보다 이 호스트에서 더 중요하다. service 서버는 public
`80`, `443`을 열어두므로 wildcard listener는 관리 UI를 public interface에 올린다.

```text
941c6f4 [S15P21E102-207] fix: Worker-2 에 host network Spark bind 보정 선반영
```

healthcheck는 이미 `${SERVICE_TS_IP}:8084`를 대상으로 하고 있어 수정하지 않았다.

렌더 검증 결과는 다음과 같다.

| 항목 | 값 |
|---|---|
| network_mode | `host` |
| Compose `ports` 선언 | 없음 |
| hostname | `spark-worker2` |
| extra_hosts | `spark-worker2=100.71.215.74` |
| `SPARK_LOCAL_IP` | `100.71.215.74` |
| `SPARK_MASTER_URL` | `spark://100.70.66.38:7077` |
| `SPARK_WORKER_HOST` | `100.71.215.74` |
| cores / memory | 1 / 1G |
| cpus / mem_limit | 1.0 / 1536 MiB |

`cluster-worker.sh config`는 `config --quiet`이므로 성공 시 아무것도 출력하지
않는다. 값 확인에는 `--quiet` 없는 별도 렌더가 필요하다.

## 3. 가입 결과

`CLUSTER_WORKER_PROFILES=hdfs-worker,spark-worker`로 기동해 DataNode-4를 유지한 채
Worker-2만 추가했다.

```text
INFO Worker: Starting Spark worker 100.71.215.74:7078 with 1 cores, 1024.0 MiB RAM
INFO WorkerWebUI: Bound WorkerWebUI to 100.71.215.74, and started at http://spark-worker2:8084
INFO Worker: Successfully registered with master spark://100.70.66.38:7077
```

Master 상태 조회 결과 서로 다른 두 Tailscale IP의 Worker가 모두 `ALIVE`다.

```text
master status: ALIVE | url: spark://100.70.66.38:7077
aliveworkers: 2 | cores: 3 | coresused: 0
  100.70.66.38:7078   state=ALIVE  cores=2  mem=2048MB
  100.71.215.74:7078  state=ALIVE  cores=1  mem=1024MB
```

listener는 Tailscale 주소 전용이고 wildcard bind는 없다.

```text
[::ffff:100.71.215.74]:7078
[::ffff:100.71.215.74]:8084
```

| 검증 | 결과 |
|---|---|
| Worker-2 health / restart | healthy / 0 |
| Master가 본 alive worker | 2 (서로 다른 Tailscale IP) |
| DataNode-4 | 재생성되지 않음, 계속 healthy |
| service public probe `7078`,`8084`,`9864`,`9866` | 모두 차단 |
| service public `80`, `443` | 정상 |
| core/app 컨테이너 15개 ID | 작업 전과 동일 |
| service API `/health` | `200` |
| service MemAvailable | 10 → 9 GiB (Worker-2 몫, 게이트 4 GiB 이상 유지) |
| service disk free | 282 → 280 GiB (이미지 빌드) |
| Live / Dead DataNode | 4 / 0 |
| Phase 5 canary 교차 host 게이트 | `PASS` |

## 4. 회귀 확인에서 드러난 제약 — Worker-2 executor가 job에 참여하지 못한다

Worker가 둘이 된 상태에서 기존 smoke job이 여전히 도는지 확인했다. job 자체는
성공했고 결과도 동일하다.

```text
exit=0
row_count=3
content_sha256=4b460b76a004e9f1469e090f9311ddd7f7dbf8146b42639d068f073316692476
```

digest는 Phase 6에서 기록한 기준선·전환 전·전환 후 세 값과 같다. 그러나 executor
배치를 보면 정상이 아니다.

```text
Granted executor ID app-.../0 on hostPort 100.70.66.38:7078
Granted executor ID app-.../1 on hostPort 100.71.215.74:7078
Granted executor ID app-.../2 on hostPort 100.71.215.74:7078
Granted executor ID app-.../3 on hostPort 100.71.215.74:7078
```

실제로 등록된 executor는 data 호스트의 것 하나뿐이고, Worker-2에는 executor가
반복 부여됐다가 모두 즉시 종료됐다.

```text
Executor app-.../1 finished with state EXITED message Command exited with code 1
Executor app-.../2 finished with state EXITED message Command exited with code 1
```

Worker-2의 executor stderr에 원인이 있다.

```text
--driver-url spark://CoarseGrainedScheduler@spark-worker:40797
```

client mode의 driver는 data 서버 `spark-worker` 컨테이너 안에 있고, 자기 주소를
Compose hostname `spark-worker`로 광고한다. 이 이름은 data 서버에서만 해석된다.
Phase 6에서 그 컨테이너에 `extra_hosts`를 넣었기 때문에 data 호스트 executor는
연결되지만, service 호스트의 executor는 이름을 풀지 못해 실패한다.

출처는 `Infra/scripts/_lib.sh`의 기본값이다.

```text
driver_host="$(spark_setting SPARK_DRIVER_HOST spark-worker)"
```

`.env.data`에 `SPARK_DRIVER_HOST`를 비롯한 Phase 8 변수가 아직 없어 이 기본값이
쓰인다. 계획 Phase 8이 `spark.driver.host=DATA_TS_IP`와 고정 port를 넣는 단계이므로
설계상 예정된 순서지만, 그 전까지는 다음 상태다.

- Worker-2는 `ALIVE`로 등록되지만 어떤 job에도 실제로 기여하지 못한다
- 모든 job이 Worker-2에서 executor 기동·실패·재시도를 반복해 낭비가 발생한다
- 재시도 한도를 넘기면 job이 실패할 수 있다. 이번 실행은 Worker-1 executor가
  작업을 끝내 성공했다

따라서 이 Phase는 `PASS`가 아니라 `CONDITIONAL`로 판정한다. 계획의 Phase 7 완료
조건인 "Master UI에서 서로 다른 Tailscale IP의 Worker 두 개가 `ALIVE`"는 충족했으나,
Worker-2를 실제로 사용하려면 Phase 8이 선행돼야 한다.

## 5. 기존 서비스 영향

`cluster-worker.sh`가 별도 project를 강제하므로 `gitjob-service` project는 호출되지
않았다. core/app 컨테이너 15개의 ID가 작업 전후 동일하고 모두 healthy를 유지했으며
`/health`는 `200`이다. DataNode-4도 재생성되지 않았고 HDFS는 Live 4 / Dead 0,
fsck HEALTHY, missing/corrupt/under-replicated 0이다.

Worker-2가 상주하면서 service 서버 MemAvailable이 10 GiB에서 9 GiB로 줄었다. 계획
6절의 최소 4 GiB 기준은 유지된다.

## 6. 롤백

Worker-2만 제거하면 되고 DataNode-4와 core/app에는 영향이 없다.

```text
CLUSTER_WORKER_PROFILES=spark-worker ./Infra/scripts/cluster-worker.sh down
```

`down`은 named volume을 삭제하지 않는다. DataNode-4를 유지한 채 Worker-2만 내리려면
위와 같이 profile을 `spark-worker`로만 지정한다. Master 쪽에서는 alive worker가
1개로 줄고 Worker-1 단독 실행으로 돌아간다. 이 경우 4절의 executor 낭비도 사라진다.

## 7. 남은 한계와 다음 Phase

- **Worker-2 executor 미참여**(4절). Phase 8의 직접 선행 조건이다
- Phase 8에서는 `spark.driver.host`/`spark.driver.port`/BlockManager port를
  고정하는 것과 함께, data 서버 UFW가 service Tailscale IP에서 오는 해당 port를
  허용하는지 확인해야 한다. 현재 data 서버의 bridge 한정 규칙에는 Spark port가 없다
- Phase 6의 replication 3 배치 문제는 미결정 상태다. Spark 클라이언트가
  `replication=3`으로 쓰는데 `/rack-b` DataNode가 1대라 새 write가 영구
  under-replicated가 된다
- Phase 5의 재복제 미검증, mis-replicated 240건, Phase 3의 Saramin `.uploading-*`
  임시 파일 2개도 그대로 남아 있다

Phase 8에서 Spark driver와 BlockManager port를 고정한 뒤, Phase 9에서 두 host의
executor가 각각 task를 수행하는지 검증한다. Phase 9의 결과 비교에는 Phase 6에서
추가한 내용 기반 digest 도구를 사용한다.
