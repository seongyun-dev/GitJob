# S15P21E102-207 Phase 2 Linux off-host 복구점

- 수행일: 2026-09-10
- 수행 시각: 12:55-13:01 UTC
- 대상: `J15E102A` data 서버, `J15E102` service 서버
- 상태: `PASS` — NameNode namespace 복구점 생성 및 off-host 검증 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 최초 진입: [Phase 2 차단 기록](2026-09-10-hdfs-spark-two-host-phase2-recovery-point-blocked.md)

## 1. 대체 결정

두 EC2는 SSAFY에서 대여한 서버로 AWS console/API 권한 없이 Linux 서버처럼
운영한다. 따라서 원래 계획의 EBS snapshot을 만들 수 없다.

이번 작업의 직접 위험은 기존 HDFS volume을 삭제하는 것이 아니라 DataNode의
network mode와 광고 주소를 바꾸는 것이다. 이에 맞춰 다음 복구점을 만들었다.

- data 서버의 기존 NameNode named volume metadata 전체 archive
- `saveNamespace` 결과, HDFS report, namespace `VERSION`, volume inspect
- 별도 물리 host인 service 서버로 동일 archive 복사
- 양쪽 SHA-256 일치 검증

이 복구점은 NameNode metadata 손상과 Compose/network 전환 rollback을 위한 것이다.
DataNode block 전체를 복제하지 않았으므로 data 서버 디스크 자체가 소실되는 상황의
full disaster recovery는 제공하지 않는다.

## 2. Writer quiesce

점검 당시 10,000 repository 대상 `repo-snapshot-bootstrap`이 WebHDFS로 쓰는 중이었다.
checkpoint가 원자적으로 저장되는 것을 확인한 뒤 Docker의 정상 종료 신호로
중단했다.

| 항목 | 결과 |
|---|---|
| checkpoint JSON | valid |
| 전체 candidate | 10,000 |
| 저장된 terminal 상태 | 889 |
| 발표 완료 snapshot | 없음 |
| 재개 가능성 | 동일 checkpoint와 기존 명령으로 재개 가능 |

강제 파일 삭제, checkpoint 수정, HDFS partial output 삭제는 수행하지 않았다.
container는 one-shot `--rm` 실행이어서 종료 후 사라졌고 checkpoint는 bind-mounted
host 경로에 유지됐다.

상시 HDFS writer인 `gitjob-data-collector-1`과 `gitjob-data-worker-1`도 정상
종료했다. 별도 tmux Spark 명령은 잔여 session이었으며 Spark Master와 worker
process를 대조한 결과 active application 0, active driver 0이었다.

## 3. 사전 HDFS gate

| 항목 | 결과 |
|---|---|
| safe mode | OFF |
| `dfsadmin -listOpenFiles -path /gitjob` | open file 0 |
| `fsck /gitjob -openforwrite` | HEALTHY |
| 전체 `fsck /gitjob` | HEALTHY |
| missing block | 0 |
| corrupt block | 0 |
| under/mis-replicated block | 0 / 0 |
| Live DataNode | 3 |

이 gate가 통과된 뒤에만 namespace 저장을 수행했다.

## 4. Namespace 저장

실행 순서는 다음과 같다.

1. NameNode safe mode 진입
2. safe mode `ON` 확인
3. `hdfs dfsadmin -saveNamespace`
4. `Save namespace successful` 확인
5. NameNode `/data/name` 전체 archive
6. SHA-256 및 HDFS/volume 식별 자료 생성
7. safe mode 해제
8. safe mode `OFF` 확인

NameNode format, volume 삭제, cluster ID 변경, DataNode restart는 수행하지 않았다.

## 5. 복구점 위치와 무결성

양쪽 서버의 동일 경로에 저장했다.

```text
/home/ubuntu/backups/gitjob-hdfs/phase2-20260910T125908Z
```

archive:

```text
namenode-data.tar.gz
size: 6.1 MiB
sha256: a86f065fca138dbecbf8fa74820630858ec6f56c16b79f8f8f74ffd366b27b2c
```

service 서버에서 `sha256sum -c SHA256SUMS`를 실행해 다음 파일이 모두 `OK`임을
확인했다.

- `namenode-data.tar.gz`
- `dfsadmin-report.txt`
- `namenode-volume-inspect.json`
- `namespace-version.txt`
- `safemode-enter.txt`
- `save-namespace.txt`

PEM, token, remote env, credential은 archive나 문서에 포함하지 않았다.

## 6. 사후 검증과 서비스 복구

상시 Collector/Worker를 다시 시작해 모두 `running healthy`를 확인했다. bootstrap은
다음 인프라 전환과 충돌하지 않도록 checkpoint 상태로 중지했다.

| 항목 | 결과 |
|---|---|
| NameNode safe mode | OFF |
| HDFS fsck | HEALTHY |
| missing/corrupt block | 0 / 0 |
| under-replicated block | 0 |
| Live DataNode | 3 |
| Collector | running healthy |
| Worker | running healthy |
| service Backend `/health` | UP |
| service Nginx HTTPS health | ok |
| service core/app containers | 기존 상태 유지, healthy |

## 7. 롤백 사용 범위

Phase 3 이후 NameNode metadata 복구가 필요한 경우 먼저 현 volume을 보존하고,
모든 HDFS daemon을 중단한 유지보수 상태에서 이 archive를 별도 volume에 복원해
식별 정보와 checksum을 검증한다. 실행 중인 NameNode volume 위에 바로 덮어쓰지
않는다.

단순 주소 광고 실패는 archive 복원보다 Compose/network 설정 원복과 기존 named
volume 재연결을 우선한다.

## 8. 다음 Phase 판정

복구점 기준 `PASS`다. Phase 3 전환 전 남은 blocker는 data 서버 checkout의 staged
변경 80개다. 변경을 patch/stash 등 복구 가능한 형태로 보존하고 checkout을 clean
상태로 만든 뒤에만 새 branch를 배포한다.
