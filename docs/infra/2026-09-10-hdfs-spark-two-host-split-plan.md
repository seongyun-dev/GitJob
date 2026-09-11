# S15P21E102-207 HDFS·Spark 2-Host Split Plan

- Jira: `S15P21E102-207`
- 작성일: 2026-09-10
- 상태: Phase 0-10 완료. 후속 항목은 Phase 10 기록 9절 참조
- 대상 브랜치: `infra/S15P21E102-207-infra-hdfs-spark-2-split`
- 대상 서버:
  - `J15E102A`: 기존 data 서버
  - `J15E102`: 기존 service/core 서버

## 1. 목적

현재 `J15E102A` 한 대에서 실행 중인 HDFS와 Spark를 두 EC2에 걸친 물리 분산
구성으로 확장한다.

1차로 `J15E102`에 HDFS DataNode를 가입시켜 저장 계층을 두 물리 서버로
확장한다. 2차로 같은 서버에 Spark Worker를 가입시켜 하나의 Spark job이 두
서버의 CPU를 실제로 사용하도록 만든다.

이번 작업의 우선순위는 다음과 같다.

1. 기존 HDFS 데이터와 named volume 보존
2. 기존 public 서비스 무중단 유지
3. application public ingress는 HTTP/HTTPS `80`, `443`만 유지하고 기존 SSH
   `22` 외 관리 포트를 추가로 공개하지 않음
4. HDFS·Spark의 서버 간 통신과 관리 UI는 Tailscale 전용
5. 작은 실제 데이터로 저장·연산 분산을 먼저 증명
6. GH Archive Raw 전체 복제와 기존 DataNode 정리는 후속 작업으로 분리

이번 구성은 2-host 분산 저장·처리 구성이지만 HA 구성은 아니다. NameNode,
Spark Master, Kafka는 계속 단일 장애점으로 남는다.

## 2. 현재 상태와 제약

현재 data 서버에는 NameNode, 논리 DataNode 3개, Spark Master/Worker,
Collector와 분석 Worker가 함께 실행된다. DataNode 3개는 서로 다른 named volume을
사용하지만 동일한 320 GiB EBS의 root filesystem을 공유한다.

2026-09-09 기록 기준 상태는 다음과 같다.

| 항목 | 값 |
|---|---:|
| HDFS DFS Used | 114.17 GiB |
| HDFS Configured Capacity | 926.79 GB |
| data host 실제 filesystem | 309 GiB |
| data host 실제 여유 공간 | 약 79 GiB |
| 기본 replication | 1 |

`Configured Capacity`는 동일 filesystem을 DataNode 3개가 각각 보고해 부풀려진
논리 합계다. 운영 용량 판단은 항상 host `df`를 기준으로 한다.

service 서버는 Backend, Frontend, Nginx, PostgreSQL, Redis, Kafka, Kafka Connect와
Jenkins를 담당한다. 문서상 사양은 4 vCPU, RAM 15 GiB, swap 없음, 단일 320 GiB
EBS다. 실제 작업 전 현재 사용량을 다시 측정하며 과거 측정값으로 배포를 승인하지
않는다.

## 3. 목표 토폴로지

```text
J15E102A · data server                    J15E102 · service server
DATA_TS_IP                               SERVICE_TS_IP

+--------------------------------+       +--------------------------------+
| HDFS NameNode                  |<------| HDFS DataNode-4                |
| HDFS DataNode-1/2/3            |       | independent named volume       |
|                                |       |                                |
| Spark Master                   |<------| Spark Worker-2                 |
| Spark Worker-1                 |       | 1 core / 1 GiB initially       |
|                                |       |                                |
| Collector / analysis Worker    |       | existing core/app services     |
+--------------------------------+       +--------------------------------+

logical failure domain: /rack-a          logical failure domain: /rack-b
```

`/rack-a`, `/rack-b`는 물리 rack을 의미하지 않는다. 두 EC2를 구분하기 위한 HDFS
논리 failure domain이다.

## 4. 네트워크 원칙

### 4.1 Public 경계

Application public ingress는 기존과 같이 다음 두 포트만 유지한다.

| 포트 | 용도 |
|---:|---|
| 80 | HTTP/Nginx |
| 443 | HTTPS/Nginx |

