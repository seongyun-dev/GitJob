# Production Data deploy topology guard

2026-09-17 05:16 outage의 기록과, 같은 일이 다시 일어나지 않게 하는 계약
(S15P21E102-300).

## 무슨 일이 있었나

`~/workspace/S15P21E102-monitoring` (stale HEAD `2f62651`) 의 `deploy.sh` 가
실행되면서 운영 Data 프로젝트를 덮어썼다. 세 가지가 맞물렸다.

```bash
data_path="${data_path:-/home/ubuntu/workspace/S15P21E102}"   # ① 운영 경로가 기본값
compose="$(compose_command "$data_path" "$data_env_file" compose.ec2-data.yaml)"  # ② 구 override
${compose} --profile data up -d --no-build                     # ③ --no-recreate 없음, 대상 미지정
```

① `data_path` 기본값이 **자기 checkout이 아니라 운영 checkout**이다.
② 그 리비전은 아직 `compose.ec2-data.yaml`(단일 노드)을 가리키는데, `develop`은
그 사이 `compose.ec2-data-cluster.yaml`로 옮겨갔다.
③ 대상 서비스 없이 `up -d` 하면 프로젝트 전체를 reconcile한다.

`COMPOSE_PROJECT_NAME=gitjob-data`는 `.env.data`에서 오고 `compose_command()`는
`-p`를 넘기지 않는다. 두 checkout이 **같은 env 파일**을 읽으므로 프로젝트 이름이
일치하는 것은 우연이 아니라 구조적으로 보장된다. `compose_command`가
`-f "$deploy_path/Infra/compose/..."`로 파일을 운영 경로에서 읽기 때문에 파일은
모두 존재했고 명령은 조용히 성공했다.

## 왜 그게 장애가 됐나

```
compose.ec2-data.yaml         : collector worker hdfs-namenode hdfs-datanode{,2,3}
                                spark-master spark-worker
compose.ec2-data-cluster.yaml : + hdfs-bootstrap  + spark-c1-archiver
                                + weekly-trend-consumer
```

`hdfs-bootstrap`은 safeMode를 푸는 주체다. 그것이 빠진 topology로 reconcile되면서
**HDFS SafeMode / LiveDataNode=0**이 됐고, `spark-c1-archiver`도 함께 사라져
**Historical 2026-03 artifact resolver가 terminal=2500에서 중단**됐다.

HDFS는 복구됐다 (Safe mode OFF, Live datanodes 4, Missing blocks 0).

## monitoring overlay는 원인이 아니다

`docs/infra/2026-09-10-gitjob-system-monitoring.md`의 절차는
`--no-deps --no-recreate --no-build node-exporter`로 **대상 1개만** 올린다. 이
명령은 `node-exporter`만 만들었고 다른 것을 부수지 않았다.

다만 그 문서의 데이터 서버 절차가 base override로 `compose.ec2-data.yaml`을 쓰고
있었다. 그것만으로 장애가 나지는 않지만 `node-exporter`가 운영과 다른 base에서
렌더링되게 만든다. 같은 Jira에서 정정했다.

## Guard 계약

`Infra/scripts/deploy_guard.py`. 순수 함수라 Docker·클러스터·checkout 없이
`AI/tests/test_deploy_topology_guard.py`에서 전부 검증된다.

### A. Full Data deploy

`--profile data up -d` 같은 전체 reconcile은 아래를 모두 만족해야 한다.

| 조건 | 거부 사유 |
|---|---|
| 운영 checkout에서 실행 | 다른 working tree에서 운영 프로젝트를 reconcile |
| `compose.yaml` 포함 | base 누락 |
| `compose.ec2-data-cluster.yaml` 포함 | cluster override 누락 |
| `compose.ec2-data.yaml` **미포함** | 단일 노드 override로 cluster 프로젝트 reconcile |
| `data` profile 선택 | 프로필 불일치 |
| canonical service 전부 렌더링 | `hdfs-bootstrap` 등 누락 → compose가 삭제함 |

override 순서는 병합 결과에 의미가 없으므로 검사하지 않는다.

### B. Targeted observability deploy

monitoring 작업은 별도 계약으로 **허용**한다. monitoring overlay가 하나 더
붙는 것 자체는 mismatch가 아니다.

- 대상 서비스 명시 (없으면 전체 reconcile과 같다)
- 대상은 monitoring 서비스만 (`node-exporter` 등)
- `--profile observability`
- `--no-deps`, `--no-recreate`
- base는 `compose.ec2-data-cluster.yaml`

### B-2. Observability remediation mode (S15P21E102-304)

`--no-recreate`는 monitoring 실행이 reconcile로 변질되는 것을 막는다. 그런데 그
요구가 monitoring 작업이 가끔 해야 하는 **정당한 수리 하나**도 막는다 — bind
mount가 잘못된 checkout을 가리키는 컨테이너의 교체다. mount는 컨테이너 생성
시점에 고정되므로 config reload로는 바뀌지 않고 recreate만이 바꾼다.

`S15P21E102-292`가 확인한 Production Prometheus가 정확히 이 모양이다.

```
현재 mount   : /home/ubuntu/workspace/S15P21E102-monitoring/Infra/monitoring/prometheus/prometheus.yml
canonical    : /home/ubuntu/workspace/S15P21E102/Infra/monitoring/prometheus/prometheus.yml
```

`--remediation` 은 **`--no-recreate` 요구만** 면제한다. 나머지는 그대로다.

| 조건 | normal | remediation |
|---|---|---|
| explicit target | 필수 | 필수 |
| monitoring 서비스만 target | 필수 | 필수 |
| `--profile observability` | 필수 | 필수 |
| `--no-deps` | 필수 | 필수 |
| canonical cluster base | 필수 | 필수 |
| `--no-recreate` | **필수** | **면제** |
| canonical checkout에서 실행 | — | **필수** |
| `REMEDIATION_SERVICES` 소속 | — | **필수** |

