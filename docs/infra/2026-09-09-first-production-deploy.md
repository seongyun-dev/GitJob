# 첫 운영 배포 기록 (2026-09-09)

배포된 커밋: `0a1e546` · Jenkins 빌드 `#39` · `DEPLOY_ENABLED=true` 수동 실행

이날 이전까지 두 EC2 호스트에는 컨테이너가 모두 healthy 상태로 떠 있었지만, 실제
애플리케이션은 한 번도 배포된 적이 없었다. 이 문서는 그 격차를 어떻게 확인했고 무엇을
했는지 남긴다. 같은 상황이 다시 생겼을 때 `Infra/scripts/verify-deployment.sh`부터
돌리면 된다.

## 배포 전 상태

| | 서비스 호스트 | 데이터 호스트 |
| --- | --- | --- |
| checkout | `571d9be` (27커밋 뒤) | `edfa96d` (10커밋 뒤) |
| backend | 자바 파일 1개짜리 골격 | — |
| 데이터베이스 테이블 | **0개** | — |
| `wal_level` | `replica` | — |
| kafka-connect | 없음 | — |
| worker | — | `/ready` 없는 구버전 이미지 |
| `c_compute` 스키마 | — | 없음 |

컨테이너는 전부 healthy였다. 컨테이너가 떠 있는 것과 기능이 동작하는 것은 다르다는 점이
이 배포 전체를 관통한다.

## 배포 후 상태

| | 이전 | 이후 |
| --- | --- | --- |
| checkout | 571d9be / edfa96d | 양쪽 `0a1e546` |
| 데이터베이스 테이블 | 0개 | 16개 (Flyway V1·V2) |
| `wal_level` | replica | logical |
| kafka-connect | 없음 | RUNNING |
| replication slot | 없음 | `gitjob_analysis_outbox` active |
| HDFS DataNode | 1개 | 3개 (926.79 GB) |
| `c_compute` | 없음 | 4개 테이블, `schema_version=1` |

## 배포 후 수동 단계

Flyway가 스키마를 만들지만, CDC 프로비저닝과 `c_compute` 마이그레이션은 자동이 아니다.
배포 직후 `verify-deployment.sh`가 무엇이 남았는지 알려주고, 각 항목의 복구 명령을 함께
출력한다. 실제로 실행한 순서는 다음과 같다.

```bash
# 서비스 호스트
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core,app \
  ./Infra/scripts/verify-deployment.sh          # schema OK, CDC 2건 ACTION

ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core \
  ./Infra/scripts/cdc-apply-prerequisites.sh    # 역할·GRANT·publication

ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core \
  ./Infra/scripts/cdc-register.sh               # Debezium 커넥터

# 데이터 호스트
ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml PROFILES=data \
  ./Infra/scripts/c-compute-migrate.sh          # c_compute 스키마
```

커넥터를 등록한 직후에는 `"tasks":[]`로 나온다. task가 뜨는 데 몇 초 걸리므로 바로
다시 확인하지 말고 잠시 기다린다.

## 검증

### CDC가 살아 있는지 — 쓰기 없이

커넥터 설정의 `heartbeat.action.query`가 10초마다 `public.cdc_heartbeat`를 갱신한다.
따라서 그 행의 `updated_at`이 계속 앞으로 가는지만 보면 Debezium이 WAL을 읽고 있는지
알 수 있다. 슬롯 지연이 거의 0이면 오프셋도 커밋되고 있다는 뜻이다.

```
updated_at 30초 간격 관찰: 02:23:40 → 02:24:10
gitjob_analysis_outbox  active=true  lag=328 bytes
```

### 종단 확인 — outbox 행이 Kafka 까지 가는가

위 두 가지는 "Debezium이 돌고 있다"까지만 말해 준다. outbox 행이 EventRouter를 거쳐
토픽에 꽂히는 것은 별개다. 합성 행 한 건을 넣어 확인했다.

