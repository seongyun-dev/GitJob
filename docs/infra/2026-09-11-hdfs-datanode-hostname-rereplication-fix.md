# S15P21E102-207 DataNode 간 재복제 경로 수정

- 수행일: 2026-09-11 (UTC 기준 2026-09-11 00:25-00:50)
- 대상: `J15E102A` DataNode-1/2/3
- 상태: `PASS` — rack-b 대상 재복제 복구, 정체돼 있던 배치 위반 90건 자동 해소
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 관련: [Phase 4](2026-09-10-hdfs-spark-two-host-phase4-service-datanode4.md),
  [Phase 5](2026-09-10-hdfs-spark-two-host-phase5-cross-host-replication.md),
  [Phase 8](2026-09-11-hdfs-spark-two-host-phase8-driver-port-pinning.md)

## 1. 배경

Phase 8에서 Spark 제출 경로에 `spark.hadoop.dfs.replication=2`를 적용한 뒤, 신규
출력 블록 두 개 중 하나만 rack 교차 배치에 성공하고 나머지는 replica 1개로 남았다.
부하가 없는 상태에서 `setrep -w 2`로 복구를 시도해도 완료되지 않았다.

Phase 5에서 "죽은 DataNode의 replica가 `STALE`로 남고 재복제가 예약되지 않는다"고
기록한 항목과 같은 뿌리로 보여 원인을 조사했다.

## 2. 증상 분리

방향에 따라 결과가 갈리는 것을 확인했다. 클러스터가 완전히 idle(전 DataNode
`Xceivers: 0`)인 상태에서 두 블록에 동시에 `setrep 2`를 걸고 관측했다.

| 대상 | 기존 replica 위치 | 필요한 새 replica | 결과 |
|---|---|---|---|
| A | `/rack-a` | `/rack-b` | 60초 후에도 `Live_repl=1` |
| B | `/rack-b` | `/rack-a` | 10초 내 `Live_repl=2` |

즉 **DataNode-4를 대상으로 하는 재복제만 실패**했다. 반대 방향과, 클라이언트가
DataNode-4에 직접 쓰는 경로는 정상이었다. 실제로 `dfs.replication=1`로 쓴 테스트
파일 6개가 모두 DataNode-4에 배치됐다. 배치 능력 자체는 문제가 없었다는 뜻이다.

Phase 5의 canary 검증이 이 결함을 놓친 이유도 여기서 설명된다. 당시 canary는 세
블록 모두 DataNode-4에만 있었고 `setrep 2`가 rack-a에 replica를 추가했다. 즉
정상 동작하는 방향만 시험한 것이었다.

## 3. 원인

source DataNode의 로그에 정확한 실패가 남아 있었다.

```text
DatanodeRegistration(100.70.66.38:9886, datanodeUuid=32f7bc8d-...):
  Starting thread to transfer BP-...:blk_1073763539_22715 to 172.18.0.1:9866
  Failed to transfer BP-...:blk_1073763539_22715 to 172.18.0.1:9866 got
java.net.ConnectException: Connection refused
```

DataNode-4는 Phase 4에 기록한 대로 NameNode에 `Name: 172.18.0.1:9866`으로
등록돼 있다. NameNode가 bridge network에 있고 published port를 통해 원격 등록을
받기 때문에 접속 원본이 Docker gateway로 관측된 결과다.

`172.18.0.1`은 data 서버 입장에서는 **자기 자신의 bridge gateway**다. 따라서
rack-a DataNode가 이 주소로 블록을 전송하려 하면 연결이 거부된다.

Phase 4는 이 문제를 hostname 기반 연결로 우회하도록 설정했다.

```text
dfs.client.use.datanode.hostname=true
dfs.datanode.use.datanode.hostname=true
```

그러나 실제 적용 상태를 확인하니 일부에만 반영돼 있었다.

| 노드 | `dfs.datanode.use.datanode.hostname` |
|---|---|
| DataNode-1/2/3 (rack-a) | **`false`** |
| DataNode-4 (rack-b) | `true` |

원인은 적용 순서다. overlay 파일에는 세 DataNode 모두 `true`로 정의돼 있지만,
Phase 4에서 재생성한 것은 NameNode뿐이었다.

```text
hdfs-namenode   2026-09-10T14:43:42   ← Phase 4, 새 설정 반영
hdfs-datanode   2026-09-10T14:02:05   ← Phase 3 설정 그대로
hdfs-datanode2  2026-09-10T14:01:00   ← Phase 3 설정 그대로
hdfs-datanode3  2026-09-10T13:54:28   ← Phase 3 설정 그대로
```

Phase 4 문서는 이 설정을 "전체 HDFS daemon 및 Spark submit client에 적용했다"고
기술했으나, rack-a DataNode 세 대는 재생성되지 않아 실제로는 적용되지 않았다.

## 4. 수정

Phase 3과 같은 롤링 재생성으로 세 DataNode에 설정을 반영했다. 한 대씩
`--no-deps --force-recreate`로 재생성하고 각 단계마다 게이트를 확인했다.
named volume과 Compose 정의는 바꾸지 않았다.