HDFS, Spark, PostgreSQL, Redis, Kafka 및 관리 UI를 public interface에 추가로
노출하지 않는다. 양쪽 서버의 기존 SSH `22`는 운영 관리 경로로 유지한다. AWS
public 보안 규칙도 이 작업에서 확대하지 않는다.

### 4.2 Tailscale 경계

클러스터 설정에서는 EC2 private IP나 Compose service name 대신 각 서버의
Tailscale IPv4를 사용한다. 실제 IP는 배포 전에 `tailscale ip -4`로 조회해
`DATA_TS_IP`, `SERVICE_TS_IP`에 기록한다. 컨테이너 DNS 전파 여부에 의존하지
않도록 초기 구현에서는 MagicDNS hostname을 사용하지 않는다.

Tailscale peer 간 연결은 `tailscale ping` 결과가 `direct`일 때만 다음 단계로
진행한다. DERP relay만 가능한 경우 대량 HDFS 전송과 Spark shuffle을 시작하지
않는다.

### 4.3 포트 계획

| 구성요소 | data 서버 | service 서버 |
|---|---:|---:|
| NameNode RPC | 8020 | - |
| NameNode UI | 9870 | - |
| DataNode-1 HTTP/Data/IPC | 9864/9866/9867 | - |
| DataNode-2 HTTP/Data/IPC | 9874/9876/9877 | - |
| DataNode-3 HTTP/Data/IPC | 9884/9886/9887 | - |
| DataNode-4 HTTP/Data/IPC | - | 9864/9866/9867 |
| Spark Master RPC/UI | 7077/8083 | - |
| Spark Worker RPC/UI | 7078/8084 | 7078/8084 |
| Spark Driver RPC | 40001 | - |
| Driver BlockManager | 40002 | - |
| Executor BlockManager | 41000-41015 | 41000-41015 |

UFW 또는 동등한 host 경계에서는 `tailscale0`로 들어오는 peer Tailscale IP만
허용한다. 포트 설정 후 다음을 모두 검증한다.

- peer Tailscale IP에서 허용 포트 연결 성공
- public IP에서 Hadoop/Spark 포트 연결 실패
- `ss -lntp`에서 의도한 주소와 포트만 listen
- 기존 public `80`, `443` 정상

## 5. Compose 격리 설계

### 5.1 Data 서버

`Infra/compose/compose.ec2-data-cluster.yaml`을 추가한다. 기존 data Compose
project와 named volume은 유지하고 EC2 분산 구성에 필요한 네트워크·주소만
override한다.

- NameNode RPC를 `DATA_TS_IP:8020`으로 제공
- DataNode 1/2/3을 host network와 고유 포트로 전환
- Spark Master/Worker-1을 host network와 Tailscale 주소로 전환
- Collector와 분석 Worker는 기존 bridge network 유지
- 기존 HDFS named volume 이름과 mount path 유지

### 5.2 Service 서버

`Infra/compose/compose.ec2-cluster-worker.yaml`을 별도 Compose project로
기동한다.

```text
gitjob-service
  backend, frontend, nginx, postgres, redis, kafka, kafka-connect, jenkins

gitjob-cluster-worker
  hdfs-datanode4, spark-worker2
```

신규 project는 기존 core/app Compose project를 참조하거나 재생성하지 않는다.
두 신규 서비스는 host network와 Tailscale IP를 사용하므로 기존 service Docker
network에 가입하지 않는다.

`network_mode: host` 서비스에는 Compose `ports`를 함께 선언하지 않는다.
배포 전에 최종 `docker compose config`를 렌더링해 이를 확인한다.

## 6. 자원 제한

service 서버는 사용자 요청 처리와 상태 저장을 우선한다. 신규 분산 노드는 다음
값으로 작게 시작한다.

| 서비스 | 초기 제한 |
|---|---|
| Spark Worker-2 | 1 core, 1 GiB |
| DataNode-4 JVM | 512 MiB-1 GiB 범위 |
| 동시 Spark job | 1개 |
| service host 최소 MemAvailable | 4 GiB |
| service host 최소 disk available | demo 기준 50 GiB |
| service host 최소 disk free ratio | 25% |

