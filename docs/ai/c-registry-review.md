# C Registry 검토 큐

> 상태: 로컬 구현·PostgreSQL/HTTP 검증, 운영 미반영 / 기준일: 2026-09-10

S15P21E102-88은 채용 공고 분류 중 Registry 결과가 `UNKNOWN` 또는
`AMBIGUOUS`인 기술 언급을 C Compute PostgreSQL에 저장한다. 코호트·수요 계산이
성공하는 트랜잭션 안에서 함께 저장하므로 결과 snapshot만 남거나 검토 원문만 남는
부분 완료가 발생하지 않는다.

## 입력과 저장 결과

`build_records(classified, attempted_at=None)`는 검증된
`JobClassificationBatch`에서 미해결 언급만 `ReviewRecord`로 만든다. 파일이나 DB를
변경하지 않으며, 시도 시각은 기본적으로 각 원본의 `collected_at`을 사용한다. 이벤트
처리기는 검증된 `occurred_at`을 명시할 수 있다.

`c-registry-review-queue/v3`는 Compute 결과의 처리 정책 version token이고,
`registry-review-queue/v3`는 파일 snapshot serialization schema다. 두 값은 용도가
다르므로 서로 같게 맞추거나 한쪽 변경만으로 다른 쪽을 갱신하지 않는다.

신규 `registry-review-queue/v3` 항목의 review ID는 DB `source_hash`와 같은 불변 원문
payload의 SHA-256 앞 24자를 사용한다. 따라서 원천 사이트뿐 아니라 URL·문맥·근거
section/text·surface·mention index·문자 위치가 실제로 다른 원문 변형은 별도 검토
항목이 되고, 완전히 같은 원문 재전달은 같은 항목을 가리킨다. 기존 v1/v2 파일
snapshot은 저장된 review ID를 다시 계산하지 않고 그대로 읽으며, 같은 원문을
재수집하면 겹치는 원문 필드와 사이트를 확인한 뒤 기존 결정 이력을 재사용한다. 우연히
같은 legacy ID라도 원문이나 사이트가 다르면 v3 ID의 별도 항목으로 보존한다.

각 레코드는 다음 근거를 보존한다.

- 길이를 자르지 않는 `source_dataset_snapshot_id`, 원본 record/site/URL, surface와
  mention index, Python 문자열 기준 `[char_start, char_end)` 위치
- 원문 기술명, 문맥, evidence section/text, 최초 match 상태와 후보
- Registry version, mapping 순서·결과·근거가 포함된 attempt 이력

`insert_reviews(conn, records, cohort_snapshot_id)`는 호출자가 연 PostgreSQL
트랜잭션을 그대로 사용한다. 동일 review ID의 원본 근거가 같으면 큐 행을 중복하지
않고 코호트 참조만 추가한다. 원본 근거가 다르면 멱등 충돌로 처리한다. 같은 입력이
여러 코호트에 사용돼도 `registry_review_cohort`에 모든 참조가 남으며, 기존 수동 결정과
attempt 이력은 계산 재전달로 덮어쓰지 않는다. v3 입력이 동일한 기존 v2/site-aware
또는 v1/site-less ID를 찾으면 겹치는 원문 필드를 확인한 뒤 기존 행과 결정 이력에
코호트 참조만 연결한다. ID가 우연히 같아도 원문이 다르면 기존 행을 덮어쓰지 않고
v3 ID로 별도 보존한다. 여러 건은 일괄 삽입·검증하지만 이 과정도 결과 snapshot과
같은 caller transaction 안에서 완료된다.

## 조회와 결정

`query_reviews`는 status와 review ID cursor로 최대 100건을 조회한다. 반환 항목에는
현재 `version`과 연결된 모든 `cohort_snapshot_ids`가 포함된다. `get_review`는 단건을
조회하고 없는 ID를 명시적으로 구분한다.

서비스 토큰으로 보호되는 내부 경로는 다음과 같다.

- `GET /internal/v1/c/registry/reviews`
- `GET /internal/v1/c/registry/reviews/{review_id}`
- `POST /internal/v1/c/registry/reviews/{review_id}/resolve`
- `POST /internal/v1/c/registry/reviews/{review_id}/reprocess`

수동 결정과 재처리는 모두 review 행을 `FOR UPDATE`로 잠근 뒤
`expected_version`을 검사한다. `(review_id, idempotency_key)`가 같은 재시도는 한 번만
반영하며, 같은 key의 요청 내용이 바뀌면 충돌한다. 성공한 변경은 version을 1 올리고
actor, note, Registry version, 변경 전후 version을 `registry_review_action`에 남긴다.

- `resolve_review`: 전달된 `RegistryMapper`에서 ACTIVE인 기존 `tech_id`만 수동 결정한다.
  최신 `expected_version`과 새 idempotency key를 사용하면 이미 `RESOLVED`인 수동
  결정을 교정할 수 있다. 이전과 새 결정은 attempt/action 이력에 모두 남으며, stale
  version은 충돌한다.
- `reprocess_review`: `PENDING` 한 건을 전달된 승인 Registry로 다시 매핑한다. 결과가
  `MATCHED`이면 자동으로 `RESOLVED`, 아니면 새 attempt를 남기고 `PENDING`을 유지한다.

Alias 승인과 신규 기술 생성은 B-142의 Registry 변경 절차다. 이 큐의 결정은 Registry
자체를 변경하지 않으며, 내부 API의 관리자 인증·권한 판정은 B 서비스가 담당한다.

`actor`는 B가 인증한 관리자 식별자다. 브라우저가 직접 보내는 인증 수단이 아니며,
두 POST는 `actor`, `note`, `idempotency_key`, `expected_version`을 요구한다.
resolve만 `tech_id`를 추가한다. 없는 review는 404, stale version·멱등 충돌·잘못된
상태 전이는 409, 입력 오류는 422, DB 미준비는 503이다.

검토 결정이 이미 저장된 COHORT·추천 숫자를 소급 변경하지는 않는다. Registry alias가
승인된 새 불변 버전으로 발행된 뒤, 선택한 완료 입력을 새 계산 버전/새 event로 재처리하고
새 cohort에서 추천을 계산한다. 원 snapshot과 원문은 그대로 보존한다. 일반 분석 완료
후 추천 자동 실행에는 이 관리자 검토를 매번 요구하지 않는다.

## DB 구조

- `c_compute.registry_review`: 현재 레코드, 상태, source hash, optimistic version.
  `004_registry_review_source_identity.sql`부터 원천 계약의 길이 제한 없는
  `source_dataset_snapshot_id`를 `text`로 보존한다.
- `c_compute.registry_review_cohort`: review와 COHORT snapshot의 다대다 참조
- `c_compute.registry_review_action`: 수동 결정·명시적 재처리의 멱등/audit 정보

기본 DDL은 `003_registry_review.sql`, 길이 정합성 후속 DDL은
`004_registry_review_source_identity.sql`이며 C Compute migration 명령으로 순서대로
명시 적용한다. 이미 적용된 003 checksum을 바꾸지 않는다.
DB 통합 회귀는 격리 PostgreSQL을 지정한 뒤 `AI/tests/test_review_queue_db.py`로 확인한다.
