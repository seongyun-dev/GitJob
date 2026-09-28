# S15P21E102-207 Phase 1 구현·정적 검증 기록

- 작성일: 2026-09-10
- 대상 branch: `infra/S15P21E102-207-infra-hdfs-spark-2-split`
- 기준 commit: `2d31693`
- 상태: `PASS` — 로컬 설정 구현과 정적 검증 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 0 Preflight](2026-09-10-hdfs-spark-two-host-phase0-preflight.md)

## 1. 범위와 안전 경계

Phase 1에서는 운영 서버와 컨테이너를 변경하지 않았다. SSH를 통한 원격 명령,
firewall 변경, Docker build/up/restart, HDFS write, safe mode, EBS snapshot은 수행하지
않았다.

`origin/develop`의 신규 commit `2d31693`을 현재 branch에 fast-forward한 뒤
구현했다. 해당 commit이 추가한 Registry DB 설정을 유지했으며, 특히
`.env.example`, `Infra/compose/compose.yaml`, `Infra/scripts/verify-deployment.sh`의
신규 내용을 덮어쓰지 않았다.

Phase 0에서 확인된 다음 blocker도 그대로 유지한다.

- data 서버 운영 checkout의 staged 변경 80개
- data 서버 `docker system df`의 stale snapshot metadata 오류

## 2. 구현 결과

### 2.1 Data 서버 overlay

`Infra/compose/compose.ec2-data-cluster.yaml`을 추가했다. 기존
`compose.yaml`과 기존 Compose project를 유지하므로 NameNode 및 DataNode 1~3의
named volume 이름과 mount target은 바뀌지 않는다.

- NameNode RPC/UI는 data 서버 Tailscale 주소에만 publish
- DataNode 1~3은 host network와 서로 다른 HTTP/Data/IPC port 사용
- 각 DataNode가 Tailscale 주소를 hostname과 transfer address로 등록
- Spark Master와 Worker-1의 host, RPC, UI port를 고정할 설정 준비
- Collector/Worker는 bridge에 남고 Tailscale NameNode/Spark Master로 접속
- 기존 `compose.ec2-data.yaml`과 동시에 사용하지 않는 별도 overlay

이 파일은 Phase 2 복구점 생성 전 운영에 적용하면 안 된다.

### 2.2 Service 서버 독립 worker project

`Infra/compose/compose.ec2-cluster-worker.yaml`을 추가했다. 공통
`compose.yaml`이나 기존 service용 `compose.ec2.yaml`을 포함하지 않는 standalone
구성이다.

포함하는 서비스는 `hdfs-datanode4-data-init`, `hdfs-datanode4`,
`spark-worker2`뿐이다. project 기본 이름은 `gitjob-cluster-worker`이며 기존
`gitjob-service`의 Backend, Frontend, Nginx, PostgreSQL, Redis, Kafka를 참조하거나
재생성하지 않는다.

DataNode-4는 독립 volume
`gitjob-cluster-worker-hdfs-datanode4-data`를 사용한다. Spark Worker-2는 1 core,
1 GiB로 시작하고 container 상한은 1 CPU, 1536 MiB다. DataNode-4도 JVM heap 768
MiB, 0.5 CPU, container 1536 MiB로 제한했다.

### 2.3 Rack mapping

`Infra/hadoop/topology.sh`는 data/service Tailscale IP를 각각 `/rack-a`,
`/rack-b`로 반환하고 그 외 주소는 `/default-rack`으로 반환한다. 실제 rack이 아니라
두 EC2 failure domain을 구분하는 논리 이름이다.

### 2.4 Spark submit 공통 설정

네 Spark wrapper가 중복으로 갖고 있던 driver bind/host 옵션을
`Infra/scripts/_lib.sh`의 `spark_submit_network_args`로 통합했다.

- `spark-smoke.sh`
- `spark-c1-archiver.sh`
- `spark-repo-activity-topn.sh`
- `spark-repo-fetch-candidates.sh`