GH Archive Raw 전체를 replication 2로 만들려면 최소 114 GiB의 추가 블록 공간뿐
아니라 Docker image, log, Spark shuffle과 안전 여유가 필요하다. service 서버의
실측 여유 공간이 150 GiB 이상이어도 이번 작업에서는 Raw 전체 복제를 수행하지
않는다.

## 7. 단계별 실행 계획

### Phase 완료 및 문서화 규칙

각 Phase는 구현이나 명령 실행만 끝났다고 완료 처리하지 않는다. 다음 내용을
`docs/infra/YYYY-MM-DD-hdfs-spark-two-host-phaseN-<topic>.md`에 기록하고,
문서 링크를 `docs/infra/README.md`에 추가한 뒤에만 다음 Phase로 넘어간다.

- 작업 전 상태와 전제 조건
- 실제 수행 내용과 변경 파일
- 검증 명령 및 실측 결과
- 기존 서비스 영향 여부
- 발견된 위험과 미해결 항목
- 롤백 절차와 실행 여부
- 다음 Phase 진행 가능 여부(`PASS`, `CONDITIONAL`, `BLOCKED`)

비밀값, 인증서, SSH key, 전체 환경 변수 출력은 문서에 남기지 않는다. 실패한
Phase도 생략하지 않고 실패 지점과 원복 결과를 같은 형식으로 기록한다.

### Phase 0. 운영 preflight와 기준 상태 기록

양쪽 서버에서 다음을 기록한다.

- Tailscale IPv4, peer 연결 방식과 latency
- `df -h`, `free -h`, `uptime`, `docker stats --no-stream`
- 기존 listen port
- 기존 service health와 컨테이너 ID/시작 시각
- NameNode cluster ID
- DataNode 1/2/3 UUID와 named volume mountpoint
- `hdfs fsck /gitjob -files -blocks -locations`

다음 중 하나라도 만족하면 작업을 중단한다.

- Tailscale peer가 direct 연결이 아님
- service host MemAvailable 4 GiB 미만
- service host disk available 50 GiB 미만
- HDFS missing/corrupt block 존재
- 기존 API, PostgreSQL, Kafka health 실패
- 신규 예정 포트 충돌

### Phase 1. 설정 구현과 정적 검증

- data/server 전용 Compose 파일 추가
- `.env.example`에 Tailscale·HDFS·Spark 변수 추가
- rack topology mapping script 추가
- Spark submit 공통 네트워크 설정 추가
- service 서버의 독립 cluster-worker 제어·health 명령 추가
- 두 신규 Compose와 기존 Compose의 회귀 검증 script 추가
- 양쪽 환경의 `docker compose config --quiet` 검증
- shell script 정적 검사와 기존 테스트 실행

기존 `deploy.sh`는 이 단계에서 새 overlay를 자동 적용하도록 바꾸지 않는다. Phase 2
복구점과 각 전환 gate를 건너뛴 일괄 재생성을 막기 위해서다. 운영 checkout과 Docker
metadata blocker가 해결된 뒤, Phase 3부터 대상 서비스별 명령을 명시적으로 실행한다.

Phase 1 결과와 검증 증거는
[Phase 1 구현·정적 검증 기록](2026-09-10-hdfs-spark-two-host-phase1-static-implementation.md)에
기록한다. 이 단계에서는 운영 컨테이너를 변경하지 않는다.

### Phase 2. HDFS 복구점 생성

Frontend, Backend, PostgreSQL, Redis와 Kafka는 유지한다. Collector와 분석
Worker를 일시 중지해 신규 HDFS write와 Spark job만 차단한다.

1. 실행 중 Spark job이 없는지 확인
2. HDFS open file 확인
3. 전체 HDFS fsck
4. NameNode safe mode 진입
5. `saveNamespace`
6. NameNode named volume metadata archive 생성 및 SHA-256 기록
7. archive와 검증 자료를 service 서버에 off-host 복사하고 checksum 대조
8. safe mode 해제

NameNode format, HDFS volume 삭제, cluster ID 재생성은 금지한다.

2026-09-10 최초 진입은 active WebHDFS bootstrap writer와 EBS snapshot 권한 부재로
중단했다. 최초 중단 내용은
[Phase 2 복구점 생성 차단 기록](2026-09-10-hdfs-spark-two-host-phase2-recovery-point-blocked.md)에
기록한다.

