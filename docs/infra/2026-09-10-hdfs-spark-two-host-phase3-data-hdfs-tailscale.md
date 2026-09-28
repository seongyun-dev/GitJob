# S15P21E102-207 Phase 3 Data HDFS Tailscale 전환

- 수행일: 2026-09-10
- 수행 시각: 13:38-14:03 UTC
- 대상: `J15E102A` data 서버
- 상태: `PASS` — NameNode와 기존 DataNode 3개 Tailscale 전환 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 복구점: [Phase 2 Linux off-host 복구점](2026-09-10-hdfs-spark-two-host-phase2-linux-recovery-point.md)

## 1. 작업 전 게이트

작업 직전 양쪽 Tailscale peer는 EC2 private 경로를 사용한 `direct` 연결이었고
latency는 0-1 ms였다. data 서버는 약 171 GiB, service 서버는 약 284 GiB의 root
filesystem 여유 공간이 있었으며 양쪽 모두 `MemAvailable` 10 GiB 이상이었다.

| 항목 | 결과 |
|---|---|
| NameNode safe mode | OFF |
| HDFS open file | 0 |
| HDFS fsck | HEALTHY |
| missing/corrupt block | 0 / 0 |
| under/mis-replicated block | 0 / 0 |
| Live DataNode | 3 |
| service Backend health | UP |
| Tailscale peer | direct |

Collector와 분석 Worker를 정상 중지한 뒤 동일 gate를 다시 통과했다. 중단돼 있던
10,000 repository bootstrap은 재개하지 않았다. 각 DataNode가 보유한 대표 파일과
SHA-256을 전환 전에 기록해 전환 후 실제 block read 검증에 사용했다.

## 2. 운영 checkout 정리

data 서버의 기존 `develop` checkout에 보이던 staged 파일은 수동 수정이 아니었다.
index/worktree 전체가 원격
`data/S15P21E102-193-gharchive-six-month-repo-activity`의 `f409ccb` tree와 정확히
일치했다. 이 상태는 원격 커밋과 server stash에 이중 보존했다.

```text
stash: phase3-preserve-f409ccb-tree-20260910
stash: phase3-preserve-failed-tracking-switch-20260910
```

서버의 `remote.origin.fetch`에는 삭제된 과거 infra branch가 남아 일반 fetch가
실패했다. 저장소 전역 설정을 변경하지 않고 이번 작업 branch ref만 명시적으로
fetch해 `infra/S15P21E102-207-infra-hdfs-spark-2-split`을 clean checkout했다.

Phase 3에서 사용한 최종 server commit은 `ddebe4a`다.

## 3. NameNode 전환과 healthcheck 보정

`.env.data`의 기존 사본을 다음 위치에 보존하고 실제 Tailscale IP 두 개만 추가했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase3-20260910T134200Z/env.data.before
```

NameNode는 기존 `gitjob-data_hdfs-namenode-data` volume과 cluster ID를 유지한 채
재생성했다.

```text
fs.defaultFS=hdfs://100.70.66.38:8020
dfs.namenode.rpc-address=100.70.66.38:8020
dfs.namenode.rpc-bind-host=0.0.0.0
cluster ID=CID-47d1b1a7-56b7-480f-861c-0a3b9459a867
```

NameNode bridge 컨테이너에서 host에 publish한 자기 Tailscale 주소로 되돌아가는
hairpin RPC는 timeout됐다. 실제 외부 RPC와 DataNode registration은 정상이었지만
기존 healthcheck가 이 경로를 사용해 `starting`에 머물렀다. daemon 내부 확인은
`hdfs://127.0.0.1:8020`을 사용하도록 Compose healthcheck를 수정했다.

이 수정은 다음 기능 단위 커밋으로 반영하고 push했다.

```text
ddebe4a [S15P21E102-207] fix: NameNode Tailscale 헬스체크 수정
```

수정 후 NameNode는 `healthy`, Live DataNode는 3, cluster ID와 volume은 불변이었다.

## 4. Docker bridge의 로컬 HDFS 접근 경계

UFW는 기본 incoming deny이고 public 허용 규칙은 SSH 22뿐이었다. 이 정책이 data
서버의 Docker bridge에서 같은 서버 Tailscale IP로 향하는 HDFS 연결도 막고 있어,
host-network DataNode의 block read와 Collector의 WebHDFS redirect가 timeout됐다.

외부 interface를 열지 않고 다음 한정 규칙만 추가했다.

```text
interface: br-436a3ab5722f (gitjob-data_default)
source: 172.18.0.0/16
destination: 100.70.66.38
protocol: TCP
ports: 8020,9864,9866,9867,9870,9874,9876,9877,9884,9886,9887
comment: gitjob HDFS local bridge
```

규칙 적용 후 bridge 컨테이너에서 NameNode RPC와 DataNode HTTP 접근, WebHDFS 307
redirect를 따른 실제 파일 read가 모두 성공했다. UFW의 일반/public 허용 항목에는
기존 22 외 포트를 추가하지 않았다.

## 5. DataNode 롤링 전환

