# C 완료 이벤트 전송 클라이언트

상태: 로컬 구현·검증. 기준일: 2026-09-08. 관련 Jira: S15P21E102-33.

`AI/worker/client.py`와 `AI/worker/submit.py`는 A 수집 완료 또는 B 분석 완료 시
C 내부 API를 즉시 호출하는 전송 adapter이다. 별도 사용자 확인 단계 없이 기존
완료 처리에서 호출한다. 수집기, B 완료 처리, 스케줄러나 큐를 이 모듈이 대신 실행하지는 않는다.

Worker의 [완료 manifest 자동 감시](c-compute-runtime.md)를 사용하는 공고는 이 전송기를
별도로 호출할 필요가 없다. `JOB_BATCH`는 명시적 한 배치 호출 경로이며, 여러 출처 자동
통합은 intake 경로다. B 개인 분석 완료는 `ANALYSIS` 호출로 연결한다.

## API와 입력

| kind | POST 경로 | 검증 모델 | 완료 결과 kind |
|---|---|---|---|
| JOB_BATCH | `/internal/v1/c/job-batches/completed` | `worker.api.JobCompleted` | COHORT, DEMAND |
| ANALYSIS | `/internal/v1/c/analyses/completed` | `worker.api.AnalysisCompleted` | RECOMMENDATION |
| PUBLIC_REPO | `/internal/v1/c/public-repositories/completed` | `worker.api.PublicReposCompleted` | PUBLIC_GITHUB |
| TREND | `/internal/v1/c/trends/completed` | `worker.api.TrendCompleted` | TREND |

별도의 입력 DTO 복사본을 만들지 않고 실제 API Pydantic 모델로 검증한다.
공통 envelope는 `schema_version="c-compute-event/v1"`, `event_id`, `trace_id`,
timezone을 포함한 `occurred_at`이다. JOB_BATCH는 `batch`, `criteria`를 추가하고,
ANALYSIS는 `user_id`, `analysis_id`, `cohort_snapshot_id`, `evidence`를 추가한다.
나머지 필드는 해당 모델과 [실행 API 계약](c-compute-runtime.md)을 따른다.

완료 처리자는 event_id와 occurred_at을 최초 완료 이벤트에 저장해 재전달에 재사용한다.
클라이언트는 새 event_id나 trace_id를 만들지 않는다. 최초 검증 결과를 JSON 바이트로
한 번 확정하며, 응답을 잃었거나 재시도해도 같은 바이트·이벤트 ID·trace ID를 전송한다.
CLI 재실행도 같은 파일을 사용한다. 입력이 달라졌을 때 기존 event_id를 재활용하지 않는다.

```python
import os
from worker.client import CompletionClient

client = CompletionClient(
    os.environ["C_COMPUTE_URL"],
    os.environ["C_COMPUTE_TOKEN"],
    timeout_seconds=10,
    max_attempts=3,
)
# A 또는 B의 기존 완료 처리에서 저장된 완료 이벤트를 바로 전달한다.
receipt = client.submit("JOB_BATCH", completed_event)
result_references = receipt.results
```

`CompletionReceipt`에는 event_id, COMPLETED 상태, `{kind, snapshot_id}` 참조만 있다.
HTTP 200이라도 event_id 불일치, PREPARING 상태, 누락/중복/예상 밖의 결과 kind,
잘못된 snapshot ID가 있으면 완료로 인정하지 않는다. 계산 결과 자체가 EMPTY 또는
INSUFFICIENT_DATA일 수 있다는 점은 계산 상태와 별개이며 결과 snapshot에서 조회한다.

## 재시도와 종료

재시도 대상은 timeout, URLError, HTTP 202/429/500/502/503/504,
HTTP 409의 정확한 `LEASE_LOST` 코드다. 응답 본문을 읽다가 발생한 timeout도 포함한다.
HTTP 400/401/403/404/422, `IDEMPOTENCY_CONFLICT`를 비롯한 다른 409,
리다이렉트와 예상하지 못한 응답은 재시도하지 않는다.

