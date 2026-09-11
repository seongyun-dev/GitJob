# S15P21E102-207 Phase 5 HDFS 교차 host 복제 canary

- 수행일: 2026-09-10
- 수행 시각: 15:25-15:45 UTC
- 대상: `J15E102A` NameNode·DataNode 1/2/3, `J15E102` DataNode-4
- 상태: `PASS` — 별도 canary 경로의 교차 host 복제와 단일 노드 중지 read 검증 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 4 Service DataNode-4 가입](2026-09-10-hdfs-spark-two-host-phase4-service-datanode4.md)

## 1. 범위와 작업 전 게이트

이번 단계는 `/gitjob/demo/distributed-proof` 한 경로만 replication 2로 만들었다.
운영 Raw 전체 복제, balancer, 기존 데이터 배치 변경, 기존 파일의 replication 변경은
수행하지 않았다. Spark Worker-2도 시작하지 않았다. 양쪽 서버의 Collector, Worker,
Frontend, Backend, Nginx, PostgreSQL, Redis, Kafka는 중지하거나 재생성하지 않았다.

| 항목 | 작업 전 결과 |
|---|---|
| Tailscale peer | `direct`, `via 172.26.11.108:41641`, 0s |
| Live / Dead DataNode | 4 / 0 |
| topology | `/rack-a` 3대, `/rack-b` 1대, 모두 In Service |
| DN4 last contact | 21초 전, healthy, project `gitjob-cluster-worker` |
| safe mode | OFF |
| fsck `/gitjob` | HEALTHY |
| missing / corrupt / under-replicated block | 0 / 0 / 0 |
| mis-replicated block | 240 (1.107%) |
| 전체 block / 크기 | 21,675 / 123 GB |
| data 서버 여유 | 172 GiB (45% 사용), MemAvailable 11 GiB |
| service 서버 여유 | 282 GiB (9% 사용), MemAvailable 10 GiB |

증거는 data 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase5-20260910T152505Z
```

## 2. Canary 생성과 초기 배치 관측

원본을 변경하지 않기 위해 기존 Parquet 3개를 HDFS 안에서 새 경로로 복사했다.

```text
원본: /gitjob/parquet/github/repo_activity_weekly/period=2026-08/
        snapshot=s15p21e102-109-weekly-20260908/part-0019{6,7,8}-...snappy.parquet