기존 DataNode-2/3 UI publish 포트 `9866`, `9867`이 새 DataNode-1의 data/IPC 포트와
겹쳤다. 세 노드를 동시에 내리지 않고 충돌을 먼저 해소하도록 전환 순서를
`DataNode-3 -> DataNode-2 -> DataNode-1`로 변경했다.

각 노드는 단독으로 재생성하고 UUID, named volume, host network, 광고 주소, 대표
파일 checksum과 전체 fsck를 확인한 뒤 다음 노드로 진행했다.

| 노드 | UUID | named volume | 광고 주소 | 대표 파일 SHA-256 | 결과 |
|---|---|---|---|---|---|
| DataNode-1 | `b1ce2dcf-e408-48e0-aa8c-31599b8a3d07` | `gitjob-data_hdfs-datanode-data` | `100.70.66.38:9866` | `d9ab2d9d...e07f80d3` | PASS |
| DataNode-2 | `dc3991a5-3b4d-4d76-831c-3be8b3353f02` | `gitjob-data_hdfs-datanode2-data` | `100.70.66.38:9876` | `a98b908d...ae7ee77b` | PASS |
| DataNode-3 | `32f7bc8d-a77f-48fd-b5e4-04fb3cafb37c` | `gitjob-data_hdfs-datanode3-data` | `100.70.66.38:9886` | `2e5edf2b...e3df5304` | PASS |

각 단계에서 Live DataNode 3을 유지했고 rollback이나 volume 교체는 실행하지 않았다.

## 6. 최종 검증

`dfsadmin -report`에는 다음 주소만 남았다.

```text
100.70.66.38:9866
100.70.66.38:9876
100.70.66.38:9886
```

NameNode report와 WebHDFS redirect에 `172.18.x.x` 주소는 남지 않았다.
`dfsadmin -printTopology`에서 세 노드가 모두 `/rack-a`의 In Service 상태로
확인됐다. `/rack-b`는 Phase 4의 service DataNode-4 가입 후 생성된다.

| 검증 | 결과 |
|---|---|
| Live/Dead DataNode | 3 / 0 |
| 세 UUID 유지·중복 없음 | PASS |
| HDFS fsck | HEALTHY |
| missing/corrupt/under-replicated block | 0 / 0 / 0 |
| 대표 파일 3개 checksum | 모두 전환 전과 일치 |
| WebHDFS redirect 실제 read | PASS |
| service 서버에서 11개 HDFS Tailscale port 연결 | PASS |
| HDFS listener wildcard/public bind | 없음 |
| Collector/Worker 재개 | 모두 healthy |
| service Backend | UP |
| service core/app container ID | 불변 |
| server Git status | clean |

Compose 실행 중 monitoring overlay를 함께 지정하지 않아 `node-exporter`가 orphan
경고로 표시됐지만 `--remove-orphans`를 사용하지 않았고 해당 컨테이너는 계속
실행 중이다.

Writer 중지 시점에 실행 중이던 Saramin 회차에는 닫힌 `.uploading-*` 임시 파일
2개가 남았다. 최종 open file은 0이고 fsck는 HEALTHY이며, 정상 완료된 이전 회차나
기존 block에는 영향이 없다. 운영 데이터 삭제 권한을 임의로 확대하지 않기 위해
이번 Phase에서는 삭제하지 않았다. 수집기의 stale upload 정리 정책과 해당 회차의
재실행 여부를 확인한 뒤 별도 정리한다.

## 7. 기존 서비스 영향

Frontend, Backend, Nginx, PostgreSQL, Redis, Kafka와 monitoring 컨테이너는
재생성하거나 중지하지 않았다. service 서버의 주요 container ID가 작업 전후
동일했고 Backend health는 계속 `UP`이었다. data 서버의 Collector/Worker만 HDFS
writer 차단을 위해 일시 중지한 뒤 기존 컨테이너 그대로 재개했다.

## 8. 롤백

단순 주소·network 문제의 정상 rollback은 Phase 2 metadata archive 복원보다 기존
Compose 설정 복귀를 우선한다.

1. Collector와 Worker 및 추가 HDFS writer 중지
2. `compose.ec2-data.yaml`을 사용해 DataNode-1, 2, 3을 한 개씩 기존 bridge 구성으로
   복구
3. 각 노드 UUID와 named volume 불변, 대표 파일 read와 fsck 확인
4. NameNode를 기존 bridge RPC 설정으로 복구
5. `.env.data`는 보존한 `env.data.before`와 차이를 검토해 필요한 두 주소만 제거
6. 더 이상 local Tailscale HDFS 경로를 사용하지 않을 때만 UFW의
   `gitjob HDFS local bridge` 규칙 제거

`down --volumes`, Docker volume prune, NameNode format은 어떤 rollback에서도
사용하지 않는다.

## 9. 다음 Phase 판정

Phase 3은 `PASS`다. Phase 4에서 service 서버에 독립 named volume을 사용하는
DataNode-4만 가입한다. 가입 직후 balancer나 Raw 전체 replication 변경은 수행하지
않는다.