- 기본 3회, 설정 범위 1~5회다.
- HTTP 호출 timeout 기본 10초, 범위 `0 < timeout_seconds <= 60`초다.
  urllib의 네트워크 I/O timeout이며 전체 작업의 업무 SLA를 대신하지 않는다.
- 재시도 대기는 0.5초부터 지수적으로 증가하며 최대 5초다. 숫자형 Retry-After도
  0~5초로 제한한다. 지원하지 않는 값은 기본 대기를 사용한다.
- 요청 JSON은 8 MiB, 응답은 1 MiB까지만 처리한다.
- 재시도 소진은 `SubmissionError(code="RETRY_EXHAUSTED", exhausted=True)`이다.
  완료 참조가 없는 상태에서 성공으로 반환하지 않는다.

호출자는 소진된 이벤트를 기존 완료 이벤트 기록에 유지하고 같은 이벤트로 재전달한다.
영구 입력 오류는 입력/설정 문제를 먼저 수정한다. `IDEMPOTENCY_CONFLICT`에 새 ID를
자동 발급하여 기존 이벤트와 다른 계산을 섞는 기능은 없다.

## CLI

서비스 origin은 `C_COMPUTE_URL`, 토큰은 `C_COMPUTE_TOKEN` 환경 변수로만 지정한다.
URL은 query/fragment/credentials/path 없는 HTTP(S) origin이어야 한다.
토큰은 API와 같은 최소 32자의 공백 없는 ASCII 값이다. 토큰 CLI 옵션은 제공하지 않는다.

```powershell
# 저장소 루트에서 시작. URL/token과 검증할 실제 이벤트 파일은 미리 준비한다.
Set-Location AI
$python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "..\.venv\Scripts\python.exe"
}
& $python -m worker.submit --kind JOB_BATCH --input C:\events\job-completed.json
```

이미 `AI/`에 있다면 `Set-Location AI`는 생략한다. 위 예제는 기존 `AI/.venv`를 먼저 찾고,
없으면 [AI 개발 환경](../../AI/README.md)의 저장소 루트 venv를 사용한다. 둘 다 없으면 환경부터 준비한다.
저장소 루트에서 `python -m worker.submit`만 실행하면 `worker` 모듈을 찾지 못할 수 있다.
이 명령은 실제 완료 이벤트를 전송·계산·저장하므로 단순 read-only 확인 명령이 아니다.

`--timeout-seconds`, `--max-attempts`는 위 범위에서 선택할 수 있다.
명시한 기존 JSON 파일만 읽고 API 모델로 검증한 후 전송한다.

| 종료 코드 | 출력 |
|---|---|
| 0 | stdout에 검증된 CompletionReceipt JSON |
| 1 | stderr에 NOT_COMPLETED와 안전한 오류 코드/시도 수 |
| 2 | 입력 파일·JSON·schema·설정·CLI 인자 오류, NOT_COMPLETED |

토큰, 전체 입력/응답 본문, 외부 예외 문구는 로그나 CLI 오류에 출력하지 않는다.
잘못 넣은 CLI 인자를 오류 메시지에 다시 출력하지 않아 실수로 전달한 토큰의 노출도 막는다.
기본 urllib opener는 환경 proxy를 사용하지 않으며 모든 리다이렉트를 거부한다.
Authorization은 리다이렉트에 복사되지 않는 헤더로도 설정한다.

## 검증 범위

`tests/test_compute_client.py`와 `tests/test_compute_submit.py`는 네 가지 실제 입력 모델,
경로 제한, 동일 바이트 재전달, transient/permanent 오류 구분, 응답 중간 timeout,
시도·시간·크기 제한, 잘못된 완료 참조, CLI 종료/비밀값 미노출을 검증한다.
재시도는 주입한 opener/sleep을 사용한 단위 검증이다. 리다이렉트 차단은 실제 urllib와
로컬 loopback HTTP 서버에서 확인한다. 외부 서비스 요청이나 A/B 운영 코드 변경은 없다.

A/B의 실제 완료 경로에 이 호출을 연결하고 서버·DB·조회 API까지 통과시키는 검증은
별도 통합 인수이며, 이 전송기 단위 검증만으로 완료됐다고 주장하지 않는다.