canary: /gitjob/demo/distributed-proof/  (3 files, 3.7 MB, 3 blocks)
```

기본 replication 1로 생성된 직후 **3개 block이 모두 `/rack-b`의 DataNode-4에
배치됐다.**

```text
blk_1073763521  Live_repl=1  [/rack-b/172.18.0.1:9866]
blk_1073763522  Live_repl=1  [/rack-b/172.18.0.1:9866]
blk_1073763523  Live_repl=1  [/rack-b/172.18.0.1:9866]
```

DataNode-4의 여유 공간이 281 GiB로 rack-a 노드의 171 GiB보다 크기 때문이다. 이는
Phase 5의 결과가 아니라 Phase 4 가입 이후의 상시 동작이며 11절에 위험으로 기록한다.

이 시점에 canary를 읽어 SHA-256을 기록했다. 당시 replica가 DataNode-4에만 있었으므로
이 read는 전부 Tailscale 경유 원격 replica에서 제공된 것이다. 즉 원격 replica의
읽기 가능성은 setrep 이전에 이미 증명됐다.

## 3. setrep 교차 host 복제

```text
hdfs dfs -setrep -w 2 /gitjob/demo/distributed-proof
```

세 파일 모두 `done`으로 완료됐고 배치는 다음과 같다.

| block | rack-b replica | rack-a replica |
|---|---|---|
| `blk_1073763521` | `172.18.0.1:9866` | `100.70.66.38:9866` |
| `blk_1073763522` | `172.18.0.1:9866` | `100.70.66.38:9876` |
| `blk_1073763523` | `172.18.0.1:9866` | `100.70.66.38:9886` |

세 block 모두 `Live_repl=2`이며 rack-a 쪽 replica가 서로 다른 DataNode에 분산됐다.
canary 경로의 under-replicated와 mis-replicated는 각각 0, average block replication은
2.0, fsck는 HEALTHY다.

## 4. 무결성 검증과 측정 함정

canary와 원본의 HDFS block checksum이 세 파일 모두 일치한다.

```text
part-00196 MATCH 000002000000000000000000ad8989165ff0947e93d7114b16627150
part-00197 MATCH 0000020000000000000000001625fe3b56dc7f717c9cf740a7491a81
part-00198 MATCH 000002000000000000000000d6e3f93797dc305e6700990a5dd0c55e
```

검증 도중 측정 방법 자체의 결함을 발견해 기록한다. `docker exec`의 stdout으로
바이너리를 빼내면 개행이 변환되어 데이터가 오염된다. 1,308,038 바이트 파일이
1,312,965 바이트로 읽혔고 초과분 4,927 바이트는 전체의 0.38%로 0x0A 바이트 빈도와
일치했다. 이 경로로 계산한 SHA-256은 실제와 다르며, 최초 측정에서 checksum 불일치로
오판할 수 있었다.

따라서 바이트 무결성은 다음 두 방법만 사용한다.

- `hdfs dfs -get`으로 컨테이너 로컬 파일에 받은 뒤 컨테이너 안에서 해싱
- `hdfs dfs -checksum`으로 HDFS가 계산한 block checksum 대조

오염된 최초 측정값은 `canary-sha256-dn4-down-INVALID-crlf.txt`로 이름을 바꿔
보존했다. 삭제하지 않고 남긴 이유는 같은 함정을 반복하지 않기 위해서다.

## 5. DataNode 중지 read 검증

DataNode-4만 `docker stop`으로 중지했다. DataNode-4는 canary 3 block만 보유하므로
다른 데이터의 가용성에 영향이 없다. named volume은 삭제하지 않았고 `down`도 쓰지 않았다.

중지 상태에서 세 파일을 전량 read했다.

| 파일 | 기대 크기 | 실제 read | SHA-256 대조 |
|---|---:|---:|---|
| `part-00196` | 1,308,038 | 1,308,038 | setrep 이전 값과 일치 |
| `part-00197` | 1,298,042 | 1,298,042 | setrep 이전 값과 일치 |
| `part-00198` | 1,294,268 | 1,294,268 | setrep 이전 값과 일치 |

setrep 이전 값은 DataNode-4에서만 읽은 결과이므로, 같은 바이트가 두 host 어느
쪽에서든 동일하게 읽힌다는 것이 확인됐다.

이 read는 NameNode가 아직 DataNode-4를 Live로 보고하는 시점에 수행됐다. 즉
클라이언트가 두 replica 위치를 모두 받은 뒤 죽은 노드 연결 실패를 감지해 rack-a
replica로 failover한 것이며, 실제 노드 장애의 초기 양상과 같다.

## 6. Dead 전환 관측과 재복제 한계

dead 판정 시간은 설정값에서 계산된다.

```text
dfs.heartbeat.interval = 3
dfs.namenode.heartbeat.recheck-interval = 300000
dead timeout = 2 * 300s + 10 * 3s = 630s
```

15:28:30 UTC 중지 후 630초가 지나 NameNode가 DataNode-4를 `Dead datanodes (1)`로
전환했다. Live/Dead 목록에 중복 등록은 없었고 Live에는 rack-a 3대만 남았다.

이 상태에서 관측된 내용은 계획이 가정한 것과 다르다.

```text
No. of Expected Replica: 2
No. of live Replica: 2
Block replica on datanode/rack: 100.70.66.38/rack-a is HEALTHY
Block replica on datanode/rack: 100.71.215.74/rack-b is STALE
```

- 죽은 노드의 replica는 **제거되지 않고 `STALE`로 표시**됐다
- NameNode 집계의 `Under replicated blocks`는 계속 0이었다
- `Low redundancy blocks with highest priority to recover`도 0이었다
- 즉 **재복제가 예약되지 않았다**
- `Present Capacity`에는 죽은 DataNode-4의 용량이 계속 포함됐다

계획 Phase 5의 6번 gate는 "DataNode 복구 후 under-replicated block 0 확인"이다.
결과적으로 0이지만, 애초에 under-replicated가 상승하지 않았기 때문에 그 gate는
재복제 동작을 증명하지 못한다. 실제 host 상실 시 HDFS가 언제 재복제를 시작하는지는
이번 단계에서 검증되지 않았다. 11절에 미해결 항목으로 남긴다.

## 7. 복구 검증

DataNode-4를 `docker start`로 재기동했다.

| 검증 | 결과 |
|---|---|
| Live / Dead DataNode | 4 / 0 |
| canary block rack-b replica | `STALE` → `HEALTHY` |
| DataNode-4 UUID | `905d00e8-97ad-4314-972b-42f8b9e08e6e` (Phase 4와 동일) |
| cluster ID | `CID-47d1b1a7-56b7-480f-861c-0a3b9459a867` (Phase 0과 동일) |
| DataNode-4 block 수 | 3 (canary), DFS Used 3.79 MB |
| 전체 fsck | HEALTHY |
| missing / corrupt / under-replicated | 0 / 0 / 0 |
| mis-replicated | 240 (작업 전과 동일) |
| average block replication | 1.0222807 |

canary를 만들며 기존 데이터의 배치나 replication을 바꾸지 않았음이 mis-replicated
수치가 240으로 유지된 것으로 확인된다.

## 8. 기존 서비스 영향

DataNode-4 중지 구간 전체에서 service 서버 core/app 컨테이너 ID가 작업 전과 동일했다.

```text
backend       778aaa11a02b
frontend      40fdaebcfd3c
nginx         7202b48ae4cf
postgres      778dec7adf6c
redis         044ba1a8c3f7
kafka         d930ab8240c7
kafka-connect f1fecb8a6bfc
```

전부 healthy를 유지했고 `http://localhost/health`는 `200`과
`{"groups":["liveness","readiness"],"status":"UP"}`를 반환했다. data 서버의 Collector와
Worker는 중지하지 않았고 HDFS write quiesce도 필요하지 않았다.