SSAFY 대여 서버는 AWS control plane 권한 없이 Linux 서버로만 운영한다는 제약을
확인해, 이번 변경의 rollback 범위에 맞춘 off-host NameNode metadata 복구점으로
대체했다. 완료 결과는
[Phase 2 Linux off-host 복구점](2026-09-10-hdfs-spark-two-host-phase2-linux-recovery-point.md)에
기록한다. 이 복구점은 Compose/network 전환 rollback용이며 data 서버 EBS 자체의
물리 장애를 복구하는 full block backup은 아니다.

### Phase 3. NameNode와 기존 DataNode의 Tailscale 전환

NameNode는 bridge network를 유지하고 다음 RPC 설정을 사용한다.

```text
fs.defaultFS=hdfs://DATA_TS_IP:8020
dfs.namenode.rpc-address=DATA_TS_IP:8020
dfs.namenode.rpc-bind-host=0.0.0.0
```

Host publish는 `DATA_TS_IP:8020`으로 제한한다.

DataNode 1/2/3은 host network로 전환한다. 동일 host 안에서 충돌하지 않도록
각자 다른 HTTP, data transfer, IPC port를 사용한다. Phase 3 전환 시점에는 HDFS
client가 IP 기반 연결을 유지했다.

```text
dfs.client.use.datanode.hostname=false
```

세 DataNode를 동시에 재생성하지 않는다. 각 DataNode마다 다음 gate를 통과한 뒤
다음 노드로 진행한다.

1. 대상 DataNode만 중지·재생성
2. 전환 전후 DataNode UUID 동일 확인
3. `dfsadmin -report`에서 Tailscale IP와 고유 port 확인
4. 대상 노드 보유 대표 파일 read
5. 전체 fsck에서 missing/corrupt block 0 확인

Compose hostname 또는 bridge 대역 주소가 NameNode report나 WebHDFS redirect에
남으면 작업을 중단하고 해당 DataNode만 이전 구성으로 복구한다.

Phase 4에서 원격 DataNode가 Docker published RPC를 통해 가입할 때 NameNode가
접속 원본을 bridge gateway로 보는 것이 확인됐다. NameNode를 host network로
이동하지 않고 Hadoop multihoming 설정인
`dfs.client.use.datanode.hostname=true`와
`dfs.datanode.use.datanode.hostname=true`를 전체 HDFS daemon 및 Spark submit
client에 적용했다. Phase 3의 Tailscale bind와 기존 UUID는 그대로 유지한다.

실제 운영 전환은 기존 UI publish 포트 충돌을 피하기 위해
`DataNode-3 -> DataNode-2 -> DataNode-1` 순서로 수행했다. 완료 결과와 bridge에서
같은 host의 Tailscale 주소로 접근하기 위한 제한 UFW 규칙은
[Phase 3 Data HDFS Tailscale 전환 기록](2026-09-10-hdfs-spark-two-host-phase3-data-hdfs-tailscale.md)에
기록한다.

### Phase 4. Service 서버 DataNode-4 가입

별도 `gitjob-cluster-worker` project에 DataNode-4와 독립 named volume을 생성한다.

```text
fs.defaultFS=hdfs://DATA_TS_IP:8020
dfs.datanode.address=SERVICE_TS_IP:9866
dfs.datanode.hostname=SERVICE_TS_IP
dfs.datanode.ipc.address=SERVICE_TS_IP:9867
dfs.datanode.http.address=SERVICE_TS_IP:9864
dfs.client.use.datanode.hostname=true
dfs.datanode.use.datanode.hostname=true
```

NameNode topology mapping은 data 서버를 `/rack-a`, service 서버를 `/rack-b`로
반환한다. Docker proxy가 원격 가입 주소를 bridge gateway로 변환할 때는
`dfsadmin -report`에서 관측한 주소를 `SERVICE_DN_REGISTRATION_IP`로 명시해
`/rack-b`로 매핑하고, 실제 block 연결은 DataNode가 광고한 Tailscale hostname을
사용한다. 가입 직후 balancer 또는 Raw 전체 replication 변경은 실행하지 않는다.

