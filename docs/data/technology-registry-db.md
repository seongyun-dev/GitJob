# Technology Registry DB 운영 계약

> 상태: S15P21E102-199 로컬 구현·검증, 운영 미반영 / 기준일: 2026-09-10

## 버전 경계

`technology-registry/v1`은 JSON/DB 구조의 호환성 family token이다. 실제 판정
내용은 `registry-YYYYMMDD.N`으로 식별하고, 같은 content version의 의미를 바꾸지
않는다. `technology_registry.content_sha256`은 검증된 Pydantic snapshot을 key 정렬,
공백 없는 UTF-8 JSON으로 직렬화한 SHA-256이다.

!46 통합 후 신규 B 분석 요청은 `CurrentRegistryVersion`이 조회한 DB의 `CURRENT`
버전을 이벤트 `registry_version`에 고정한다. C import용 alias를 B 요청의 기준으로
바꾸지 않는다. C는 `technology-registry/v1`을 `technology_registry_alias`의 검증된
snapshot으로 해석한다. 두 경로 모두 날짜/문자열 최댓값을 추측하지 않으며 이미
발행한 이벤트나 저장 결과의 concrete version은 바꾸지 않는다.

이 둘은 같은 public 테이블을 사용하지만 승인 대상은 다르다. B 발행에는 Evidence
규칙이 포함되고, C import에는 기술·매핑·provenance와 canonical hash가 포함된다.
이번 충돌 해결은 두 경로의 공존을 보장하며, 서로 다른 내용을 같은 버전으로
덮어쓰거나 B 시드에 C의 provenance/hash를 만들어 넣지 않는다. B→C 계산을 연결할
때 동일 버전과 기술 범위가 실제로 호환되는지 별도로 인수해야 한다.

## 저장 구조와 무결성

- `technology_registry`: snapshot의 schema/content version, canonical SHA-256,
  import source, import 시각
- `technology`: `(registry_version, tech_id)` 복합 키, 표시명, 상태, 항목 provenance
- `technology_category`: snapshot별 기술 도메인과 원본 순서
- `technology_mapping`: snapshot별 alias/package/import/tag/language mapping,
  정규화 충돌 키, 원본 순서, mapping provenance
- `technology_registry_alias`: C import용 schema family별 활성 snapshot pointer.
  B의 DRAFT/CURRENT/RETIRED 수명 주기를 대체하지 않는다.

Flyway V1~V10은 develop 원본을 유지하고 `V11__c_registry_snapshot_metadata.sql`이
C 메타데이터만 추가한다. V4가 만든 복합키·자동 채번·FK를 재정의하지 않는다.
Hash가 없는 B 시드는 그대로 보존하며 C import로 자동 승인하지 않는다.
새 C snapshot은 header와 모든
child row를 한 transaction으로 넣고,
동일 content version의 hash 또는 import source가 다르면 import를 거절한다. Read는
모든 row를 Registry contract로 다시 검증하고 기록된 hash와 다르면 실패한다.

## Import와 활성화

자동 C startup seed는 없다. 승인된 snapshot을 운영자가 명시적으로 import한다.
완성된 C-only snapshot은 B 신규 분석 대상으로 승격하지 않도록 `RETIRED`로 저장한다.
B 관리자 작업 중인 `DRAFT`로도 취급하지 않는다. C alias 활성화는 B의 `CURRENT`를
변경하지 않는다. 기존 B 버전과 같은 이름의 다른 snapshot은 import할 수 없으므로
승인된 별도 concrete version을 사용한다.
운영 기본 승인본은 B seed와 버전명이 겹치지 않는
`AI/registry/data/technology_registry_20260911_1.json`(`registry-20260911.1`)이다.
기존 `registry-20260908.1` 파일은 B seed와 같은 이름이므로 운영 C import에 사용하지
않는다. 아래 helper는 Worker 컨테이너 안에서 접속 정보를 조립하므로 비밀번호를 호스트
명령행이나 로그에 노출하지 않으며, 동일 내용 재실행은 안전하다.

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data \
  ./Infra/scripts/c-compute-migrate.sh

ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data \
  ./Infra/scripts/c-registry-import.sh

ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data VERIFY_TIMEOUT_SECONDS=60 \
  ./Infra/scripts/verify-deployment.sh
