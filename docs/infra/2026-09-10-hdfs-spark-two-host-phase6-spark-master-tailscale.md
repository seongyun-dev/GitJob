# S15P21E102-207 Phase 6 Spark Master·Worker-1 Tailscale 전환

- 수행일: 2026-09-10
- 수행 시각: 15:58-16:20 UTC
- 대상: `J15E102A` data 서버 Spark Master, Spark Worker-1
- 상태: `PASS` — host network·Tailscale 전환과 결과 동일성 검증 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 5 교차 host 복제 canary](2026-09-10-hdfs-spark-two-host-phase5-cross-host-replication.md)

## 1. 범위와 작업 전 게이트

data 서버의 Spark Master와 Worker-1만 host network·Tailscale 주소로 전환했다.
Spark Worker-2는 시작하지 않았고 Collector, 분석 Worker, HDFS daemon, service 서버
스택은 중지하거나 재생성하지 않았다.

| 항목 | 작업 전 결과 |
|---|---|
| Spark Master / Worker-1 | 둘 다 `gitjob-data_default` bridge, 구 `compose.ec2-data.yaml` |
| host publish | `100.70.66.38:8083`, `100.70.66.38:8084` (docker-proxy), 7077/7078 미공개 |
| 실행 중 Spark application | 없음 (마지막 `app-20260910160414-0028` 정리 완료) |
| Live / Dead DataNode | 4 / 0 |
| fsck `/gitjob` | HEALTHY, missing/corrupt/under-replicated 0 / 0 / 0 |
| 서버 checkout | `e59712a`, clean |

증거는 data 서버의 다음 경로에 보존했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase6-20260910T160012Z
```

`.env.data`의 변경 전 사본을 `env.data.before`로 권한 `0600`으로 보존했다.

## 2. 기준선 보존과 결과 비교 기준의 재정의

계획 Phase 6은 "Worker-1 단독 smoke job과 기존 결과 checksum 비교"를 선행 게이트로
둔다. 이 게이트를 그대로 실행하면 두 가지 문제가 있어 방법을 바꿨다.

첫째, `spark-smoke.sh`의 기본 출력은 `${PARQUET_ROOT}/smoke/${DATASET_ID}`이고
`smoke_job.py`가 `mode("overwrite")`로 쓴다. 즉 기본값으로 실행하면 비교 대상인
기존 결과 `/gitjob/parquet/smoke/gitjob-smoke-v1`을 먼저 덮어쓴다. `dataset_id`는
모든 row의 컬럼 값이므로 이를 바꾸면 내용도 달라져 비교가 불가능하다. 그래서
`DATASET_ID`는 그대로 두고 `PARQUET_ROOT`만 별도 경로로 지정했다.

둘째, Parquet 파일은 바이트 재현성이 없다. part 파일명에 난수 UUID가 들어가고
footer에 빌드 문자열이 기록된다. 실제로 동일 입력·동일 구성으로 실행한 결과의
`hdfs dfs -checksum`이 기존 결과와 달랐다.

| 대상 | HDFS file checksum |
|---|---|
| 기준선 `part-00000` (2026-09-01) | `…55b613f2483ffc3d911b96c35f8be4ed` |
| 전환 전 재실행 `part-00000` | `…2f6b528257adbf1756cfd15a65a989a3` |

따라서 file checksum은 이 게이트의 판정 기준이 될 수 없다. 내용 기반 digest 도구를
추가해 판정 기준을 데이터로 옮겼다.

```text
Infra/spark/dataset_digest.py
Infra/scripts/spark-dataset-digest.sh
```

모든 값을 문자열로 렌더링하고 전체 튜플로 정렬한 뒤 그 정규 순서로 SHA-256을
계산하므로, 결과는 schema와 row 집합에만 의존한다. Phase 9의 "단일 Worker 기준
결과와 checksum 동일" 판정에도 같은 도구를 사용한다.

기존 결과는 이번 단계에서 읽기만 했다. 작업 종료 시점에도 타임스탬프
`2026-09-01 01:10`과 file checksum이 작업 전과 동일하다.

## 3. 전환 중 발견한 결함 두 건

### 3.1 host network에서 Spark 데몬이 자기 hostname을 해석하지 못함

Master를 host network로 처음 재생성했을 때 즉시 죽었다.

```text
java.net.UnknownHostException: spark-master: Temporary failure in name resolution
  at org.apache.spark.deploy.master.MasterArguments.<init>(MasterArguments.scala:31)