가입 gate는 다음과 같다.

- Live DataNode 4, Dead DataNode 0
- 네 DataNode UUID가 모두 다름
- `dfsadmin -printTopology`에 두 failure domain 표시
- service host의 기존 core/app 컨테이너 ID와 시작 시각 불변
- 기존 API, DB, Kafka health 정상

실제 가입 결과와 Docker project 격리 보정은
[Phase 4 Service DataNode-4 가입 기록](2026-09-10-hdfs-spark-two-host-phase4-service-datanode4.md)에
기록한다.

### Phase 5. HDFS 교차 host 복제 canary

운영 Raw 전체가 아니라 별도 검증 경로를 사용한다.

```text
/gitjob/demo/distributed-proof
```

또는 크기를 측정한 작은 실제 Parquet snapshot을 선택한다.

1. 검증 파일 생성
2. `hdfs dfs -setrep -w 2 <path>` 실행
3. `hdfs fsck <path> -files -blocks -locations -racks` 확인
4. 동일 block replica가 `/rack-a`, `/rack-b`에 각각 존재하는지 확인
5. 한쪽 DataNode 일시 중지 상태에서 read 확인
6. DataNode 복구 후 under-replicated block 0 확인

이 단계 완료 전에는 HDFS 물리 분산 완료로 판정하지 않는다.

실제 수행 결과는
[Phase 5 교차 host 복제 canary](2026-09-10-hdfs-spark-two-host-phase5-cross-host-replication.md)에
기록한다. canary 생성 직후 replication 1 block이 여유 공간이 가장 큰 DataNode-4에
전부 배치돼, `setrep 2` 이후에야 rack-a에 replica가 생겼다. 6번 gate는 결과적으로
under-replicated 0이지만, 죽은 DataNode의 replica가 제거되지 않고 `STALE`로 남아
재복제가 예약되지 않았으므로 자동 redundancy 회복은 증명되지 않았다.

### Phase 6. Spark Master와 Worker-1 Tailscale 전환

Spark Master와 data 서버 Worker-1은 host network를 사용한다.

```text
SPARK_MASTER_HOST=DATA_TS_IP
SPARK_MASTER_PORT=7077
SPARK_MASTER_WEBUI_PORT=8083

SPARK_WORKER_HOST=DATA_TS_IP
SPARK_WORKER_PORT=7078
SPARK_WORKER_WEBUI_PORT=8084
SPARK_MASTER_URL=spark://DATA_TS_IP:7077
```

기존 Compose DNS 이름인 `spark-master`, `spark-worker`를 외부 광고 주소로
사용하지 않는다. Worker-1 단독 smoke job과 기존 결과 checksum 비교를 먼저
통과해야 한다.

실제 수행 결과는
[Phase 6 Spark Master·Worker-1 전환](2026-09-10-hdfs-spark-two-host-phase6-spark-master-tailscale.md)에
기록한다. Parquet은 바이트 재현성이 없어 file checksum으로는 이 게이트를 판정할 수
없고, 내용 기반 digest로 기준선·전환 전·전환 후 세 결과의 동일성을 확인했다. 전환에는
Spark 데몬의 hostname 해석과 관리 UI wildcard bind 두 건의 수정이 필요했다.

### Phase 7. Service 서버 Spark Worker-2 가입

DataNode-4와 같은 별도 Compose project에 Worker-2를 추가한다.

```text
SPARK_WORKER_HOST=SERVICE_TS_IP
SPARK_WORKER_PORT=7078
SPARK_WORKER_WEBUI_PORT=8084
SPARK_WORKER_CORES=1
SPARK_WORKER_MEMORY=1G
SPARK_MASTER_URL=spark://DATA_TS_IP:7077
```

Spark Master UI에서 서로 다른 Tailscale IP의 Worker 두 개가 `ALIVE`인지
확인한다.

실제 수행 결과는
[Phase 7 Service Spark Worker-2 가입](2026-09-11-hdfs-spark-two-host-phase7-service-spark-worker2.md)에
기록한다. 등록 조건은 충족했으나 client mode driver가 자기 주소를 Compose hostname
`spark-worker`로 광고해 service 호스트 executor가 연결하지 못한다. Worker-2를 실제로
사용하려면 Phase 8이 선행돼야 하므로 판정은 `CONDITIONAL`이다.

