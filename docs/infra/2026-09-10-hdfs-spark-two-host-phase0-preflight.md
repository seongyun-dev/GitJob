# S15P21E102-207 Phase 0 Preflight Record

- Jira: `S15P21E102-207`
- 점검일: 2026-09-10
- 점검 시각: 07:50-08:00 UTC
- 점검 방식: SSH를 통한 read-only 명령
- 상태: 조건부 통과 — 운영 checkout 정리 필요
- 계획 문서: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)

## 1. 점검 범위

Phase 0에서는 운영 상태를 변경하지 않았다. 컨테이너 stop/restart, firewall 변경,
HDFS write, safe mode 전환, snapshot 생성은 수행하지 않았다.

다음을 읽기 전용으로 확인했다.

- 양쪽 EC2의 Tailscale 주소와 peer 경로
- CPU load, memory, root filesystem
- Docker Engine/Compose와 실행 컨테이너
- host listen port와 UFW 정책
- public endpoint에서 노출되는 포트
- HDFS cluster health, capacity, block 상태와 topology
- NameNode cluster ID와 DataNode UUID
- Spark Master와 Worker 상태, 실행 중 application 여부
- 운영 checkout 상태

비밀번호, token, credential, remote `.env` 값은 조회하거나 기록하지 않았다.

## 2. 서버와 Tailscale 기준선

| 항목 | J15E102 service | J15E102A data |
|---|---|---|
| host private address | `172.26.11.108` | `172.26.12.59` |
| Tailscale IPv4 | `100.71.215.74` | `100.70.66.38` |
| peer path | direct `172.26.12.59:41641` | direct `172.26.11.108:41641` |
| ping result | 0 ms | 1 ms |
| uptime | 10 days | 10 days |
| load average | `1.14 / 0.73 / 0.68` | `1.32 / 1.29 / 1.18` |
| Docker Engine | `29.7.2` | `29.7.2` |
| Docker Compose | `v5.5.0` | `v5.5.0` |

양방향 모두 DERP가 아닌 VPC private address를 통한 direct Tailscale 연결이다.

## 3. 자원 기준선

| 항목 | J15E102 service | J15E102A data |
|---|---:|---:|
| RAM total | 15 GiB | 15 GiB |
| RAM used | 5.9 GiB | 3.5 GiB |
| RAM available | 9.5 GiB | 11 GiB |
| swap | 0 | 0 |
| root filesystem | 309 GiB | 309 GiB |
| root used | 25 GiB | 237 GiB |
| root available | 285 GiB | 73 GiB |
| root usage | 8% | 77% |

Service 서버는 Phase 0 기준 `MemAvailable >= 4 GiB`, disk available `>= 50 GiB`,
disk free ratio `>= 25%`를 모두 충족한다. Data 서버는 약 73 GiB만 남아 있어 Raw
전체 replication 확대나 대량 임시 파일 생성은 금지한다.

Data 서버에서는 `docker system df`가 stale container snapshot 참조 오류로
실패했으므로 Docker 내부 용량 합계는 기록하지 않는다. Host `df`와 HDFS report는
정상적으로 조회됐다. 자세한 blocker는 8절에 기록한다.

## 4. 서비스 기준선

Service 서버의 핵심 컨테이너는 모두 `running/healthy`, restart count 0이었다.

| 서비스 | 상태 | restart count |
|---|---|---:|
| backend | healthy | 0 |
| frontend | healthy | 0 |
| nginx | healthy | 0 |
| postgres | healthy | 0 |
| redis | healthy | 0 |
| kafka | healthy | 0 |
| kafka-connect | healthy | 0 |

HTTP `/health`는 `UP`, HTTPS `/nginx-health`는 `ok`를 반환했다. Data 서버의
Collector와 analysis Worker도 모두 healthy, restart count 0이었다.

향후 각 Phase 검증에서는 이 컨테이너들의 ID와 `StartedAt`이 cluster-worker
배포로 변경되지 않았는지 비교한다. 전체 ID와 시각은 민감정보는 아니지만 문서
가독성을 위해 운영 명령 출력에만 보존하고 여기에는 상태 요약만 기록한다.

