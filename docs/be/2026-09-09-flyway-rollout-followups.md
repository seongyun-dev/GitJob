# Flyway 전환 이후 남은 작업 (S15P21E102-172)

**이 문서는 임시다.** 아래 항목이 모두 끝나면 삭제한다. 남아 있다는 것은 아직 할 일이
있다는 뜻이다.

Flyway 도입으로 스키마 적용은 자동이 되었지만, 배포를 실제로 완주한 적이 없고 그 과정에
사람이 해야 하는 단계가 남아 있다. 여기 적어두지 않으면 잊는다.

---

## 배경: 왜 "배포 성공"을 믿으면 안 되는가

이번 전환 과정에서 드러난 문제들이 모두 같은 모양이었다.

| 사건 | 떠 있음 | 일할 수 있음 |
| --- | --- | --- |
| 빌드 #31 | CI는 `.env.ci`로 검증 통과 | 원격 env에는 키가 없었다 |
| AES | 앱 설정에 값이 있음 | compose가 컨테이너로 전달하지 않았다 |
| Flyway | `flyway-core`가 클래스패스에 있음 | 자동설정 모듈이 없어 무동작이었다 |
| kafka-connect | healthcheck 200 | 등록된 커넥터 0개 |
| worker | `/health` 정상 | `/ready`는 `C_MIGRATION_REQUIRED` |

**컨테이너가 healthy한 것과 기능이 동작하는 것은 다르다.** 아래 절차에서 healthcheck
결과가 아니라 실제 데이터 흐름을 확인하는 이유다.

---

## 1. 첫 배포 런북

첫 배포는 여러 가지가 동시에 처음이다. 서비스 호스트 checkout이 22커밋을 건너뛰고,
컨테이너 안 Gradle 빌드가 자바 1개에서 56개로 늘고, kafka-connect가 운영에서 처음 뜨고,
배포 preflight가 처음 실행된다. **한 번에 끝내려 하지 말고 `deploy.sh` 출력을 보면서
단계별로 확인한다.**

### 실행

Jenkins에서 `DEPLOY_ENABLED=true`로 수동 빌드한다. SCM 폴링 빌드는 파라미터 기본값이
`false`라 배포하지 않는다.

### 확인 (healthcheck를 믿지 말고 직접)

- [ ] **1) 스키마** — `flyway_schema_history`에 V1·V2가 `success=t`
- [ ] **2) worker** — `GET /ready`가 `READY`.
      `C_MIGRATION_REQUIRED`면 데이터 호스트에서 `python -m worker.migrate` 실행.
      운영 DB에 `c_compute` 스키마가 없으므로 **첫 배포에서는 반드시 필요하다.**
- [ ] **3) CDC 전제조건** — `db/cdc/cdc_prerequisites.sql`을 치환해 1회 적용한 뒤
      `pg_roles`에 `gitjob_cdc`, `pg_publication`에 `gitjob_analysis_outbox_pub` 확인
- [ ] **4) 커넥터 등록** — `Infra/scripts/cdc-register.sh` 실행 후
      `pg_replication_slots` 1건과 커넥터 상태 `RUNNING` 확인
- [ ] **5) 기능 확인** — 분석 요청 → `analysis_outbox`에 행 → Kafka 토픽에 메시지 도달

**5번이 진짜 확인이다.** 1~4가 모두 초록불이어도 5번이 안 되면 CDC는 죽은 것이고,
healthcheck는 이것을 잡아주지 못한다.

### 중단 기준

4번이나 5번에서 막히면 그 자리에서 `.env.service`의 `ANALYSIS_OUTBOX_MODE=POLLING`으로
전환한다. 백엔드 스케줄러가 직접 발행하는 경로이고 테스트 12개가 덮고 있다. 커넥터를
등록하기 전이라면 정리할 것도 없다.

### 배포 후 며칠

replication slot은 WAL을 붙잡는다. 커넥터가 등록된 채로 죽어 있으면 WAL이 쌓여 디스크가
찬다. `cdc_heartbeat`가 이것을 막지만 커넥터가 실제로 살아 있을 때만 유효하다. 슬롯
상태와 디스크를 며칠 지켜본다. 5번이 실패한 채 커넥터만 남겨두는 것이 가장 나쁘다.

---

## 2. 후속 티켓

우선순위 순이다.

### 2-1. healthcheck를 "일할 수 있음" 기준으로 (1순위)

worker는 `/ready`가 **이미 구현되어 있다.** compose healthcheck를 `/health`에서 `/ready`로
바꾸면 된다(인증이 걸려 있어 토큰 처리가 필요하다). kafka-connect는 커넥터 이름까지
확인하도록 바꾼다.

다른 항목은 모두 일회성 수정이지만 이것은 **부류를 잡는다.** 앞으로 생길 같은 종류의
실패도 자동으로 드러난다. 작업량도 작다.

### 2-2. `c_compute` 정리

`db/migration/`과 `db/migrations/`가 s 한 글자 차이로 공존한다. 통합하거나
`db/c-compute/`로 이름을 바꾼다. 어느 쪽이든 `AI/worker/store.py`와 `AI/worker/migrate.py`의
경로를 고쳐야 하므로 **C조와 협의가 선행되어야 한다.**

배포 절차에 `python -m worker.migrate`를 넣는 것은 그와 별개로 필요하다.

### 2-3. env 전수 대조

`Infra/scripts/check-required-env.sh`는 Compose가 필수로 선언한 `${VAR:?}` 변수만 본다.
기본값이 있는 나머지 키는 빠져도 조용히 기본값으로 동작한다. `.env.example` 전체와
대조하도록 확장할 수 있지만, **기본값이 있는 키까지 강제할 것인가**는 정책 결정이 먼저다.

### 2-4. 프론트엔드

`FE/package.json`에 테스트 프레임워크가 없다(vitest·jest·testing-library 모두 없음).
CI의 Frontend test 스테이지는 `tsc --noEmit`과 `vite build`만 수행한다. 초기 세팅
단계라 자연스러운 상태지만, "Frontend test 통과"가 실제보다 많은 것을 보장하는 것처럼
읽힌다.

`oxlint`는 이미 설치되어 있는데 CI가 호출하지 않는다. **`npm run lint` 한 줄 추가는
지금 해도 된다.**

### 2-5. 정리

- `docs/infra/2026-08-27-infra-deployment-plan.md`의 리스크 항목("Flyway/Liquibase 등
  마이그레이션을 P2/P6 전에 확정")이 해소되었다. 리스크 레지스터로 계속 쓴다면 갱신한다.
- 로컬 `.env.wsl`에 `AES_SYMMETRIC_KEY`·`AES_SALT`가 없다. 없으면 backend가 기동하지
  않는다.

---

## 3. 지금 하지 말 것

**CDC 전제조건과 커넥터 등록을 자동화하지 않는다.** 유혹적이지만 한 번도 성공한 적 없는
절차를 자동화하면 실패 모드만 늘어난다. `CREATE ROLE`이 비멱등이라 조건 검사가 필요하고,
그러면 배포 스크립트가 비밀번호를 다루게 된다.

수동으로 한 번 끝까지 성공시켜 **어느 단계가 어떻게 실패하는지 데이터를 얻은 뒤에**
자동화한다. 같은 이유로 당분간 배포 스크립트에 기능을 더하지 않는다.