새 환경 변수가 비어 있으면 기존 `0.0.0.0` / `spark-worker` 동작을 유지한다.
Phase 8에서 Tailscale driver host와 고정 port 설정을 env에 넣으면 네 경로에
동일하게 적용된다.

### 2.5 운영·검증 도구

- `Infra/scripts/cluster-worker.sh`: 독립 project의 `config`, `up`, `health`,
  `down` 제공
- `Infra/scripts/validate-two-host-cluster.sh`: 신규/기존 Compose render와 주소,
  service 격리, volume, network mode, topology mapping 자동 검증

`cluster-worker.sh up`은 실행하지 않았다. `down`도 volume을 삭제하지 않는다.

## 3. 환경 변수 계약

`.env.example`에는 실제 IP가 아닌 빈 placeholder와 자원 기본값만 추가했다.
Phase 0에서 확인한 실제 Tailscale 주소는 운영 env에만 기록한다. 고정 Spark job
port도 Phase 8 전까지 빈 값이므로 현재 단일 host 실행에는 갑자기 적용되지 않는다.

## 4. 검증 결과

`Infra/scripts/validate-two-host-cluster.sh` 실행 결과:

```text
two-host cluster Compose assertions: PASS
two-host cluster static validation: PASS
```

기존 service/data EC2 Compose와 신규 data cluster/standalone worker Compose를 모두
render했다. DataNode 1~3의 host network와 고유 port, 신규 worker project의 정확한
service 집합, `ports`/Docker network 부재, DataNode-4 주소, Worker-2 Master URL,
독립 volume 이름, topology mapping을 assertion으로 확인했다.

Tailscale 주소가 비어 있을 때 cluster-worker Compose가 실패하는 것과 Spark 공통
helper가 기존 기본값 및 두 host 고정 옵션을 각각 올바르게 생성하는 것도 확인했다.

- 변경 shell script 전체 `bash -n`: PASS
- `git diff --check`: PASS
- `shellcheck`: 현재 WSL에 설치되지 않아 미실행
- image build와 container 실행: Phase 1 범위 밖으로 미실행

## 5. 기존 서비스 영향

없음. 운영 서버 명령과 container lifecycle 작업을 수행하지 않았다. 기존
`deploy.sh`도 새 cluster overlay를 자동 적용하지 않는다. 이는 평소 배포 한 번으로
Phase 2~8이 한꺼번에 실행되는 사고를 막기 위한 의도적 안전장치다.

## 6. 발견 위험과 대응

| 위험 | 대응 |
|---|---|
| 운영 checkout dirty | 소유자 확인 전 원격 branch 전환·배포 금지 |
| Docker metadata 오류 | prune/restart 금지, 복구점 후 유지보수 창에서 진단 |
| DataNode 주소 오등록 | Phase 3에서 한 노드씩 UUID/address/fsck gate |
| service stack 동반 재생성 | standalone project와 별도 제어 script 사용 |
| Spark job별 설정 불일치 | 공통 network argument 함수 사용 |
| Raw 114 GiB 자동 복제 | replication 기본 1 유지, canary만 별도 setrep |

## 7. 롤백

Phase 1은 저장소 파일만 변경했으므로 운영 롤백은 필요하지 않다. 코드 롤백이
필요하면 이 Phase의 변경 commit만 revert한다.

## 8. 다음 Phase 진입 판정

로컬 구현 기준 `PASS`다. 그러나 Phase 2의 운영 작업은 다음 조건이 해결돼야 한다.

1. data 서버 staged 변경 80개의 소유자와 보존 방법 확정
2. data 서버 Docker metadata 오류 재진단
3. Collector/분석 Worker 중지 시간 확정
4. EBS snapshot 생성 권한과 기록 위치 확인

위 조건 전에는 `cluster-worker.sh up` 또는 data cluster overlay 적용을 실행하지
않는다.