### Phase 8. Spark driver와 BlockManager port 고정

모든 운영 `spark-submit` 경로에 공통 설정을 적용한다.

```text
spark.driver.bindAddress=DATA_TS_IP
spark.driver.host=DATA_TS_IP
spark.driver.port=40001
spark.driver.blockManager.port=40002
spark.blockManager.port=41000
spark.port.maxRetries=15
spark.executor.cores=1
spark.cores.max=2
```

초기에는 동시 job을 한 개로 제한한다. `spark.blockManager.port`와 retry 범위는
두 host의 Tailscale 경계에서 모두 허용돼야 한다.

실제 수행 결과는
[Phase 8 driver·BlockManager 포트 고정](2026-09-11-hdfs-spark-two-host-phase8-driver-port-pinning.md)에
기록한다. 양쪽 서버의 `ts-input` 체인이 UFW 체인보다 먼저 `tailscale0`를 ACCEPT하므로
이 단계에서 UFW 규칙 추가는 필요하지 않았고 public 허용 목록도 그대로다. 설정 직후
두 host executor가 모두 등록되고 각각 task를 수행했다.

### Phase 9. Spark 분산 처리 검증

검증을 세 단계로 확장한다.

1. HDFS를 사용하지 않는 synthetic shuffle canary
2. `/gitjob/demo/distributed-proof`를 읽는 HDFS canary
3. 1일치 GH Archive Repo Activity 실제 job

1일치 검증 후 1개월 입력으로 확대한다. 6개월 전체 입력은 서비스 자원과 소요
시간을 검토한 뒤 별도 승인으로 실행한다.

완료 조건은 다음과 같다.

- Spark Worker 2개 `ALIVE`
- 서로 다른 두 Tailscale IP에서 executor 실행
- 양쪽 executor가 각각 하나 이상의 task 수행
- shuffle read/write 관측
- executor failure/retry 없음
- 단일 Worker 기준 결과와 checksum 동일
- 실행 중 service API, DB, Kafka health 정상

실제 수행 결과는
[Phase 9 분산 처리 검증](2026-09-11-hdfs-spark-two-host-phase9-distributed-verification.md)에 기록한다. 세 단계 모두 통과했고 1일치 실제 job에서
task가 data 376 / service 285로 분산됐다. 같은 입력의 단일 Worker 결과와 내용
digest가 일치한다. 이 단계에서 Phase 5의 "재복제 미검증" 항목도 재시험해, 노드
상실 시 243개 블록이 120초 만에 자동 복구되는 것을 확인했다.

### Phase 10. 서비스 재개와 안정화 관측

Collector와 분석 Worker를 재개하고 최소 30분 동안 다음을 관측한다.

- public HTTP/HTTPS와 Backend health
- 분석 요청 접수와 완료
- Kafka consumer lag
- PostgreSQL, Redis, Kafka restart 여부
- HDFS Live/Dead DataNode와 fsck
- Spark Worker 상태
- service host CPU, memory, disk I/O와 OOM 여부
- Tailscale direct 연결 유지 여부

자원 경합이나 API 지연이 확인되면 Spark Worker-2를 먼저 중지한다. HDFS
DataNode-4는 저장 canary의 replication 상태를 확인한 뒤 별도로 판단한다.

실제 수행 결과는 [Phase 10 안정화 관측](2026-09-11-hdfs-spark-two-host-phase10-stabilization.md)에 기록한다. 31분 관측에서 이상치가
없어 Worker-2 중지 조건에 해당하지 않았다. Collector와 분석 Worker는 이번 작업에서
중지한 적이 없어 재개할 대상이 없었다. 분석 요청 접수·완료와 Kafka consumer lag은
실사용자 트래픽이 없어 관측 대상이 존재하지 않았다.

## 8. 배포 자동화 계획

배포 흐름을 다음 단위로 분리한다.

```text
deploy_service_core_app
deploy_data_cluster
deploy_service_cluster_worker
verify_distributed_cluster
```

`deploy_service_cluster_worker`는 `gitjob-service` Compose project를 호출하지
않는다. DataNode-4와 Worker-2만 대상으로 build/pull/config/up/healthcheck를
수행한다.