```

`MasterArguments`는 `--host`를 적용하기 전에 `Utils.localHostName()`을 평가한다.
bridge에서는 Docker DNS가 `spark-master`를 응답했지만 host network에서는 그 경로가
없다. 같은 host network를 쓰는 HDFS DataNode가 정상 동작하는 것과 대비되는데,
Hadoop 이미지는 `nss-myhostname`으로 자기 hostname을 로컬 주소로 해석하고 Spark
base 이미지는 그렇지 않기 때문이다.

overlay에 `extra_hosts`를 명시해 해결했다. Worker는 base compose가 scale을 위해
`hostname:`을 두지 않으므로 안정된 이름을 지정하고 함께 매핑했다.

```text
f8ef503 [S15P21E102-207] fix: host network Spark 데몬의 hostname 해석 보정
```

### 3.2 관리 UI가 wildcard 주소에 bind됨

수정 후 Master는 기동했지만 UI listener가 `*:8083`이었다.

```text
INFO MasterWebUI: Bound MasterWebUI to 0.0.0.0, and started at http://spark-master:8083
```

Spark `WebUI.bind()`는 `SPARK_LOCAL_IP`가 없으면 `0.0.0.0`으로 대체한다. bridge에서는
docker-proxy가 `100.70.66.38:8083`만 publish해 문제가 없었지만, host network에서는
관리 UI가 public interface에도 올라간다. data 서버 UFW가 기본 incoming deny이고
public 허용이 SSH 22뿐이어서 외부에서 접근되지는 않았으나, 계획 4.3절의 "`ss -lntp`에서
의도한 주소와 포트만 listen" 기준에 어긋난다.

`SPARK_LOCAL_IP`를 Tailscale 주소로 고정해 해결했다. 이 변경으로 UI가 127.0.0.1에
응답하지 않게 되므로 healthcheck 대상도 함께 바꿨다. 이들은 host network이므로
자기 Tailscale 주소로의 연결이 Phase 3에서 NameNode가 겪은 docker-proxy hairpin이
아니라 로컬 연결이다.

```text
d31d05f [S15P21E102-207] fix: host network Spark 리스너를 Tailscale 주소로 제한
```

## 4. 운영 env 변경

`.env.data`에서 두 줄만 바꿨다. 스크립트는 컨테이너 env가 아니라 이 파일에서 값을
읽으므로, overlay만 바꾸면 `spark-smoke.sh` 같은 경로가 여전히 bridge 이름을 향한다.

```text
HDFS_URI=hdfs://hdfs-namenode:8020      -> hdfs://100.70.66.38:8020
SPARK_MASTER_URL=spark://spark-master:7077 -> spark://100.70.66.38:7077
```

`HDFS_URI`는 전환 후 첫 smoke job이
`java.net.UnknownHostException: hdfs-namenode`로 실패해 발견했다. NameNode RPC는
Phase 3에서 이미 Tailscale 주소로 옮겨졌고, bridge 컨테이너도 Phase 3의 제한 UFW
규칙으로 `100.70.66.38:8020`에 접근할 수 있으므로 양쪽 클라이언트에서 동작한다.

## 5. 전환 결과

Master를 먼저 전환해 게이트를 통과한 뒤 Worker-1을 전환했다.

```text
INFO Master: Starting Spark master at spark://100.70.66.38:7077
INFO Master: I have been elected leader! New state: ALIVE
INFO Worker: Starting Spark worker 100.70.66.38:7078 with 2 cores, 2.0 GiB RAM
INFO Worker: Successfully registered with master spark://100.70.66.38:7077
```

listener는 네 포트 모두 Tailscale 주소 전용이다.

```text
[::ffff:100.70.66.38]:7077
[::ffff:100.70.66.38]:7078
[::ffff:100.70.66.38]:8083
[::ffff:100.70.66.38]:8084
```

| 검증 | 결과 |
|---|---|
| Master / Worker network mode | 둘 다 `host` |
| Compose `ports` 선언 | 없음 (계획 5.2절 요건) |
| 광고 주소에 Compose DNS 사용 | 없음 |
| Master health / restart | healthy / 0 |
| Worker health / restart | healthy / 0 |
| Worker 등록 주소 | `100.70.66.38:7078` |
| wildcard·public bind | 없음 |
| public probe 7077/7078/8083/8084 | 모두 차단 |

## 6. 결과 동일성 검증

같은 `dataset_id`로 전환 전후 각각 별도 경로에 실행하고, 기존 결과까지 세 데이터셋의
내용 digest를 비교했다.

| 데이터셋 | row_count | content_sha256 |
|---|---:|---|
| `/gitjob/parquet/smoke/gitjob-smoke-v1` (2026-09-01 기준선) | 3 | `4b460b76…92476` |
| `/gitjob/demo/phase6-pre/smoke/gitjob-smoke-v1` (전환 전) | 3 | `4b460b76…92476` |
| `/gitjob/demo/phase6-post/smoke/gitjob-smoke-v1` (전환 후) | 3 | `4b460b76…92476` |

세 값이 모두 동일하다. 전체 값은
`4b460b76a004e9f1469e090f9311ddd7f7dbf8146b42639d068f073316692476`이며 증거 파일
`dataset-digests.txt`에 보존했다.

전환 후 job은 `worker_count=1`, `spark_version=3.5.3`, ERROR 0으로 완료됐다.

## 7. 발견한 위험 — replication 3 write가 영구 under-replicated

검증 도중 전체 fsck의 under-replicated가 0에서 3으로 올라갔다. 원인은 다음과 같다.

- HDFS 클러스터 기본값은 `dfs.replication=1`이지만 **Spark 클라이언트는 `replication=3`으로 쓴다**
- `/rack-b`에는 DataNode가 DataNode-4 한 대뿐이다
- 기본 block 배치 정책은 replication 3에서 두 번째·세 번째 replica를 원격 rack에 두려 하는데, rack-b에 후보 노드가 하나뿐이라 세 번째를 배치하지 못한다

```text
part-00000-... 1087 bytes, replicated: replication=3, 1 block(s):
  Under replicated blk_1073763530_22706.
  Target Replicas is 3 but found 2 live replica(s)
