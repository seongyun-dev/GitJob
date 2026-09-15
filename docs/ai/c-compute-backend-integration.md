# B ↔ C Compute 연결 인수

> 2026-09-15 운영 기준: Jira `S15P21E102-269` 병합·C Worker 배포 완료,
> `S15P21E102-272`로 JobKorea C 분석 소비 적용
> 아직 하지 않은 것: 실제 B callback과 로그인 FE E2E

C는 공고 모집단·수요·매칭·추천·What-if·Trend를 계산한다. B는 로그인 사용자의
소유권을 확인하고 C 내부 API를 호출한 뒤 FE DTO로 변환한다. B나 FE가 C 계산을 다시
구현하거나 C DB를 직접 읽지 않는다.

원본 계약은 [C 계산 실행·저장 계약](c-compute-runtime.md)이다. 이 문서는 B가 실제로
연결할 순서와 운영 인수 조건만 요약한다.

## 1. 현재 확인된 운영 상태

2026-09-15 읽기 전용 실사 결과는 다음과 같다.

- 데이터 서버의 C Worker 8080은 Tailscale 주소에만 게시되며 서비스 서버에서
  `/health=200`으로 접근된다.
- 서비스 서버 `.env.service`에는 `C_COMPUTE_URL`이 아직 없다. token 값은 두 호스트에
  설정되어 있지만 값 자체를 문서나 로그에 남기지 않는다.
- 운영 Worker와 DB alias는 승인된 `registry-20260911.4` 44개와 Rule Pack
  44개/145규칙을 사용한다.
- 공고 자동 intake는 Worknet·Saramin·Career·GameJob·JobKorea를 읽는다. JobKorea는
  `S15P21E102-272` 소유자 결정에 따라 2026-09-15부터 C 분석 입력에 포함한다.
- 월별 Repo Snapshot은 6~8월만 완료 marker까지 확인됐다. 5월은 Artifact만 있고 완료
  marker가 없어 소비하면 안 된다.

따라서 C 운영 URL과 계산 결과는 준비됐고, B callback과 로그인 사용자 E2E가 남았다.

## 2. 운영 연결 전 C 체크리스트

1. `S15P21E102-269` 변경을 검토·병합한 뒤 데이터 서버를 최신 develop로 배포한다.
2. `compose.ec2-data-cluster.yaml`의 Worker 8080을 데이터 서버 Tailscale 주소에만 게시한다.
   공인망이나 `0.0.0.0`에 열지 않는다.
3. 기존 Registry import 절차로 `.4`를 import·activate하고 Worker를 재시작한다.
4. 서비스 서버에서 인증 포함 `/ready`, `/registry`, `/contracts`, `/intake/status`를 호출한다.
5. `/ready`와 `/registry`가 승인된 `.4` version/hash를 반환하는지 확인한다.
6. B 서버 설정에 `C_COMPUTE_URL=http://100.70.66.38:8080`과 동일한
   `C_COMPUTE_TOKEN`을 전달한다. 현재 base Compose의 backend environment에는 두 변수가
   아직 없으므로 B 구현에서 명시적으로 전달한다. token은 브라우저에 전달하지 않는다.

서비스 서버의 nginx 파일에는 별도 도메인·인증서 미커밋 변경이 있다. C 배포를 이유로
reset하거나 덮어쓰지 않는다.

## 3. B가 호출할 순서

### 3.1 공고 모집단과 수요 선택

B는 사용자가 선택한 직무·지역·경력 조건으로 아래 endpoint를 호출한다.

```http
POST /internal/v1/c/job-cohorts/resolve
Authorization: Bearer <server-only token>
Content-Type: application/json
```

```json
{
  "schema_version": "job-cohort-resolve-selector/v1",
  "target_role": "BACKEND",
  "regions": ["서울"],
  "career_levels": ["신입"]
}
```

C는 마지막으로 검증된 A 입력 중 선택한 source의 완료 시각을 `as_of`로 고정하고, 같은
입력·조건이면 기존 계산을 재사용한다. 응답의 COHORT와 DEMAND는 같은 event/stream에서
저장된 쌍이다.

```json
{
  "data": {
    "cohort_snapshot_id": "c-...",
    "demand_snapshot_id": "c-...",
    "criteria": {
      "target_role": "BACKEND_ENGINEER",
      "as_of": "2026-09-15T01:30:00Z",
      "regions": ["서울"],
      "career_levels": ["신입"]
    },
    "compute_versions": {}
  }
}
```

- 200: 두 Snapshot 준비 완료
- 202 `PREPARING`: 같은 selector로 재시도하며 `Retry-After`를 따른다
- 404 `COHORT_NOT_PREPARED`: Worker 첫 정상 poll 전이거나 현재 입력이 차단됨
- 422 `INVALID_INPUT`: 지원하지 않는 직무·필터 형식
- 503: DB·Registry·C 런타임 일시 장애

