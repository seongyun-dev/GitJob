# S15P21E102-207 Phase 4 Service DataNode-4 가입

- 수행일: 2026-09-10
- 수행 시각: 14:25-14:50 UTC
- 대상: `J15E102` service 서버, `J15E102A` NameNode
- 상태: `PASS` — 독립 project/volume의 DataNode-4 가입 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 3 Data HDFS Tailscale 전환](2026-09-10-hdfs-spark-two-host-phase3-data-hdfs-tailscale.md)

## 1. 범위와 작업 전 게이트

이번 단계는 service 서버에 DataNode-4만 추가했다. Spark Worker-2는 시작하지
않았고 balancer, 수동 `setrep`, Raw 전체 복제도 실행하지 않았다. data 서버의
Collector와 Worker만 NameNode 재생성 동안 잠시 중지했으며 service 서버의
Frontend, Backend, Nginx, PostgreSQL, Redis, Kafka와 monitoring은 중지하거나
재생성하지 않았다.

| 항목 | 작업 전 결과 |
|---|---|
| HDFS fsck | HEALTHY |
| missing/corrupt block | 0 / 0 |
| 기존 DataNode | Live 3, 기존 UUID 유지 |
| service root 여유 공간 | 약 282 GiB |
| service MemAvailable | 약 10 GiB |
| DN4 host port | `9864`, `9866`, `9867` 사용 가능 |
| DN4 named volume | 없음 — 신규 생성 대상 |
| 기존 service stack | 모두 실행, 주요 서비스 healthy |