```

Registry helper는 import와 alias 활성화 후 Worker를 재시작한다. 모든 release migration을
적용한 뒤 마지막 명령으로 readiness를 확인한다.

`--activate-alias`를 생략하면 immutable snapshot만 추가되고 현재 family pointer는
움직이지 않는다. 활성화 전에는 대상 JSON의 repository-local provenance가 현재
checkout에서 검증되어야 한다. Import 결과의 `registry_version`, `content_sha256`,
`source_ref`, `imported_at`을 배포 기록에 남긴다.

현재 alias 활성화는 이전 pointer 값을 비교하는 CAS가 아니다. 같은 family를 동시에
활성화하면 alias 행의 UPSERT가 직렬화되어 마지막 commit의 버전이 남는다. 각 호출의
성공은 이후 다른 운영자가 alias를 바꾸지 않는다는 보장이 아니다. 불변 snapshot과
이미 고정된 Worker/이벤트 버전은 바뀌지 않는다. MVP 전환은 한 운영자가 승인 버전
하나를 적용하고 아래 단계의 실제 version/hash를 확인하는 범위다. 여러 관리자의
동시 활성화 승인·충돌 거절은 현재 지원 계약에 포함하지 않는다.

## B/C 전환 순서

C DB mode는 시작할 때 family token을 concrete version으로 해석하고 그 process
수명 동안 snapshot을 고정한다. Alias 변경은 live hot reload가 아니다. 새 snapshot
import와 alias 활성화 뒤 C를 재기동하고 readiness의 version/hash를 확인한다.
B는 별도 CURRENT 수명 주기를 유지한다. 두 결과를 연결할 때는 버전 호환을 먼저
확인해야 하며, C alias를 옮겼다는 이유로 B도 바뀌었다고 가정하지 않는다. 기존 요청과 retry는
계속 원래 concrete version을 사용하므로 해당 snapshot row를 보존한다.

### 기존 family-only 요청의 전환 점검

위의 불변 버전 고정은 **새 B 코드로 생성한 요청부터** 적용된다. 과거 Outbox에
`payload.registry_version=technology-registry/v1`만 저장된 요청은 원 내용 버전을
알 수 없으므로 현재 활성 버전으로 자동 backfill하지 않는다. 전환 전 미완료 analysis와
연결된 Outbox payload를 읽어 이런 요청이 있는지 확인한다. `PUBLISHED`여도 소비가
완료되었다는 뜻은 아니므로 Outbox 상태만으로 drain 완료를 판단하지 않는다.

해당 요청이 남으면 당시 Worker/Registry로 완료시키거나 별도 오류/재요청 절차를
정한 후 전환한다. 기존 event JSON을 수정하거나 동일 event ID에 새 버전을 넣어
재전송하지 않는다. 이 변경은 운영 데이터의 소급 정리나 Replay를 실행하지 않는다.

DB 연결 실패, 활성 alias 부재, snapshot 부재, contract 위반, hash 불일치는 모두
운영 불가 상태다. DB mode에서는 bundled JSON으로 자동 fallback하지 않는다.

### 시작 오류와 재시작

C는 시작 시 연결 단절·lock timeout 등 PostgreSQL `OperationalError`만 최대 세 번
시도한다(추가 대기 1초, 2초). 끝내 실패하면 시작을 중단하여 프로세스 재시작 정책이
복구를 시도할 수 있게 한다. 각 DB 연결·쿼리 자체의 기존 timeout은 별도로 적용된다.
로딩에 성공한 뒤에는 같은 프로세스에서 alias를 다시 해석하지 않는다.

승인 snapshot 부재·무결성 오류·migration 부재는 단순 재시도로 고치지 않는다.
`/health`는 계속 liveness만 나타내며 인증된 `/ready`는 `C_REGISTRY_UNAVAILABLE`
503이다. 원인을 고친 뒤 Worker를 재시작해야 한다. B/C 로그는 오류 종류를 남기되
DB 연결 문자열·SQL 예외 원문·인증정보는 기록하지 않는다.

### 최초 개통/계산 버전 변경 인수 순서

1. 적용 대상 이미지, DB, 승인 Registry source/version/hash, 보존된 완료 입력 경로를
   확인한다. 과거 미완료 분석/Outbox를 확인하여 이전 버전 작업을 먼저 완료시키거나
   별도 재요청 대상으로 구분한다. 이벤트의 저장된 버전을 수정하지 않는다.
2. 신규 분석 트래픽이 열리지 않은 점검 구간에서 Flyway V1~V11과 해당 이미지가 요구하는
   C Compute migration을 적용한다. V11만으로 C approved alias가 생기지는 않는다.
3. 위의 명시 import/activation을 실행하고 DB snapshot의 version/hash를 확인한다.
   실행 중인 A 수집 컨테이너를 이 절차의 부수 효과로 재시작하지 않는다.
4. C Worker를 새 이미지로 시작한다. 인증된 `GET /ready`와
   `GET /internal/v1/c/registry`의 concrete version/hash를 DB 승인값과 비교한다.
5. 보존된 완료 공고 입력을 새로운 계산 버전/새 event로 처리한다. 자동 intake를
   사용한다면 설정과 완료 입력 mount 및 실제 처리 성공을 확인한다. COHORT/DEMAND가
   저장되고 대상 criteria로 `POST /internal/v1/c/job-cohorts/resolve`가 성공해야 한다.
6. B 신규 요청이 DB CURRENT의 concrete `registry_version`을 저장하는지 확인한다.
   C와 연결할 결과는 호환 버전인지 별도로 확인하며, 다르면 계산을 강제로 통과시키지
   않는다. B 이벤트에 없는 hash 필드를 가정하지 않는다.
7. 완료 전달→C 결과 저장/조회 및 사용자 격리를 확인한 후 신규 분석 트래픽을 연다.

`/ready=200`은 DB/Registry 준비를 뜻하며 모든 직무의 최신 코호트 준비까지 뜻하지는
않는다. 계산 버전이 달라지면 이전 head 대신 `COHORT_NOT_PREPARED`가 나오는 것이
정상이며 5단계를 생략하지 않는다. 과거 저장 결과 조회는 유지되지만 서로 다른
Registry로 만든 입력을 섞은 신규 계산은 거절한다. MVP 인수 동안 승인 버전 하나를
유지하고, 버전 전환 때 위 순서를 반복한다.

기존 `deploy.sh`는 두 호스트 배포 뒤 `verify-deployment.sh`를 호출한다. 이 사후
검사는 migration/import/코호트 재계산을 대신 실행하지 않으며 사용자 트래픽을
자동 차단하지도 않는다. 실패 표시를 무시하고 컨테이너 liveness만으로 개통하지 않는다.

### 병합 전 로컬 V3 실험 DB

!80 단독의 `V3__versioned_technology_registry.sql`을 이미 적용한 로컬 실험 DB는
develop의 V3 시드와 Flyway 이력이 다르다. V11은 그 분기 DB를 자동 repair하지 않는다.
필요한 데이터를 보존한 별도 DB에서 정식 V1~V11 경로를 검증한다. 운영 DB의 migration
이력을 삭제하거나 checksum을 임의 변경하지 않는다.