| 노드 | 설정 반영 | UUID | 결과 |
|---|---|---|---|
| DataNode-3 | `true` | `32f7bc8d-a77f-48fd-b5e4-04fb3cafb37c` | 불변 |
| DataNode-2 | `true` | `dc3991a5-3b4d-4d76-831c-3be8b3353f02` | 불변 |
| DataNode-1 | `true` | `b1ce2dcf-e408-48e0-aa8c-31599b8a3d07` | 불변 |

각 재생성 직후 Live DataNode 4, fsck HEALTHY, missing/corrupt 0을 확인했다.
증거는 data 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/dn-hostname-fix-20260911T003125Z
```

## 5. 검증

### 5.1 재복제 복구

2절에서 실패했던 블록 A에 `setrep`을 재발행하자 10초 내에 수렴했다.

```text
Live_repl=2  [/rack-b/172.18.0.1:9866, /rack-a/100.70.66.38:9866]
```

재생성만으로는 자동 재시도가 일어나지 않았다. NameNode는 전송 실패가 누적된
블록을 무한 재시도하지 않으므로, 이미 포기된 블록은 `setrep`으로 다시 큐에
넣어야 한다.

### 5.2 정체돼 있던 배치 위반의 자동 해소

Phase 4부터 240건으로 고정돼 있던 mis-replicated 블록이 스스로 줄기 시작했다.

| 시점 | mis-replicated | DataNode-4 블록 수 | DataNode-4 사용량 |
|---|---:|---:|---:|
| 수정 전 | 240 | 6 | 3.82 MB |
| 수정 후 | 150 | 93 | 1.25 GB |

90개 블록이 rack-b로 복제됐고 전송 실패는 0건이다. 이 240건은 Phase 4·5·8에서
"범위 밖 backlog"로 기록해 왔는데, 실제로는 HDFS가 계속 고치려다 같은
`Connection refused`로 실패하고 있었던 것이다. source DataNode 로그에 그 흔적이
남아 있었다.

```text
Failed to transfer BP-...:blk_1073747647_6823 to 172.18.0.1:9866 got
java.net.ConnectException: Connection refused
```

남은 150건은 오류가 아니라 큐가 비어 멈춘 상태다. HDFS는 mis-replicated 블록을
상시 재스캔하지 않고 NameNode 기동이나 명시적 요청 시점에 평가한다. 이제는
구조적으로 불가능한 상태가 아니라 `setrep` 재발행이나 다음 NameNode 재기동으로
해소 가능한 상태다.

### 5.3 Spark replication 2 write

Phase 8에서 적용한 `spark.hadoop.dfs.replication=2`가 이제 의도대로 동작한다.
같은 smoke job을 다시 실행한 결과 두 블록 모두 rack 교차 배치에 성공했다.

```text
blk_...550  Live_repl=2  [/rack-a/100.70.66.38:9876, /rack-b/172.18.0.1:9866]
blk_...549  Live_repl=2  [/rack-b/172.18.0.1:9866, /rack-a/100.70.66.38:9866]
Under-replicated blocks: 0
Mis-replicated blocks:   0
```

### 5.4 최종 상태

| 검증 | 결과 |
|---|---|
| Live / Dead DataNode | 4 / 0 |
| 세 DataNode UUID | 모두 불변 |
| fsck `/gitjob` | HEALTHY |
| missing / corrupt / under-replicated | 0 / 0 / 0 |
| mis-replicated | 240 → 150 (자동 해소 진행) |
| Phase 5 canary 교차 host 게이트 | `PASS` |
| service core/app 컨테이너 ID | 불변 |
| service API `/health` | `200` |

## 6. 기존 서비스 영향

재생성 전 `dfsadmin -listOpenFiles`로 열린 파일이 없음을 확인했고, 한 대씩
순차 재생성했으므로 매 시점 Live DataNode는 3 이상이었다. Collector와 분석
Worker는 중지하지 않았다. service 서버는 이 작업의 대상이 아니며 컨테이너 ID와
health가 그대로다.

## 7. 남은 항목

- **mis-replicated 150건**: 이제 해소 가능하다. 다음 NameNode 재기동 때 자동
  처리되거나 `setrep` 재발행으로 앞당길 수 있다. 해소 시 약 1~2 GB가 추가로
  service 서버에 복제된다(현재 여유 280 GB)
- **Phase 5의 죽은 노드 재복제**: 이번 수정으로 전송 경로가 복구됐으므로 다시
  검증할 가치가 있다. Phase 5 6절의 "`STALE`로 남고 재복제되지 않음"이 같은
  원인이었는지는 재시험해야 확정된다
- **NameNode 등록 주소**: 근본적으로는 DataNode-4가 `172.18.0.1`이 아니라 자기
  Tailscale 주소로 등록되는 편이 낫다. 그러려면 NameNode를 host network로 옮겨야
  하는데 Phase 3·4에서 의도적으로 피한 변경이다. 현재는 hostname 우회로 동작하므로
  이번 범위에서 다루지 않는다

## 8. 다른 문서에 반영할 정정

- Phase 4 문서 3절의 "전체 HDFS daemon에 적용했다"는 실제로 NameNode에만
  적용됐다. 이 문서 3절을 참조하도록 정정한다
- Phase 5 문서 11절의 "재복제 미검증"은 원인이 특정됐다. 다만 죽은 노드 시나리오
  자체는 아직 재시험하지 않았다
- Phase 8 문서 5절의 under-replicated 관측은 이 결함이 원인이었다