## 9. 신규 검증 도구

`Infra/scripts/verify-hdfs-cross-host-replication.sh`를 추가했다. 읽기 전용이며
`setrep`, HDFS write, DataNode 제어를 수행하지 않으므로 운영 중 재실행이 안전하다.

검증 항목은 Live/Dead DataNode 수, 두 rack 존재, canary block별 replica 수, canary
block별 두 rack 동시 존재, 파일별 HDFS checksum 취득, 전체 missing/corrupt/
under-replicated 0, `/gitjob` fsck HEALTHY다. mis-replicated는 범위 밖이므로 판정에
넣지 않고 `INFO`로만 출력한다.

실제 클러스터 실행 결과는 12개 항목 `PASS`, 종료 코드 0이다.

구현에서 두 가지를 의도적으로 회피했다.

- `${line##*[}` 형태의 대괄호 glob은 이식성이 없어 `sed`로 replica 목록을 추출한다
- checksum은 `tail -n 1`과 `$NF`로 읽어 Java stack trace가 앞에 출력돼도 오판하지 않는다

## 10. 롤백

canary는 별도 경로이므로 롤백 범위가 작다.

1. `hdfs dfs -setrep -w 1 /gitjob/demo/distributed-proof`로 replication을 1로 되돌린다
2. 필요하면 `hdfs dfs -rm -r -skipTrash /gitjob/demo/distributed-proof`로 canary만 제거한다
3. 원본 `/gitjob/parquet/...`는 이번 단계에서 읽기만 했으므로 원복 대상이 아니다
4. DataNode-4를 중지해야 하면 canary replica가 rack-a에도 있는지 먼저 확인한다