## 5. 네트워크와 public 노출 기준선

### 5.1 UFW

양쪽 서버 모두 기본 정책은 incoming deny, outgoing allow, routed deny다.

- Service 서버: SSH `22`, public HTTP `80`, HTTPS `443` 허용
- Data 서버: SSH `22`만 허용

현재 HDFS/Spark 관리 UI는 Docker가 data 서버 Tailscale IP에 bind한 상태다.
Service 서버에는 Grafana, Prometheus, Node Exporter, Jenkins, Kafka UI와
RedisInsight가 Tailscale IP에 bind되어 있다.

### 5.2 외부 endpoint probe

프로젝트 작업 환경에서 두 public FQDN의 TCP 포트를 검사했다.

- Service 서버: `80`, `443` 연결 성공
- Service 서버 Hadoop/Spark 예정 포트: 연결 실패
- Data 서버 `80`, `443` 및 Hadoop/Spark 포트: 모두 연결 실패

검사한 Hadoop/Spark 포트는 `7077`, `7078`, `8020`, `8083`, `8084`, `9864`,
`9866`, `9867`, `9870`이다. Phase 이후에도 동일 probe를 반복한다.

## 6. HDFS 기준선

### 6.1 Cluster identity

| 항목 | 값 |
|---|---|
| cluster ID | `CID-47d1b1a7-56b7-480f-861c-0a3b9459a867` |
| namespace ID | `1025136227` |
| DataNode-1 UUID | `b1ce2dcf-e408-48e0-aa8c-31599b8a3d07` |
| DataNode-2 UUID | `dc3991a5-3b4d-4d76-831c-3be8b3353f02` |
| DataNode-3 UUID | `32f7bc8d-a77f-48fd-b5e4-04fb3cafb37c` |

기존 volume mapping은 다음과 같다.

| 서비스 | named volume | mount |
|---|---|---|
| NameNode | `gitjob-data_hdfs-namenode-data` | `/data` |
| DataNode-1 | `gitjob-data_hdfs-datanode-data` | `/data` |
| DataNode-2 | `gitjob-data_hdfs-datanode2-data` | `/data` |
| DataNode-3 | `gitjob-data_hdfs-datanode3-data` | `/data` |

모든 HDFS 컨테이너는 healthy, restart count 0이다.

### 6.2 Capacity and integrity

| 항목 | 결과 |
|---|---:|
| Live DataNode | 3 |
| Dead DataNode | 0 |
| logical configured capacity | 926.79 GB |
| HDFS DFS used | 119.80 GB |
| HDFS DFS remaining | 216.70 GB |
| total files | 15,792 |
| total blocks | 15,790 |
| default replication | 1 |
| average replication | 1.0293857 |
| under-replicated blocks | 0 |
| missing blocks | 0 |
| corrupt blocks | 0 |
| missing replicas | 0 |
| filesystem status | HEALTHY |
| safe mode | OFF |

`hdfs fsck /gitjob -openforwrite`도 HEALTHY였으며 별도의 open-for-write 문제는
출력되지 않았다.

현재 세 DataNode는 모두 `/default-rack`이며 NameNode에는 bridge IP와 Compose
hostname으로 등록되어 있다.

```text
172.18.0.6:9866  hdfs-datanode
172.18.0.9:9866  hdfs-datanode2
172.18.0.7:9866  hdfs-datanode3
```

이는 Phase 3에서 Tailscale address와 고유 port로 전환해야 할 기준 상태다.

## 7. Spark 기준선

| 항목 | 값 |
|---|---|
| Master URL | `spark://spark-master:7077` |
| Master status | ALIVE |
| alive Workers | 1 |
| Worker address | `172.18.0.5:41307` |
| Worker cores | 2 |
| Worker memory | 2 GiB |
| active applications | 0 |
| active drivers | 0 |

Spark Worker RPC port는 현재 random `41307`이고 Master/Worker 모두 bridge address를
광고한다. Phase 6 이후 Tailscale IP와 고정 port로 바뀌어야 한다.

## 8. 운영 checkout blocker

Phase 0에서 운영 적용 전에 해결해야 할 blocker 두 개를 발견했다.

