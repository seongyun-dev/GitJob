# 저장소 선택과 분석 요청

로그인으로 확보한 GitHub Access Token으로 사용자의 저장소·브랜치를 조회하고,
고른 대상을 분석 요청으로 등록한다 (B-FN-002).

앞단은 [GitHub OAuth 로그인](README.md#인증계정), 뒷단은
[Outbox·CDC 발행](analysis-outbox.md)이다. 이 문서는 그 사이를 다룬다.

## 흐름

```
1. GET  /api/v1/me/repositories                          저장소 목록
2. GET  /api/v1/me/repositories/{owner}/{repo}/branches  브랜치 목록
3. POST /api/v1/analyses                                 분석 요청 → 202 + analysisId
                                                            ↓
                              analysis_job + analysis_outbox (한 트랜잭션)
                                                            ↓
                                        Debezium → Kafka → Worker
```

3번 응답 시점에 Kafka 발행은 아직 일어나지 않았다. 커밋된 Outbox 행을 Debezium이
옮기므로, Kafka가 잠깐 죽어 있어도 요청은 성공한다.

## API

### `GET /api/v1/me/repositories`

| 파라미터 | 기본값 | 설명 |
| --- | --- | --- |
| `page` | 1 | 1부터 |
| `perPage` | 30 | 최대 100. GitHub 상한이라 넘기면 100으로 맞춘다 |

최근 갱신 순으로 정렬한다. GitHub은 전체 개수를 주지 않으므로 총 페이지 수를
만들어 낼 수 없고, 받은 항목 수가 페이지 크기와 같은지로 `hasNext`만 알린다.

```json
{
  "message": "요청이 성공적으로 처리되었습니다.",
  "data": {
    "items": [
      {
        "githubRepositoryId": 987654321,
        "fullName": "octocat/GitJob",
        "name": "GitJob",
        "owner": "octocat",
        "isPrivate": false,
        "defaultBranch": "main",
        "description": "...",
        "language": "Java",
        "updatedAt": "2026-09-08T00:00:00Z",
        "analyzable": true
      }
    ],
    "page": 1, "perPage": 30, "hasNext": true
  }
}
```

`analyzable`이 false면 아카이브·비활성 저장소다. 목록에서 감추지 않고 선택만 막는다.
숨기면 사용자는 자기 저장소가 왜 없는지 알 수 없다.

### `GET /api/v1/me/repositories/{owner}/{repo}/branches`

`perPage` 기본값은 100이다. 브랜치는 보통 한 페이지에 다 들어오고, 화면이 페이지를
넘기게 만들 이유가 없다.

```json
{ "data": { "items": [{ "name": "feature/cdc", "commitSha": "0123...", "isProtected": false }],
            "page": 1, "perPage": 100, "hasNext": false } }
```

응답의 `commitSha`는 표시용이다. 분석 요청 시 서버가 다시 확정한다.

API 카탈로그에 없던 경로다. 브랜치 선택에 반드시 필요해 추가했다.

### `POST /api/v1/analyses`

```json
{ "repositoryFullName": "octocat/GitJob", "branchName": "feature/cdc" }
```

```json
{
  "message": "분석을 등록했습니다.",
  "data": {
    "analysisId": "an_5f3c...",
    "status": "QUEUED",
    "repositoryFullName": "octocat/GitJob",
    "branchName": "feature/cdc",
    "commitSha": "0123456789abcdef0123456789abcdef01234567",
    "pollAfterSec": 2,
    "statusUrl": "/api/v1/analyses/an_5f3c..."
  }
}
```

| 상태 | 의미 |
| --- | --- |
| `202` | 새로 등록했다 |
| `200` | 같은 저장소 분석이 이미 진행 중이라 그 Job을 안내한다 |

본문 형태는 같으므로 화면은 `statusUrl`만 쓰면 된다.

API 명세서 예시는 `{"repoFullNames": [...]}`였으나 브랜치가 없었다. `analysis_job`
스키마가 저장소 하나에 `branch_name`·`commit_sha`를 갖는 단일 저장소 모델이고
브랜치 선택이 이 기능의 요구사항이므로, 저장소 하나 + 브랜치 하나로 정했다.
여러 저장소를 요청하려면 호출을 나눠 각각 별도 `analysisId`를 받는다.

## 클라이언트가 정하지 못하는 것

요청 본문에 담긴 값 중 실제로 쓰는 것은 저장소 이름과 브랜치 이름 **둘뿐**이다.
나머지는 전부 서버가 채운다.

| 값 | 출처 | 클라이언트가 정하면 생기는 일 |
| --- | --- | --- |
| `githubRepositoryId` | GitHub 저장소 응답 | 권한 밖 저장소를 분석시킬 수 있다 |
| `repositoryFullName` | GitHub 저장소 응답(정규 표기) | 이름이 바뀐 저장소의 옛 이름이 이벤트에 남는다 |
| `commitSha` | GitHub 브랜치 응답의 tip | 임의의 commit을 분석시킬 수 있다 |
| `analysisId`·`analysisRepositoryId` | 서버 생성 UUID | 남의 분석 ID를 덮어쓸 수 있다 |
| `registryVersion` | `technology_registry`의 `CURRENT` 행 | 판정 기준을 골라 결과를 왜곡할 수 있다 |

저장소 접근 권한은 별도로 확인하지 않는다. `GET /repos/{owner}/{repo}` **호출의
성공 자체가 권한의 증거**다. GitHub은 권한 없는 저장소에도 404를 주기 때문에,
우리가 권한 없음과 없는 저장소를 구분해 응답하면 비공개 저장소의 존재 여부가
새어 나간다. 그래서 둘 다 `REPO-404-1`로 응답한다.

`analysisRepositoryId`는 요청마다 새로 만든다. 이 값이 Kafka 키이자 Worker가 자격 증명을
교환할 때 쓰는 손잡이라, 재사용하면 두 분석이 같은 것으로 취급된다.

## 중복 요청

같은 사용자에게 같은 저장소 분석이 진행 중이면 새 Job을 만들지 않고 진행 중인
Job을 200으로 안내한다. "진행 중"의 기준은 `AnalysisJob.IN_PROGRESS_STATUSES`다.
API 명세에 두 벌의 상태 어휘가 섞여 있어 양쪽을 모두 넣어 뒀다. 하나의 enum으로
통일하는 것은 별도 항목이며, 그때 이 집합도 함께 좁힌다.

검사와 저장은 별개의 문장이라 동시에 들어온 두 요청이 둘 다 검사를 통과할 수 있다.
그 경합을 실제로 판정하는 것은 애플리케이션이 아니라 부분 UNIQUE 인덱스다.

```sql
CREATE UNIQUE INDEX uq_analysis_job_active
    ON analysis_job (user_id, repository_id)
    WHERE status IN ('QUEUED', ...);
```

진 요청은 제약 위반을 받고, 이긴 Job을 찾아 200으로 돌려준다. **이때 이긴 행은 반드시
보인다.** PostgreSQL의 UNIQUE 인덱스는 상대 트랜잭션이 열려 있는 동안 오류를 내지 않고
대기하므로, 위반이 도착했다는 것은 상대가 이미 커밋했다는 뜻이다.

재조회에서 아무것도 못 찾으면 원래 예외를 그대로 던진다. 다른 제약 위반을 "기존 Job을
재사용했다"는 답으로 감추지 않기 위해서다.

인덱스의 상태 목록은 `AnalysisJob.IN_PROGRESS_STATUSES`와 중복이며, 어긋나면
`DatabaseScriptConsistencyTest`가 빌드를 깨뜨린다.

## 오류

| 코드 | HTTP | 상황 |
| --- | --- | --- |
| `G-400-1` | 400 | `owner/repo` 형식 오류, 위험한 브랜치 이름 |
| `AUTH-401-4` | 401 | GitHub 토큰 폐기·연결 해제. 재로그인 외 회복 경로 없음 |
| `REPO-403-1` | 403 | GitHub이 403을 준 경우(권한 부족) |
| `REPO-409-1` | 409 | 보관·비활성 저장소. 권한 문제가 아니므로 403과 구분한다 |
| `REPO-404-1` | 404 | 저장소가 없거나 접근 권한이 없음(구분하지 않음) |
| `REPO-404-2` | 404 | 브랜치 없음 |
| `REPO-429-1` | 429 | GitHub API 한도 초과 |
| `REPO-503-1` | 503 | GitHub 연결 실패·5xx |

GitHub은 한도 초과와 권한 부족을 **둘 다 403**으로 응답한다. `x-ratelimit-remaining`이
0일 때만 한도 초과다. 이를 뭉뚱그리면 사용자에게 "잠시 후 재시도"와 "권한 없음" 중
잘못된 안내를 하게 된다.

## 입력 검증이 보안 경계인 이유

`owner`, `repository`, `branchName`은 그대로 GitHub URL의 경로가 된다.
`RepositoryCoordinate`가 GitHub을 호출하기 **전에** 형식을 좁힌다.

- `..`를 허용하면 `/repos/o/r/branches/../../user/repos`처럼 다른 엔드포인트로
  빠져나갈 수 있다. 인코딩만으로는 부족해서 형식 자체를 막는다.
- 브랜치 이름은 `feature/cdc`처럼 슬래시를 포함할 수 있어 owner/repo보다 넓게 받는다.
  대신 Git이 금지하는 문자(공백, 제어문자, `~^:?*[\#`)와 슬래시로 시작·끝나는 형태를
  거절한다. 제어문자를 막는 것은 URL과 로그에 개행을 심는 것을 방지하기 위해서다.
- 슬래시는 인코딩하지 않고 경로 구분자로 남긴다. `%2F`로 보내면 GitHub이 404를 준다.

## 인덱스

| 인덱스 | 역할 |
| --- | --- |
| `uq_analysis_job_active` | 진행 중 (사용자, 저장소) 중복 차단 |
| `idx_analysis_job_user_repository` | 중복 검사 조회. 위 부분 인덱스는 이 쿼리에 쓰이지 않는다 |
| `idx_analysis_outbox_analysis_id` | FK 자식 컬럼. PostgreSQL은 자동으로 만들지 않는다 |

부분 인덱스가 조회를 못 받쳐 주는 이유는 쿼리가 상태 목록을 바인드 파라미터로 넘기기
때문이다. 플래너는 `status IN (?,?,?)`가 인덱스 조건과 같다고 증명하지 못해 순차 스캔으로
떨어진다. 그래서 일반 인덱스가 따로 필요하다.

## 설정

| 키 | 환경변수 | 기본값 |
| --- | --- | --- |
| `gitjob.analysis.request.poll-after-seconds` | `ANALYSIS_POLL_AFTER_SECONDS` | `2` |

Registry 버전 환경변수는 사용하지 않는다. `CurrentRegistryVersion`이 DB의 CURRENT
버전을 조회하고 Outbox에 고정한다. C snapshot import용 alias와는 별도 승인 경로다.

## 검증

```powershell
.\gradlew.bat test --tests 'com.example.git_job.analysis.*'
```

`GithubRepositoryClientTest`는 JDK `HttpServer`로 GitHub을 흉내 낸다. 네트워크도
토큰도 필요 없고, 403 두 종류 구분·404 자원별 구분·슬래시 브랜치 경로를 검증한다.
`AnalysisSubmissionServiceTest`는 "클라이언트가 보낸 값으로 무엇을 하지 않는가"를
검증한다. `RepositoryCoordinateTest`는 경로 탈출과 금지 문자를 막는지 본다.

## 아직 하지 않은 것

- **CSRF.** `SecurityConfig`는 CSRF를 끈 채로 두면서 "상태를 바꾸는 POST가 들어오면
  활성화해야 한다"고 적어 두었고, `POST /api/v1/analyses`가 그 첫 사례다. 세션 쿠키가
  `SameSite=Lax`라 브라우저가 cross-site POST에 쿠키를 싣지 않아 실질 위험은 낮지만,
  이 항목은 남아 있다. 활성화하면 FE가 `X-XSRF-TOKEN`을 보내야 하므로 계약 변경이다.
- **Access Token 평문 저장.** `User.accessToken`은 아직 평문이다(별도 티켓).
  이 기능이 그 토큰을 읽는 첫 소비자이므로 암호화 적용 시 `GithubAccessTokenProvider`
  한 곳만 고치면 되도록 통로를 좁혀 두었다.
- **분석 상태 조회** `GET /api/v1/analyses/{analysisId}`. 응답의 `statusUrl`이
  가리키는 경로이며 구현되었다. 응답과 현재 범위는 [분석 진행 상태 조회](analysis-status.md)를 참고한다.
- **저장소 선택 저장** `GET`/`PUT /api/v1/me/repositories/selection`.