지역·경력 필터를 B에서 목록만 잘라내는 방식으로 처리하면 추천 수치와 공고 목록의 분모가
달라진다. 필터가 바뀔 때마다 이 endpoint로 같은 조건의 COHORT·DEMAND를 받아야 한다.

### 3.2 사용자 분석 완료 전달

GitHub 사용자 분석이 최종 성공 또는 계약상 허용된 부분 성공 상태가 되면 B가
`POST /internal/v1/c/analyses/completed`를 호출한다.

- `event_id`는 `userId + analysisId + cohortSnapshotId + Evidence version`에서 B가 한 번
  만들고 재시도에도 같은 값을 쓴다.
- `user_id`는 브라우저 입력이 아니라 로그인 사용자에서 정한다.
- `cohort_snapshot_id`는 바로 앞 resolve 응답을 쓴다.
- Evidence v4의 개인 종합은 top-level `personal_assessments`에 둔다.
- repository 기술마다 `personal_level`을 중복해서 넣지 않는다.
- `assessment_ceiling`, `attribution_status`, `missing_scope`를 보존한다.

정확한 필드와 enum은 운영 C의 `GET /internal/v1/c/contracts`에서 생성된 schema를 사용한다.

완료 응답의 `results`에서 `kind=RECOMMENDATION`인 `snapshot_id`를
`userId + analysisId + cohortSnapshotId`에 저장한다. B 재시작이나 같은 완료 이벤트 재전달로
중복 계산을 만들지 않는다.

### 3.3 개인 결과 조회

B는 저장한 RECOMMENDATION Snapshot ID와 인증한 사용자 ID로 다음 C API를 호출한다.

- `GET /internal/v1/c/snapshots/{snapshotId}?user_id={authenticatedUserId}`
- `GET /internal/v1/c/recommendations/{snapshotId}/job-postings`
- `GET /internal/v1/c/recommendations/{snapshotId}/matching-job-postings`
- `GET /internal/v1/c/recommendations/{snapshotId}/matching-job-posting`

다른 사용자의 개인 Snapshot은 존재 여부를 노출하지 않도록 404로 처리한다. B는 C의 추천
점수, 충족 여부, Skill Gap, What-if 증가 수를 재계산하지 않는다.

### 3.4 공용 Trend 선택

```http
POST /internal/v1/c/trends/resolve
Authorization: Bearer <server-only token>
```

주간 증분 Trend:

```json
{"source":"WEEKLY_REPO_ACTIVITY","tech_id":"python","include_partial":false}
```

고정 월별 historical Trend:

```json
{
  "source":"GH_ARCHIVE_HISTORICAL",
  "tech_id":"react",
  "periods":["2026-06","2026-07","2026-08"],
  "granularity":"MONTH",
  "include_partial":false
}
```

세 source `WEEKLY_REPO_ACTIVITY`, `GH_ARCHIVE`, `GH_ARCHIVE_HISTORICAL`은 서로 다른
series다. B/FE가 하나의 합성 점수로 섞지 않는다. resolve 응답의 `snapshot_id`로 기존
snapshot 조회 API를 호출한다. 미완료 월을 0으로 채우지 않는다.

## 4. B·FE 공개 API 경계

B가 제공할 공개 API의 URI와 DTO는 FE조와 고정하되 역할은 다음으로 제한한다.

- 로그인·소유권 확인
- 사용자별 최신 analysis/cohort/recommendation 선택
- C 응답을 FE DTO로 변환
- 페이징과 C 오류를 분석 전·계산 중·데이터 부족·일시 장애로 변환

FE는 C token이나 C Snapshot ID를 임의로 만들지 않는다. Fixture는 운영 빌드에서 제거하고,
`UNKNOWN`·부분 분석·미해석 요구를 기술 미보유로 표시하지 않는다.

## 5. 공동 완료 기준

아래가 실제 로그인 사용자 한 명으로 이어져야 완료다.

```text
GitHub 로그인
→ 저장소 선택·분석
→ Evidence와 personalLevel 생성
→ B가 공고 selector resolve
→ B가 analyses/completed 호출
→ C가 매칭·Gap·추천·What-if 저장
→ B 공개 API 조회
→ FE 실제 화면 표시
```

추가로 다음을 확인한다.

- 매칭 건수와 목록이 같은 COHORT를 사용함
- What-if 증가 건수와 신규 부합 공고 목록이 일치함
- 다른 사용자 Snapshot을 읽을 수 없음
- 같은 event 재전달과 Worker 재시작 후 중복 Snapshot이 생기지 않음
- 공고·Trend 입력 부족을 0이나 기술 미사용으로 바꾸지 않음
- C 장애를 무조건 500으로 뭉개지 않고 202·404·409·422·503 의미를 보존함

이 문서의 코드 계약 완료는 운영 배포나 로그인 FE E2E 완료를 뜻하지 않는다.
