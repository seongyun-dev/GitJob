# 분석 진행 상태 조회 (B-FN-005 / S15P21E102-133)

`GET /api/v1/analyses/{analysisId}?includeRepositories=true`

인증된 사용자 본인의 분석 상태를 읽는다. 조회는 분석을 등록하거나 외부 API를 호출하지 않는다.
성공 응답은 기존 `message`, `data` 봉투를 사용한다.

- `analysisStatus`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `PARTIAL_SUCCEEDED`, `FAILED`.
  기존 `RATE_LIMITED`, `CANCELED`도 보존한다.
- `COLLECTING`/`ANALYZING`/`CANCEL_REQUESTED`는 `RUNNING`, `COMPLETED`는 `SUCCEEDED`,
  `PARTIAL`은 `PARTIAL_SUCCEEDED`, `CANCELLED`는 `CANCELED`로 정규화한다.
- `currentStage`: DB에 기록된 현재 단계. `stages`는 기록이 있는 현재 단계 하나만 담는다.
- `totalCount`: 현재 생성 모델은 분석 ID 하나당 저장소 하나이므로 1.
- `completedCount`: 종료한 처리 대상 수. 성공/부분완료/실패/취소 모두 종료이므로 1, 그 외 0.
- `progressPercent`: 완료 처리 대상 비율(0 또는 100). 성공률이 아니며 시간으로 추정하지 않는다.
- `requestedAt`, `startedAt`, `finishedAt`: 저장된 시각. 미기록 시각은 null.
- `pollAfterSeconds`: 진행 중 5, 종료 시 null.
- `errorCode`: 기록된 실패 코드, 없으면 null.
- `repositories`: repositoryId, branchName, commitSha, status, errorCode.
  `includeRepositories=false`이면 빈 배열.

오류: 미인증 401 (`AUTH-401-1`), 타인 소유 403 (`AUTH-403-1`),
분석 없음 404 (`AN-404-1`), 잘못된 boolean 파라미터 400 (`G-400-2`).

## 현재 데이터 모델의 범위

Notion 명세의 다중 저장소 집계는 현재 단일 저장소 요청 모델에 맞춰 축소했다.
저장되지 않은 단계 이력, 파일 처리 수, 기술 수, 버전 정보는 추정하여 채우지 않는다.
현재 worker 결과 이벤트는 COMPLETED/FAILED만 전달한다. 따라서 새 작업은 중간 상태 전달을
추가하기 전까지 QUEUED에서 SUCCEEDED/FAILED로 바뀐다. RUNNING과 PARTIAL_SUCCEEDED는
해당 상태가 DB에 기록되어 있을 때 조회할 수 있다. 이 API 자체가 작업 상태를 변경하지 않는다.
실시간 단계 갱신 및 다중 저장소의 부분완료 집계는 worker 이벤트/저장 모델 확장이 필요하다.

## 진행 중인 묶음 조회 (S15P21E102-136)

`GET /api/v1/me/analyses/latest-batch`

저장소 선택 화면이 폴링하는 **단 하나의** 조회다. 분석마다 따로 묻지 않는다 —
저장소 넷을 고르면 폴링도 넷이 되고, 그 넷이 저마다 다른 순간의 상태를 들고 있어
화면이 "몇 개가 끝났는지"를 말할 수 없다.

```json
{ "message": "요청이 성공적으로 처리되었습니다.",
  "data": {
    "canSubmit": false,
    "batch": {
      "batchId": "ab_9a1c...", "requestedAt": "2026-09-20T00:00:00Z",
      "totalCount": 4, "completedCount": 2, "failedCount": 0,
      "pollAfterSeconds": 5,
      "items": [{
        "analysisId": "an_5f3c...", "repositoryId": "987654321",
        "repositoryFullName": "octocat/GitJob", "branchName": "main",
        "commitSha": "0123...", "analysisStatus": "RUNNING",
        "currentStage": "ANALYZING_REPOSITORY",
        "requestedAt": "2026-09-20T00:00:00Z", "errorCode": null }]
    } } }
```

**`/active`라고 부르지 않는다.** 끝난 묶음도 잠시 돌려주므로 이름이 사실과 어긋나고,
화면이 영원히 폴링해야 할 대상처럼 읽힌다.

**`maxBatchSize`도 함께 내려간다.** 한 번에 고를 수 있는 저장소 수를 화면이 지어내지
않게 하려는 것이다. 상한을 넘겨 제출하면 `AN-400-1`로 거절한다.