```

즉 이 토폴로지에서 replication 3 write는 2 replica에서 멈추고 계속 under-replicated로
남는다. Phase 4·5에서 관측한 mis-replicated 240건도 같은 `replication=3` 파일들인데,
그것들은 rack이 하나였던 시점에 rack-a에 3개를 모두 확보했으므로 replica 수는
충족하고 rack 정책만 위반한다. 반대로 **rack이 둘인 지금 새로 쓰는 replication 3
블록은 replica 수 자체를 채우지 못한다.**

이번 단계에서 발생한 3건은 전부 이 단계의 테스트 출력이었다. 클러스터 기본값과
맞추기 위해 `setrep -w 1`로 되돌려 under-replicated를 0으로 복구했고, 운영 데이터의
배치는 바꾸지 않았다.

후속으로 다음 중 하나를 결정해야 한다.

- Spark 제출 경로에 `spark.hadoop.dfs.replication`을 클러스터 기본값과 맞춰 지정
- rack-b에 DataNode를 추가해 정책을 만족시킴
- replication 3을 쓰지 않기로 하고 운영 write 경로를 점검

## 8. 기존 서비스 영향

`--no-deps`로 대상 서비스만 재생성했다. Collector, 분석 Worker, HDFS 4개 daemon,
node-exporter는 재생성되지 않았고 계속 healthy였다.

service 서버 core/app 컨테이너 ID는 작업 전후 동일하고 `/health`는 `200`이다.

```text
backend  778aaa11a02b
nginx    7202b48ae4cf
postgres 778dec7adf6c
kafka    d930ab8240c7
```

HDFS는 Live 4 / Dead 0, fsck HEALTHY, missing/corrupt/under-replicated 0 / 0 / 0으로
작업 전과 같다. Phase 5 canary의 교차 host 배치도 그대로 `PASS`다.

분석 Worker는 bridge에 남아 있고 compose가 `SPARK_MASTER_URL`을 넘기지만,
`AI/` 코드에 이 값을 읽거나 `spark-submit`을 호출하는 경로가 없음을 확인했다. 따라서
Spark Master가 bridge를 떠난 것이 현재 운영 경로를 끊지 않는다. bridge에서 Spark로
제출하는 경로가 생기면 UFW의 `gitjob HDFS local bridge` 규칙에 7077/7078을 더하고
driver·BlockManager 주소를 Phase 8에서 함께 다뤄야 한다.

## 9. 롤백

1. `.env.data`를 `env.data.before`와 대조해 `HDFS_URI`와 `SPARK_MASTER_URL` 두 줄만 되돌린다
2. `compose.ec2-data.yaml`로 `up -d --no-deps spark-worker`, 이어서 `spark-master`를 재생성한다
3. Master UI에서 Worker 1개 `ALIVE`를 확인한다
4. 기준선과 동일한 방법으로 smoke job을 실행해 content digest가 `4b460b76…92476`인지 확인한다

Spark는 상태를 named volume에 두지 않으므로 volume 조작이 필요하지 않다. HDFS
daemon과 DataNode-4는 이 롤백 대상이 아니다.

## 10. 남은 한계와 다음 Phase

- 7절의 replication 3 배치 문제는 후속 결정이 필요하다
- bridge에서 Spark Master로의 제출 경로는 UFW·driver 주소가 정리되지 않아 아직 불가하다
- Phase 5의 재복제 미검증 항목은 그대로 남아 있다
- mis-replicated 240건과 Phase 3의 Saramin `.uploading-*` 임시 파일 2개도 미해결이다

Phase 6은 `PASS`다. Phase 7에서 service 서버의 별도 project에 Spark Worker-2를
`CLUSTER_WORKER_PROFILES=spark-worker`로 가입시키고, Master UI에서 서로 다른 두
Tailscale IP의 Worker가 `ALIVE`인지 확인한다.