Phase 4 전후 증거는 양쪽 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase4-20260910T142500Z
```

data 서버의 `.env.data`에는 실제 NameNode report에서 확인한
`SERVICE_DN_REGISTRATION_IP=172.18.0.1`만 추가했다. Phase 3의 변경 전 env 사본은
계속 보존하고, Phase 4 적용 후 사본은 권한 `0600`으로 저장했다.

## 2. 첫 기동에서 발견한 Compose project 충돌

service 서버의 `.env.service`에는 기존 stack용
`COMPOSE_PROJECT_NAME=gitjob-service`가 있다. Compose 파일의 최상위 `name`보다 이
값이 우선되어 첫 DN4 기동이 `gitjob-service` project 이름을 사용했다.

기존 core/app 컨테이너는 재생성되지 않았고 ID도 바뀌지 않았다. 잘못 생성된 DN4
컨테이너만 내린 뒤, `cluster-worker.sh`가 항상 별도의 project 이름을 명시하도록
보정했다. 잘못된 project label을 가진 신규 volume은 HDFS block 0개를 확인한 뒤
삭제하고 올바른 project에서 새로 생성했다.

옵션 없이 worker 제어 스크립트를 실행해도 Phase 7의 Spark Worker-2가 함께 가입하지
않도록 기본 profile도 `hdfs-worker` 하나로 제한했다. Spark 가입에는 이후
`CLUSTER_WORKER_PROFILES=spark-worker`를 명시해야 한다.

```text
894ec22 [S15P21E102-207] fix: 클러스터 워커 프로젝트 격리 강제
```

최종 DN4의 Compose project와 volume은 다음과 같다.

```text
project=gitjob-cluster-worker
volume=gitjob-cluster-worker-hdfs-datanode4-data
network_mode=host
```

## 3. Docker proxy의 원격 가입 주소 보정

DN4는 service Tailscale IP에 정확히 바인딩하고 NameNode RPC에도 연결했지만,
bridge 안의 NameNode는 published `8020` 포트를 통과한 원격 접속 원본을 Docker
gateway인 `172.18.0.1`로 관측했다. 첫 등록 결과가 `/default-rack`이어서 즉시 DN4를
중지했고, 새 volume의 HDFS block이 0개임을 확인한 뒤 해당 volume만 제거했다.

NameNode를 host network로 옮기는 대신 Hadoop의 hostname 기반 DataNode 연결을
활성화했다.

```text
dfs.client.use.datanode.hostname=true
dfs.datanode.use.datanode.hostname=true
dfs.datanode.hostname=100.71.215.74
```

> 2026-09-11 정정: 이 hostname 설정은 NameNode에만 반영됐다. 이 단계에서 기존
> DataNode 1/2/3을 재생성하지 않아 세 노드는 Phase 3 설정(`false`)으로 계속
> 실행됐고, 그 결과 rack-a → rack-b 방향의 DataNode 간 재복제가 전부 실패했다.
> 원인과 수정은 [DataNode 간 재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md)에 기록한다.

topology script는 NameNode가 관측한 `172.18.0.1`도 service 서버의 `/rack-b`로
매핑한다. `172.18.0.1`을 고정 가정하지 않고 배포 시 확인한
`SERVICE_DN_REGISTRATION_IP` 값으로 주입한다.

Spark job도 새 DN4의 block location을 실제 Tailscale hostname으로 연결하도록 모든
공용 submit wrapper에 다음 설정을 추가했다.

```text
spark.hadoop.dfs.client.use.datanode.hostname=true
```

관련 기능 커밋은 다음과 같다.

```text
4a4c995 [S15P21E102-207] fix: 원격 데이터노드 주소 광고 보정
05fcffb [S15P21E102-207] fix: Spark HDFS 원격 데이터노드 조회 보정
96560bf [S15P21E102-207] fix: 데이터노드 전용 기본 프로필 적용
```

## 4. 최종 가입 결과

NameNode를 새 설정으로 한 번만 재생성한 뒤 기존 3개 DataNode가 먼저 정상 복귀한
것을 확인하고 DN4를 가입시켰다. NameNode report의 `Name`은 Docker gateway지만
`Hostname`은 실제 service Tailscale IP다. HDFS client와 WebHDFS redirect는
hostname을 사용한다.

| 노드 | UUID | report 주소/hostname | rack | 결과 |
|---|---|---|---|---|
| DataNode-1 | `b1ce2dcf-e408-48e0-aa8c-31599b8a3d07` | `100.70.66.38:9866` | `/rack-a` | 기존 UUID 유지 |
| DataNode-2 | `dc3991a5-3b4d-4d76-831c-3be8b3353f02` | `100.70.66.38:9876` | `/rack-a` | 기존 UUID 유지 |
| DataNode-3 | `32f7bc8d-a77f-48fd-b5e4-04fb3cafb37c` | `100.70.66.38:9886` | `/rack-a` | 기존 UUID 유지 |
| DataNode-4 | `905d00e8-97ad-4314-972b-42f8b9e08e6e` | `172.18.0.1:9866` / `100.71.215.74` | `/rack-b` | 신규 UUID |

DN4 listener는 wildcard나 private/public EC2 주소가 아니라 다음 Tailscale 주소에만
바인딩됐다.

```text
100.71.215.74:9864
100.71.215.74:9866
100.71.215.74:9867
```

data 서버의 NameNode bridge에서 세 포트로 직접 연결되는 것을 확인했다. 기존 파일의
WebHDFS `OPEN` redirect도 `http://100.70.66.38:9864/...`를 반환해 bridge 주소가
클라이언트 경로로 노출되지 않았다.

## 5. 최종 검증

| 검증 | 결과 |
|---|---|
| Live/Dead DataNode | 4 / 0 |
| 네 UUID 유지·중복 없음 | PASS |
| topology | `/rack-a` 3대, `/rack-b` 1대 |
| HDFS default replication | 1 유지 |
| missing/corrupt/under-replicated block | 0 / 0 / 0 |
| 전체 fsck | HEALTHY |
| DN4 block 수 | 최종 가입 gate 시점 0 |
| DN4 restart count | 0 |
| DN4 project/volume label | `gitjob-cluster-worker` 일치 |
| WebHDFS Tailscale redirect | PASS |
| Collector/Worker 재개 | 모두 healthy |
| service API `/health` | `UP` |
| service core/app container ID | 작업 전과 동일 |
| service root 여유 공간 | 약 282 GiB |