```
토픽:     gitjob.repository-analysis.requests.v1   (outbox 의 topic 컬럼이 결정)
키:       verify-178-repo                          (analysis_repository_id)
페이로드: {"probe":"S15P21E102-178"}               (event_json, Debezium 봉투가 아닌 원본)
헤더 id:  verify-178-event                         (event_id)
```

네 값이 각각 커넥터 설정의 다른 필드에서 나오므로, 이것으로 EventRouter 전체가 확인된다.

확인 후 행 2건과 토픽을 삭제했다. Kafka 메시지는 지울 수 없어 토픽째 지웠다. 남겨두면
나중에 실제 소비자가 `auto.offset.reset=earliest`로 붙었을 때 시험용 이벤트를 읽는다.

이 시험이 안전했던 이유는 두 가지다. `analysis_job`에 `user` 테이블 FK가 없어 사용자 행을
만들 필요가 없었고, 이 토픽을 소비하는 코드가 아직 없어 가짜 이벤트가 아무것도 일으키지
않았다. 둘 중 하나라도 바뀌면 같은 방식을 그대로 쓰면 안 된다.

## 이날 도구에서 고친 것

배포에 실제로 써 보고 두 가지를 고쳤다. 둘 다 검증 없이는 드러나지 않았을 문제다.

**실행 권한** — `cdc-register.sh`를 포함한 스크립트 3개에 실행 비트가 없었다.
`verify-deployment.sh`가 출력하는 복구 명령과 문서가 모두 `./Infra/scripts/...` 형태라
`Permission denied`가 난다. 이날은 `bash`로 우회했고 이후 `+x`를 부여했다.

**비활성 상태가 누락을 가림** — worker의 `/ready`는 인증을 먼저 검사하므로,
`C_COMPUTE_TOKEN`이 비어 있으면 스키마 유무에 도달하지 못하고 `C_COMPUTE_NOT_CONFIGURED`를
반환한다. `verify-deployment.sh`는 이것을 SKIP으로 분류했는데, 그 결과 데이터 호스트가
**`c_compute` 스키마 없이 배포된 것을 전 항목 SKIP으로 통과**시켰다. 토큰이 비었을 때
데이터베이스를 직접 조회해 두 상태를 구분하도록 고쳤다.

두 번째는 이 문서 전체의 주제를 그대로 반복한다. 검사 도구조차 "확인하지 않음"을
"문제 없음"으로 보고할 수 있다.

## 이후 자동화

이 배포 직후 `deploy.sh`가 마지막에 두 호스트의 `verify-deployment.sh`를 실행하도록
연결했다. 한쪽에서 멈추지 않고 양쪽을 모두 배포한 뒤 검증하며, 어느 한쪽이라도 준비되지
않으면 배포를 실패로 끝낸다. 커넥터를 등록한 직후에는 task가 아직 없어 실패로 보이므로
`VERIFY_TIMEOUT_SECONDS` 재시도를 준다.

따라서 앞으로는 배포 한 번으로 두 호스트가 정상화되고, 정상화되지 않았다면 빌드가
빨간불로 알려준다. 볼륨이 소실되어 CDC 전제조건이나 `c_compute`가 사라진 경우에는 여전히
사람이 위 명령을 실행해야 하고, 그때 무엇을 실행해야 하는지는 빌드 로그에 그대로 찍힌다.

## 아직 하지 않은 것

- **C compute API는 비활성이다.** `C_COMPUTE_TOKEN`이 비어 있고 이는 `.env.example`이
  문서화한 설계된 상태다. 스키마는 적용해 두었으므로 토큰만 넣으면 켜진다.
- **데이터 서비스의 기능 검증은 하지 않았다.** collector·spark·HDFS는 컨테이너 health와
  DataNode 3개 등록까지만 확인했고, 실제 수집·집계가 도는지는 보지 않았다.

남은 항목은 `docs/be/2026-09-09-flyway-rollout-followups.md`를 따른다.
