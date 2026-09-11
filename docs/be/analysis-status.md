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