**`canSubmit`은 `batch` 안이 아니라 밖이다.** 제출 차단은 사용자 단위이고 배치 단위가
아니다. V27 이전에 만들어진 분석은 `batch_id`가 없어 어떤 묶음에도 속하지 않지만,
진행 중이면 저장소를 점유하고 제출을 막는다. 이 값을 배치 안에 두면 그런 사용자가
"제출 가능"을 보고 눌렀다가 409를 맞는다. `POST`의 게이트와 **같은 질문**이어야 한다.

묶음을 한 번도 만들지 않았거나 마지막 묶음이 보여 줄 기간
(`completed-batch-visible-for`, 기본 30분)을 지났으면 `batch`가 `null`이고 상태는
**200**이다. 404가 아닌 이유는 화면의 HTTP 클라이언트가 404에서 예외를 던져,
분석을 한 번도 해 본 적 없는 사용자 전원에게 오류 패널이 뜨기 때문이다.

`completedCount`·`canSubmit`·`pollAfterSeconds`는 모두
`AnalysisJob.IN_PROGRESS_STATUSES` 하나로 판정한다. `normalize()`도 종료를 판정할 수
있지만 두 목록은 따로 관리되고, 애초에 `normalize`가 존재하는 이유가 "워커가 BE 모르는
값을 쓸 수 있다"는 것이다. 두 술어를 섞으면 "2/4"와 차단 규칙이 어긋난 날이 온다.
`normalize`는 화면에 보낼 상태 문자열을 만드는 데만 쓴다.

`items[]`의 `currentStage`·`requestedAt`·`errorCode`·`commitSha`는 선택 항목이 아니다.
저장소 카드가 각각 단계 한 줄, "요청 후 N분 경과", 실패 사유, 기준 커밋 표시에 쓴다.

## 제출이 ANALYSIS-503-1 로 전부 실패할 때

Registry 가 발행되지 않은 것이다. 활성 경계는 `technology_registry.status='CURRENT'` 가
아니라 `technology_registry_alias` 행이고, 마이그레이션은 그 행을 넣지 않는다.
`Infra/scripts/c-registry-import.sh` 로 발행한다 -- 자세한 것은
[repository-analysis-request.md](repository-analysis-request.md#registry-가-발행돼-있어야-요청이-만들어진다).

`verify-deployment.sh` 의 `registry-alias` 항목이 배포 시점에 이것을 본다.

## 멈춘 분석의 정리 (S15P21E102-136)

`StaleAnalysisReaper`가 `active-window`(기본 2시간)를 넘긴 진행 중 분석을
`FAILED`로 종료시키고 `error_code`에 `ANALYSIS_TIMED_OUT`을 남긴다.

2026-09 운영에서 분석이 49시간째 `QUEUED`에 남은 일이 있었고, 그 상태를 되돌릴 경로가
코드 어디에도 없었다. 그대로 두고 "진행 중이면 새 요청을 막는다"를 얹으면 그 사용자는
영영 새 분석을 못 한다. 차단에 유효시간을 두는 것만으로는 부족하다 — 유효시간은
배치 차단만 풀어 주고 `uq_analysis_job_active`는 풀어 주지 못해, **그 저장소가 영구히
분석 불가**가 되기 때문이다. 인덱스를 실제로 풀려면 상태를 종료로 옮기는 수밖에 없다.

기본 2시간은 워커가 한 잡을 붙들 수 있는 최대 시간에서 나왔다
(클론 600초 · claim lease 900초 · max poll interval 900초 · 최대 시도 5회 = 최악 75분).
**워커 쪽 값을 올리면 이 값도 함께 올려야 한다.**

살아 있는데 느린 분석을 죽이면 뒤늦게 온 결과는 `AnalysisResultService`가
`ALREADY_TERMINAL`로 흘리고 그 근거는 저장되지 않는다. 그 일이 실제로 일어나면
같은 자리에서 WARN을 남긴다 — 그 로그가 보이기 시작하면 창이 짧다는 뜻이다.

관리자 모니터링의 `dataStore.staleAnalysisJobCount`가 창을 넘긴 진행 중 분석 수다.
0이 아니면 워커가 죽었거나 요청이 Kafka에 닿지 못하고 있다는 뜻이고, reaper가 돌고
있다면 곧 0으로 돌아온다.