```python
REMEDIATION_SERVICES = ("prometheus",)
```

**모드가 계약을 느슨하게 하는 것이 아니라 allowlist가 대상을 좁힌다.** monitoring
서비스라는 이유만으로 자격이 생기지 않는다 — `node-exporter` / `grafana` /
`kafka-exporter` 는 remediation으로 recreate할 수 없다.

checkout을 선언하지 않으면 fail-closed다. "선언되지 않음"은 "canonical임"이
아니다.

#### json-exporter는 remediation이 필요 없다

`up -d --no-deps --no-recreate json-exporter` 는 **없는 컨테이너를 생성한다.**
`--no-recreate` 는 이미 있는 컨테이너의 recreate만 막지 생성을 막지 않는다.
따라서 json-exporter는 normal mode로 처리되고 allowlist에 넣지 않는다 —
`test_json_exporter_needs_no_remediation_to_be_created` 가 이것을 고정한다.

실행 순서도 이쪽이 맞다. Prometheus가 json-exporter를 scrape하므로 json-exporter를
먼저 만들고 그다음 Prometheus를 canonical config로 recreate한다.

### C. Service-aware 검증 — 프로젝트 전체 동일성 비교를 하지 않는다

"같은 프로젝트의 모든 컨테이너 `config_files`가 동일해야 한다"는 규칙은 **틀렸고,
다음 정상 배포를 막았을 것이다.** 정상적인 차이가 셋 있다.

| 서비스 | 판정 | 이유 |
|---|---|---|
| canonical Data services | cluster override 기준 | 실제 렌더링에 영향 |
| `node-exporter` | cluster + monitoring overlay **허용** | 의도된 overlay |
| `analysis-worker` | **LABEL_ONLY** | base에만 정의돼 있어 어느 data override를 썼든 렌더링이 같음 |

`classify_running_service()`가 서비스별로 `OK` / `LABEL_ONLY` / `RECONCILE`을
낸다. **`RECONCILE`만 실제로 잘못 렌더링된 것**이고, `LABEL_ONLY`는 라벨이
과거를 기록할 뿐이라 recreate를 요구하지 않는다.

### D. Checkout guard

운영 full deploy는 승인된 ref에서만 허용한다. 판정은 브랜치 이름이 아니라
**조상 관계**로 한다.

| 상태 | 판정 | 이유 |
|---|---|---|
| HEAD == approved ref | PASS | |
| approved의 **조상** | FAIL | stale — 현재 topology를 모른다 (2026-09-17이 이 경우) |
| approved의 **자손** | FAIL | 미병합 코드는 운영에서 시험하지 않는다 |
| 무관 | FAIL | 어떤 topology를 담았는지 말해주는 것이 없다 |
| dirty | FAIL | 재현 불가능한 배포 |
| ref 확인 불가 | FAIL | fail-closed |

> **운영 main checkout 사례.** 2026-09-17 시점 `/home/ubuntu/workspace/S15P21E102`
> 의 HEAD는 `2e7742b Merge commit '15065cd' into ai/S15P21E102-256-ai-llm` 로
> `develop`의 조상도 자손도 아니었다. 이 guard는 이것을 **무관(FAIL)** 으로
> 판정한다. feature 브랜치 merge는 리뷰되지 않은 compose 변경을 담고 있을 수도,
> 리뷰된 변경을 빠뜨렸을 수도 있어서 어느 쪽인지 알 수 없기 때문이다.
> 테스트 `test_unrelated_checkout_is_refused`가 이 사례를 고정한다.

## 배선 위치

`deploy.sh`는 `refresh_checkout` **직후, 아무것도 recreate하기 전에** 데이터
호스트에서 guard를 실행한다.

```
refresh_checkout ...
assert_data_deploy_contract      ← 여기
remove_legacy_data_weekly_consumer
build_data_images
start_data_app
```

배포를 실행하는 기계가 아니라 **배포 대상 호스트에서** 판정한다. 문제가 된 것은
언제나 대상 호스트의 checkout이었지 실행 기계가 아니었다.

## guard 도입 전 필요한 일회성 reconcile

현재 `gitjob-data` 프로젝트의 `node-exporter`는 stale monitoring checkout에서
렌더링됐고, 그 checkout의 `compose.yaml`은 develop과 **277줄 차이**난다. 기능은
하고 있으나 설정 변경이 재현되지 않는다.

```
RECONCILE  : node-exporter   — 올바른 base(cluster override) + monitoring overlay로
                               운영 checkout에서 targeted recreate
LABEL_ONLY : analysis-worker — 조치 불필요. 라벨만 구식이고 렌더링은 정상
OK         : 나머지 9개 canonical Data services
```

`analysis-worker`를 라벨 통일 목적으로 recreate하지 않는다. 그것이 이 문서가
프로젝트 전체 동일성 비교를 거부하는 이유다.

## 범위 밖

- monitoring 전용 `COMPOSE_PROJECT_NAME` 분리 — `node-exporter`는 설계상 같은
  프로젝트의 `observability` profile이고, 분리는 S15P21E102-292와 충돌한다
- `deploy.sh`에 `--no-recreate` 강제 — 정상 배포는 변경된 서비스를 recreate해야
  한다
- Production deploy / reconcile / HDFS 작업 / Historical resume

## 참고

- `S15P21E102-300` — 이 작업
- `S15P21E102-267` — Weekly Consumer profile 격리 (완료, 범위 다름)
- `S15P21E102-292` — 2호스트 모니터링 실지표 연결 (별도 담당)
- `docs/infra/2026-09-10-gitjob-system-monitoring.md` — observability-only 절차