### Service 서버

- branch: `develop`
- HEAD: `5bbc12907c4d7e966703ec9aa238922e73c3dab4`
- remote `origin/develop`보다 22 commits behind
- tracked working tree: clean

### Data 서버

- branch: `develop`
- HEAD: `5bbc12907c4d7e966703ec9aa238922e73c3dab4`
- remote `origin/develop`보다 17 commits behind
- tracked changes: 80 entries
- 신규·수정 파일이 index에 남아 있어 checkout이 clean하지 않음

현재 `Infra/scripts/deploy.sh`는 remote checkout이 dirty하면 배포를 중단한다.
따라서 Data 서버의 변경 소유자와 보존 여부를 확인하기 전에는 자동 배포나 branch
전환을 수행하지 않는다. Phase 1의 로컬 구현과 정적 검증은 진행할 수 있지만,
운영 적용은 다음 조건이 충족될 때까지 차단한다.

1. Data 서버 staged 변경의 소유자와 목적 확인
2. 필요하면 commit, patch 또는 별도 백업으로 보존
3. 운영 checkout `git status --porcelain`이 빈 상태인지 확인
4. 양쪽 서버가 배포 대상 commit을 안전하게 fast-forward할 수 있는지 확인

이 문서 작성 과정에서 해당 변경을 restore, reset, stash 또는 commit하지 않았다.

### Data 서버 Docker metadata

Data 서버의 `docker system df`가 다음 오류로 실패했다.

```text
failed to retrieve container list: rw layer snapshot not found for container
e1161f7ce380...
```

해당 container ID는 현재 `docker ps -a`와 `docker inspect`에는 존재하지 않는다.
Docker journal에는 같은 시각 task delete event와 `/system/df` 500 응답이 기록됐다.
실행 중인 HDFS, Spark, Collector, Worker 컨테이너는 계속 healthy이며 restart count
0이었다.

이는 현재 데이터 무결성 장애를 의미하지는 않지만 Docker metadata 또는
containerd snapshot 상태가 완전히 정상이라고 판정할 수 없다는 뜻이다. 운영
컨테이너 restart나 신규 image build 전에 다음을 별도 진단한다.

1. 동시 작업자가 container를 생성·삭제 중인지 확인
2. `docker events`와 Docker journal의 발생 시각 대조
3. 반복 `docker system df`에서 오류가 재현되는지 확인
4. Docker daemon restart가 필요하다면 HDFS 복구점 생성 후 유지보수 구간에서 수행

원인 확인 전 `docker system prune`, containerd metadata 직접 삭제, Docker daemon
restart를 수행하지 않는다.

## 9. Phase 0 판정

| Gate | 결과 |
|---|---|
| Tailscale direct | PASS |
| Service MemAvailable >= 4 GiB | PASS |
| Service disk available >= 50 GiB | PASS |
| 신규 예정 포트 미사용 | PASS |
| HDFS missing/corrupt block 0 | PASS |
| 실행 중 Spark application 없음 | PASS |
| 기존 core/app health | PASS |
| Public Hadoop/Spark 포트 차단 | PASS |
| 운영 checkout clean | **BLOCKED: data 서버 dirty** |
| Data 서버 Docker metadata | **BLOCKED: `docker system df` snapshot 오류** |

Phase 0은 인프라·데이터 상태 기준으로 통과했으나 운영 배포 준비는 조건부다.
다음 Phase에서는 저장소 안의 Compose, script, test 구현과 정적 검증까지만 수행할
수 있다. 운영 서버 변경은 checkout과 Docker metadata blocker가 해결되고 HDFS
복구점이 생성된 후에만 수행한다.

## 10. Phase 1 진입 시 유지할 기준값

- `DATA_TS_IP=100.70.66.38`
- `SERVICE_TS_IP=100.71.215.74`
- NameNode cluster ID와 DataNode 1/2/3 UUID 불변
- HDFS missing/corrupt block 0
- Service 핵심 컨테이너 restart count 0
- Public Hadoop/Spark endpoint 연결 실패
- Raw 전체 replication 변경 금지
- 운영 checkout과 Docker metadata blocker 해결 전 remote mutation 금지