Phase 4 문서 7절이 경고한 "DataNode-4가 유일 replica를 보유할 수 있음"은 이번
단계에서 실제 조건이 됐다. canary 생성 직후 3 block 모두 DataNode-4에만 있었고,
`setrep 2` 이후에야 rack-a에 복제됐다. 따라서 DataNode-4를 중지하기 전에는 항상
block별 replica 위치를 확인한다.

NameNode format, volume 삭제, `down --volumes`, Docker volume prune은 어떤 롤백에서도
수행하지 않는다.

## 11. 남은 한계와 다음 Phase

**재복제 미검증.** 6절 기준으로 죽은 DataNode의 replica는 `STALE`로 남고 재복제가
예약되지 않았다.

> 2026-09-11 정정: 이 결론은 **틀렸다.** [DataNode 간 재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md)
> 이후 같은 시나리오를 다시 시험한 결과, dead 전환 직후 NameNode가
> `Under replicated blocks: 243`, `Low redundancy blocks with highest priority to
> recover: 3`으로 재복제를 정상 예약했고 120초 만에 0으로 수렴했다
> (243 → 186 → 141 → 95 → 66 → 26 → 0). DataNode-4 복귀 30초 내에는 rack 교차
> 배치까지 자동 복원돼 under/mis-replicated가 모두 0이 됐다.
>
> 당시 0으로 관측된 이유는 두 가지가 겹친 것으로 본다. 첫째, 이 단계의
> DataNode-4는 canary 3블록만 보유해 재복제 대상이 극소수였고 측정 시점이
> 전환 직후였다. 둘째, 이 단계의 canary는 rack-b → rack-a 방향만 시험해
> 실제로 고장나 있던 rack-a → rack-b 방향을 건드리지 않았다.
>
> 재검증 기록은 [Phase 9 분산 처리 검증](2026-09-11-hdfs-spark-two-host-phase9-distributed-verification.md)
> 2절에 있다. 실제 host 상실 시의 복구 시점과 동작은 별도 검증이 필요하다.
현재 구성은 "두 host에 replica가 존재한다"는 것까지 증명했고 "한 host를 잃어도
자동으로 redundancy가 회복된다"는 것은 증명하지 않았다.

**신규 write가 service 서버로 쏠린다.** DataNode-4의 여유 공간이 가장 크므로
replication 1 신규 block은 우선 DataNode-4에 배치된다. 관측 시점의 Collector는 HDFS
write를 하지 않아 DataNode-4 block은 canary 3개뿐이었지만, 수집이 재개되면 service
서버에 유일 replica를 가진 운영 block이 쌓일 수 있다. service 서버를 가볍게 유지한다는
계획 6절의 전제와 충돌하므로 다음 중 하나를 별도로 결정해야 한다.

- 운영 write 경로의 replication 정책 조정
- DataNode-4의 `dfs.datanode.du.reserved` 확대로 배치 우선순위 조정
- 계획 12절의 "호스트당 DataNode 1개 정리" 작업에 포함

**mis-replicated 240건.** Phase 4 문서는 이를 "기존 replication 2 Parquet block"으로
기술했으나 실측은 `replication=3`으로 설정된 파일들이다. replica 수는 3/3 충족이라
under-replicated는 0이고, 두 번째 rack이 생겨 rack 정책만 위반 상태다. 주요 경로는
`/gitjob/parquet/github/repo_activity_weekly/period=2026-08/`과
`/gitjob/parquet/smoke/gitjob-smoke-v1/`이다. 재배치는 data 서버 I/O와 여유 공간에
영향을 주므로 이번 단계에서 다루지 않았다.

**Phase 3 잔여 항목.** Saramin 회차의 닫힌 `.uploading-*` 임시 파일 2개는 여전히
정리되지 않았다.

Phase 5는 `PASS`다. 계획 Phase 6에서 Spark Master와 data 서버 Worker-1을 host network와
Tailscale 주소로 전환한다. Worker-1 단독 smoke job과 기존 결과 checksum 비교를 먼저
통과해야 하며, 이번 단계에서 만든 canary 경로를 Phase 9의 HDFS canary job 입력으로
재사용할 수 있다.