전체 순서는 다음으로 고정한다.

```text
preflight
-> service core/app 상태 확인
-> data HDFS 롤링 전환
-> DataNode-4 가입 및 저장 canary
-> Spark Master/Worker-1 전환
-> Spark Worker-2 가입 및 계산 canary
-> 실제 1일치 job
-> 전체 서비스 검증
```

어느 gate든 실패하면 다음 단계로 진행하지 않는다.

## 9. 롤백 계획

### 9.1 기존 DataNode 전환 실패

- 실패한 DataNode만 중지
- 기존 bridge override 복원
- 동일 named volume으로 재기동
- 동일 UUID 재등록 및 fsck 확인
- 다른 DataNode는 변경하지 않음

### 9.2 DataNode-4 실패

- DataNode-4만 중지
- 기존 DataNode 1/2/3 유지
- replication 2 canary가 DataNode-4를 사용했다면 `setrep -w 1` 완료 후 제거
- 신규 DataNode volume은 원인 확인 전 삭제하지 않음

### 9.3 Spark Worker-2 실패

- service 서버의 `gitjob-cluster-worker`에서 Worker-2만 중지
- 기존 core/app과 data 서버 Worker-1 유지

### 9.4 Spark Master 전환 실패

- 기존 bridge 설정과 Compose DNS 기반 Master URL 복원
- Worker-1 재등록
- 기존 단일 Worker smoke job 확인

### 9.5 전체 HDFS 복구

- 신규 write 중지
- Phase 2 off-host NameNode metadata archive와 기록한 cluster ID/UUID 기준으로 복구
- NameNode와 DataNode volume을 함께 검증

SSAFY 대여 서버에는 AWS control plane 권한이 없어 EBS snapshot은 존재하지 않는다.
Phase 2 archive는 NameNode metadata 복구점이며 DataNode block 전체나 data 서버의
물리 디스크 장애를 복구하는 full backup은 아니다.

어떤 롤백에서도 자동 volume 삭제나 NameNode format을 수행하지 않는다.

## 10. 완료 기준

- application public ingress는 `80`, `443`만 유지하고 기존 SSH `22` 외 관리
  포트를 추가하지 않음
- HDFS·Spark는 Tailscale peer에서만 접근 가능
- Tailscale peer 연결은 direct
- HDFS Live DataNode 4, Dead DataNode 0
- DataNode가 Tailscale IP와 고유 port를 광고
- 두 논리 failure domain 확인
- replication 2 canary block이 두 EC2에 각각 존재
- 한쪽 DataNode 중지 상태에서 canary read 성공
- HDFS missing/corrupt/under-replicated block 0
- Spark Worker 2개 `ALIVE`
- 실제 job에서 두 host의 executor가 task 수행
- shuffle 작업 성공 및 기준 checksum 동일
- 기존 core/app 컨테이너가 cluster worker 배포로 재시작되지 않음
- 서비스 API, PostgreSQL, Redis, Kafka 정상
- GH Archive Raw 114 GiB 전체 복제 또는 재배치 없음
- 구성 한계와 실제 host `df` 기준 용량을 운영 문서에 기록

## 11. 예상 일정

| 구간 | 예상 |
|---|---:|
| 사전점검·설정 구현 | 1일 |
| HDFS 롤링 전환·DataNode-4 canary | 1~1.5일 |
| Spark 2-host 전환·실제 job 검증 | 1일 |
| 안정화·문서·롤백 검증 | 0.5일 |
| 합계 | 3.5~4일 |

## 12. 이번 작업에서 하지 않는 것

- GH Archive Raw 114 GiB 전체 replication 2 적용
- HDFS balancer 실행
- 기존 DataNode 2/3 decommission
- NameNode HA 또는 Spark Master HA 구성
- Kafka broker 추가
- public Hadoop/Spark port 개방
- HDFS volume 재생성 또는 format
- 서비스 서버에서 무제한 Spark 자원 사용

호스트당 DataNode 1개로 정리하는 작업은 DataNode-4 안정화, service 서버 용량
검증과 필요한 block 이동 계획을 별도 수립한 뒤 진행한다.
