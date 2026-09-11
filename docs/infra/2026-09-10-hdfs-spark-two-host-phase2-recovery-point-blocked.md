# S15P21E102-207 Phase 2 복구점 생성 차단 기록

- 점검일: 2026-09-10
- 운영 점검 시각: 12:30-12:32 UTC
- 대상: `J15E102A` data 서버
- 상태: `BLOCKED` — 복구점 미생성, 운영 변경 미실행
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 1 구현·정적 검증](2026-09-10-hdfs-spark-two-host-phase1-static-implementation.md)

## 1. 이번 시도의 범위

Phase 2 진입 전 gate만 읽기 전용으로 다시 확인했다. 다음 작업은 수행하지 않았다.

- Collector, Worker, bootstrap container stop/kill/restart
- HDFS safe mode 진입 또는 해제
- `saveNamespace`
- HDFS write, replication 변경, volume 조작
- Docker prune 또는 daemon restart
- EBS snapshot 요청
- 운영 checkout switch/reset/stash/commit

따라서 기존 서비스와 실행 중인 데이터 작업에는 영향이 없다.

## 2. 재점검 결과

| 항목 | 결과 |
|---|---|
| data server branch/HEAD | `develop` / `5bbc129` |
| 운영 checkout | staged 변경 80개, 여전히 dirty |
| Docker metadata | `docker system df` 정상 반환, 기존 오류 재현 안 됨 |
| root filesystem | 309 GiB 중 138 GiB 사용, 172 GiB 가용, 45% 사용 |
| memory | 15 GiB 중 11 GiB available, swap 없음 |
| HDFS safe mode | OFF |
| HDFS fsck `/gitjob` | HEALTHY |
| missing/corrupt block | 0 / 0 |
| under/mis-replicated block | 0 / 0 |
| 평균 block replication | 1.0225215 |

Phase 0의 Docker stale snapshot metadata 오류는 이번 재점검에서 재현되지 않았다.
원인을 고쳤다고 단정할 수는 없지만 Phase 2의 직접 blocker에서는 제외한다.

## 3. Blocker 1 — active WebHDFS writer

다음 one-shot container가 점검 중 실행 중이었다.

```text
gitjob-data-repo-snapshot-bootstrap-run-e2cf0adae9d6
started: 2026-09-10T12:29:22Z
status: running
limit: 10000
artifact store: webhdfs
```

이 작업은 `/gitjob/analysis_input/github/repo_snapshot/...`에 WebHDFS로 artifact와
snapshot을 게시한다. 따라서 Collector와 일반 Worker만 멈춰도 HDFS write가
quiesce되지 않는다.

작업 소유자와 checkpoint 정책을 확인하지 않고 kill하면 부분 결과 또는 재수집
비용을 만들 수 있다. 이번 시도에서는 종료시키지 않았으며, 자연 완료를 기다리거나
소유자가 checkpoint를 확인한 뒤 정상 중단해야 한다.

## 4. Blocker 2 — EBS snapshot 실행 권한 부재

저장소에는 EBS snapshot script나 snapshot ID 기록이 없고, 현재 로컬 및 data
서버에는 AWS CLI가 없다. 현재 실행 환경에서 AWS API credential 또는 snapshot
생성 권한도 확인되지 않았다.

Phase 2의 목적은 `saveNamespace`만 실행하는 것이 아니라 같은 시점의 data 서버
root EBS snapshot ID를 확보하는 것이다. snapshot을 만들 수 없는 상태에서 writer를
멈추고 safe mode만 부분 실행하는 것은 서비스 영향만 만들고 복구점을 완성하지
못하므로 진행하지 않았다.

재개 전 다음 값과 권한이 필요하다.

- data EC2 instance ID, region/AZ
- root device와 source EBS volume ID
- `ec2:CreateSnapshot`, `ec2:DescribeSnapshots`, tag 생성 권한이 있는 실행 경로
- snapshot ID를 이 Phase 문서에 기록할 수 있는 운영 절차

credential, PEM, 환경 변수 전체 값, KMS secret은 문서에 기록하지 않는다.

## 5. Blocker 3 — dirty 운영 checkout

Phase 0과 동일하게 data 서버 checkout에는 staged 변경 80개가 남아 있다. 이번
Phase는 checkout 변경 없이 기존 container 명령으로 수행할 수 있지만, 뒤따르는
Phase 3 배포는 clean checkout 없이는 불가능하다.

이번 시도에서는 해당 변경을 조회만 했고 restore/reset/stash/commit하지 않았다.
소유자 확인과 보존 방법이 확정되기 전에는 branch 전환이나 배포를 수행하지 않는다.

## 6. 재개 절차

다음 순서를 모두 만족한 뒤 Phase 2를 처음부터 다시 수행한다.

1. bootstrap writer 자연 완료 또는 소유자 승인 하 정상 checkpoint 중단
2. Collector와 HDFS write를 수행하는 모든 job 식별
3. AWS snapshot 실행 주체와 source volume ID 확인
4. data checkout 변경 소유자와 보존 방법 확인
5. Spark active application/driver 0 확인
6. HDFS open file 0 및 전체 fsck HEALTHY 확인
7. writer 정지 상태에서 safe mode 진입
8. `saveNamespace` 성공
9. EBS snapshot 생성, snapshot ID 및 상태 기록
10. safe mode 해제 후 report/fsck 재검증

## 7. 롤백 및 서비스 영향

변경을 수행하지 않았으므로 롤백할 항목이 없다. HDFS safe mode는 계속 OFF이고
실행 중 bootstrap과 기존 Collector/Worker도 그대로 유지됐다.

## 8. 다음 Phase 판정

`BLOCKED`. 유효한 EBS snapshot ID가 문서에 기록되고 HDFS post-check가 통과하기
전에는 Phase 3 NameNode/DataNode 전환을 시작하지 않는다.