NameNode 재시작 직후 기존 DataNode block report가 다시 들어오는 동안
under-replicated block이 일시적으로 72에서 10으로 내려간 뒤 0으로 수렴했다. 데이터
누락이나 손상은 발생하지 않았다.

기존 Parquet block 240개는 두 번째 rack이 생기면서 rack placement 위반으로
표시된다. replica 수는 충족돼 under-replicated는 0이고 fsck도 HEALTHY다.
이번 단계에서는 데이터 배치를 바꾸지 않았다.

> 2026-09-10 Phase 5 정정: 위 240개는 `replication=2`가 아니라 `replication=3`으로
> 설정된 파일들이다. replica 3개가 모두 data 서버에 있어 rack 정책만 위반 상태다.
> 주요 경로는 `/gitjob/parquet/github/repo_activity_weekly/period=2026-08/`과
> `/gitjob/parquet/smoke/gitjob-smoke-v1/`이다. 재배치는
> [Phase 5 기록](2026-09-10-hdfs-spark-two-host-phase5-cross-host-replication.md)에서도
> 범위 밖으로 두었다.

service UFW의 일반/public 허용 규칙은 기존 SSH 22, HTTP 80, HTTPS 443뿐이다. HDFS
세 포트는 Tailscale 주소에만 bind했으며 public UFW 규칙을 추가하지 않았다.

## 6. 기존 서비스 영향

service 서버의 주요 컨테이너 ID는 작업 전후 동일하다.

```text
backend       778aaa11a02b
frontend      40fdaebcfd3c
nginx         7202b48ae4cf
postgres      778dec7adf6c
redis         044ba1a8c3f
kafka         d930ab8240c7
kafka-connect f1fecb8a6bfc
```

Backend, Frontend, Nginx, PostgreSQL, Redis, Kafka의 상태는 계속 healthy였고 API
boundary도 `UP`을 반환했다. 새 worker project에는 DataNode-4만 실행 중이며
Spark Worker-2는 Phase 7 전까지 시작하지 않는다.

## 7. 롤백

가입 gate 시점 DN4 block은 0이었지만 Collector와 Worker를 정상 재개했으므로 이후
replication 1 신규 block의 유일한 replica가 DN4에 저장될 수 있다. 따라서 앞으로의
rollback은 DN4를 바로 중지하면 안 된다.

1. HDFS writer와 Spark job 중지
2. DN4의 현재 block 수와 `fsck -files -blocks -locations -racks` 확인
3. DN4에만 있는 block이 있으면 다른 DataNode로 안전하게 복제·이동한 뒤 0 확인
4. `CLUSTER_WORKER_PROFILES=hdfs-worker`로 별도 project만 중지
5. NameNode report가 Live 3, missing/corrupt/under-replicated 0인지 확인
6. hostname client 설정과 topology mapping은 기존 3개 노드에 무해하므로 별도
   원복이 필요한 경우에만 NameNode를 이전 설정으로 재생성

`down --volumes`, Docker volume prune, NameNode format은 실행하지 않는다. DN4 volume은
rollback 후에도 증거 및 복구를 위해 보존한다.

## 8. 남은 한계와 다음 Phase

NameNode의 configured capacity 약 1.21 TiB는 논리 DataNode 합계다. data 서버의
DataNode 3개가 같은 물리 filesystem을 사용하므로 실제 물리 용량과 같지 않다는 기존
한계는 남아 있다. 이번 단계에서 개선된 것은 두 번째 물리 서버와 두 번째 rack에
독립 volume이 추가됐다는 점이다.

Phase 4는 `PASS`다. Phase 5에서는 작은 별도 경로만 replication 2로 설정해 같은
block이 `/rack-a`와 `/rack-b`에 각각 존재하고 양쪽에서 읽히는지 검증한다.
