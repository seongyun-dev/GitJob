# Registry Mapper·채용 요구유형 분류·Review 구현 내역

> 기준일: 2026-09-07
>
> 관련 Jira: `S15P21E102-81`, `S15P21E102-82`, `S15P21E102-88`
>
> 상태: C측 구현·로컬 검증 완료. 실공고 전체 흐름 검수와 B측 운영 통합은 미완료.

## 1. 구현 범위와 변경 파일

| 이슈 | 구현 | 테스트 | 결과 |
|---|---|---|---|
| -81 | [registry/mapper.py](../../AI/registry/mapper.py) | [test_registry_mapper.py](../../AI/tests/test_registry_mapper.py) | 출처별 MATCHED/AMBIGUOUS/UNKNOWN, 후보·근거·Registry 버전 |
| -82 | [job/classifier.py](../../AI/job/classifier.py) | [test_job_classifier.py](../../AI/tests/test_job_classifier.py) | 요구유형, 원문 섹션·위치, 복수 근거, 공고 메타데이터 |
| -88 | [registry/review.py](../../AI/registry/review.py) | [test_registry_review.py](../../AI/tests/test_registry_review.py) | 로컬 미해결 큐 저장·조회, 판정 이력, pending 재처리 |

사용 방법은 [AI README](../../AI/README.md), Registry 및 C/B 책임 경계는
[Registry 계약 10절](../data/2026-09-01-technology-registry-v1.md#10-c측-review-구현과-b측-통합-경계)에 기록했다.
A→C `job-analysis-input/v1` 입력 계약과 A/B 소유 구현, 환경 변수, 의존성은 변경하지 않았다.
Stack Overflow와 신규 수요 집계 구현은 이번 범위에 포함하지 않는다.

## 2. 입력에서 결과까지

1. `JobAnalysisInputBatch`로 A 입력의 schema·URL·시각·본문 상태를 검증한다.
2. `RegistryMapper`는 명시된 source와 ecosystem에 맞춰 ACTIVE Registry를 조회한다.
3. `classify_job_batch`는 mention별 mapping 및 요구유형을 `job-technology-classification/v1`에 기록한다.
4. `ReviewStore.ingest`는 mapping이 UNKNOWN 또는 AMBIGUOUS인 결과를 `registry-review-queue/v1`에 보존한다.
5. 수동 판정 또는 새 Registry를 사용한 `reprocess_pending`로 검토 이력을 추가한다.

### -81 Registry Mapper

- DISPLAY_NAME, ALIAS, PACKAGE, IMPORT_PATH, STACKOVERFLOW_TAG, GITHUB_LANGUAGE를 구분한다.
- exact match와 import segment prefix 경계를 사용하며 후보와 정규화·판정 근거를 반환한다.
- 자유 텍스트의 C/R/Go는 명시적인 언어 문맥이 없으면 모호한 후보로 남긴다.
- C++, C#, Objective-C, C-level, R&D, Go-to-market을 짧은 기술명 C/R/Go의 확정 근거로 사용하지 않는다.
- 결과에 실제 사용한 `registry_version`을 기록한다.

### -82 채용 요구유형 분류

- REQUIRED, PREFERRED, SKILL, REVIEW_REQUIRED를 구분한다. 입력 요구유형과 섹션이 충돌하거나 Registry가 미해결이면 검토 대상으로 남긴다.
- A의 `evidence_section`과 C가 원문에서 관측한 `parsed_section`을 별도로 보존한다.
- C는 원문 evidence offset까지 완전한 heading을 탐색한다. 고정된 앞쪽 줄 수에 제한되지 않으며, A의 누락·일반 본문 label을 보완한다. A의 명시적 section label은 유지한다.
- 동일 기술의 전달된 복수 근거를 유지하고, 다른 기술들이 하나의 evidence 문장을 공유하면 같은 위치를 기록한다.
- 원문 text, surface, offset, mention index, mapping 시도 순서, parser/Registry 버전을 보존한다.
- 공고 ID·URL·회사·직무·지역·상태·게시/수집 시각·content hash를 후속 집계 입력으로 유지한다. JSON 재검증에서도 URL과 timezone 제약을 적용한다.

기존 -159 extractor는 요구유형 탐색을 12줄/240자, 섹션 탐색을 5줄로 제한하며
technology/requirement/surface 기준으로 일부 근거를 합친다. C의 섹션 보완은 긴 섹션의
요구유형 누락과 일반 섹션으로 넘어갈 때의 잘못된 상태 상속을 다룬다.
A가 이미 합쳐 전달하지 않은 근거는 C에서 복원하지 않는다.

### -88 검토 저장·조회·재처리

- 단일 writer의 caller-path JSON snapshot을 atomic replace로 저장한다.
- 안정적인 review ID로 동일 snapshot의 반복 ingest를 중복 저장하지 않는다.
- source ID·URL·surface, 원문 근거·문맥, 후보·사유, 자동/수동 판정 이력을 조회한다.
- 수동 판정은 ACTIVE tech ID, 검증된 Registry Mapper, reviewer와 note를 요구한다.
- pending을 저장된 mapping 순서와 문맥으로 재처리하고 해결된 항목만 RESOLVED로 바꾼다.
- `MATCHED / REVIEW_REQUIRED`처럼 요구유형만 충돌한 결과는 Registry 미해결 큐의 대상이 아니다.

## 3. 검증 결과와 재현

구현 기준 base는 `b0ed7a7aea57b134acd1edd70764d6640830ec3f`이다.
Python 3.12와 저장소 `requirements-dev.txt` 환경에서 검증했다.

| 검증 | 결과 |
|---|---|
| -81 단계의 Mapper + 기존 Registry 계약/Seed | 92 passed |
| -82 단계의 Mapper + 분류기 | 37 passed |
| -88 단계의 Mapper + 분류기 + Review | 43 passed |
| 전체 변경을 포함한 LF 복사본의 전체 AI 테스트 | 280 passed, 제외 없음 |
| 변경 Python 6개 파일 Ruff check/format | 통과 |
| diff whitespace | 통과 |

Windows `core.autocrlf=true` 체크아웃에서 Registry JSON schema가 CRLF가 되면
`test_committed_json_schema_matches_contract_model_exactly`의 byte 비교가 실패한다.
스키마 검사를 수정하거나 제외하지 않고 LF 보존 복사본에서 전체 통과를 확인했다.
미커밋 변경을 모두 포함한 검증본과 최종 구현 커밋의 변경 파일 8개는 LF SHA-256이 일치한다.

집중 검증은 저장소 루트에서 실행한다. `$python`은 해당 프로젝트 Python 환경을 지정한다.

```powershell
$python = (Resolve-Path 'AI/.venv/Scripts/python.exe').Path
$env:PYTHONPATH = (Resolve-Path 'AI').Path + ';' + (Resolve-Path 'Infra/spark').Path
& $python -m pytest AI/tests/test_registry_mapper.py AI/tests/test_job_classifier.py AI/tests/test_registry_review.py -q
Push-Location AI
try {
    & $python -m ruff check registry/mapper.py job/classifier.py registry/review.py tests/test_registry_mapper.py tests/test_job_classifier.py tests/test_registry_review.py
    & $python -m ruff format --check registry/mapper.py job/classifier.py registry/review.py tests/test_registry_mapper.py tests/test_job_classifier.py tests/test_registry_review.py
} finally { Pop-Location }
```

Ruff는 `AI/`를 현재 디렉터리로 실행한다. 루트에서 실행하면 로컬 모듈의
first-party 판별이 달라져 기존 검증과 다른 import 정렬 결과가 나온다.

커밋된 전체 변경은 저장소 밖의 새 임시 디렉터리에서 LF로 재현할 수 있다.

```powershell
$validationDir = Join-Path $env:TEMP ('gitjob-ai-lf-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $validationDir | Out-Null
$archivePath = Join-Path $validationDir 'source.zip'
$sourceDir = Join-Path $validationDir 'source'
git -c core.autocrlf=false archive --format=zip --output=$archivePath HEAD
Expand-Archive -LiteralPath $archivePath -DestinationPath $sourceDir
$env:PYTHONPATH = (Join-Path $sourceDir 'AI') + ';' + (Join-Path $sourceDir 'Infra/spark')
Push-Location (Join-Path $sourceDir 'AI')
try { & $python -m pytest tests -q } finally { Pop-Location }
Remove-Item Env:PYTHONPATH
```

전체 Ruff에는 기존 I001 7건이 남는다: `collector/gharchive/sinks.py`,
`github/repo_fetch_store.py`, `github/repo_snapshot_bootstrap.py`, `llm/test_server.py`,
`tests/test_repo_fetch_benchmark.py`, `tests/test_repo_fetch_orchestrator.py`,
`tests/test_repo_snapshot_bootstrap.py`. 해당 파일은 base 대비 변경하지 않았다.
로컬 테스트는 Linux CI, 배포 또는 운영 DB 통합의 증거가 아니다.

## 4. 실제 공고 표본 점검

2026-09-07 접근 가능한 작업공간에서 기존 실공고 snapshot을 찾지 못했다.
기존 클라이언트로 공개 페이지 접근을 확인하고, -159 수집기의 기존 범위로 최소 probe를 수행했다.

- 범위: 2026-08-01~2026-08-31, 백엔드개발자 duty 1000229.
- 설정: 1페이지, page_size 3, 목록 지연 0.8초, 상세 지연 0.5초, timeout 15초, 1회 시도, OCR 비활성.
- 결과: 목록 3행, 기간 일치 0건, 상세 요청 0건, 출력 0건.
- 종료: `max_pages`; 날짜 경계 도달 전 제한 종료 경고가 있다.
- run ID: `jobkorea-20260907T120400+0900`. 빈 입력 결과와 manifest는 저장소 밖에 보관했다.
- 기존 manifest의 request 설명은 pagesize=40으로 고정되어 있으나 실제 config는 3이고 `raw_rows_seen=3`이다.

따라서 실제 비어 있지 않은 공고의 수집→계약→Mapper→분류→Review 검증은 미완료다.
기존 extractor를 직접 호출하는 회귀 검증은 synthetic 입력으로 수행했다.
후속 검수에는 기간과 사용 권한이 확인된 실공고 표본이 필요하다.

## 5. 남은 통합과 커밋

B측 관리자 API·운영 DB 통합에서 review 이력 영속성, 인증된 actor,
중복 판정 요청 key, 승인 Registry 공급, 재처리 실행·상태·동시 갱신 규칙을 확정해야 한다.
C측 로컬 구현 완료를 -88 전체 운영 통합 완료로 간주하지 않는다.

| 커밋 | 동작 |
|---|---|
| `c29b5ad793bddfa5d2f99ae8eb09253af2484f5e` | -81 Mapper와 집중 테스트 |
| `e5b60700e10c0315368140c27b05912428b28950` | -82 분류기와 집중 테스트 |
| `8dfe5e710fb749e92aa75c4efca3cdab80125b77` | -88 Review와 집중 테스트, C/B 통합 경계 |

## 6. 원문·계약

- [S15P21E102-81](https://ssafy.atlassian.net/browse/S15P21E102-81)
- [S15P21E102-82](https://ssafy.atlassian.net/browse/S15P21E102-82)
- [S15P21E102-88](https://ssafy.atlassian.net/browse/S15P21E102-88)
- [A→C 채용 입력 계약](../data/2026-09-01-a-to-c-job-analysis-input-contract.md)
- [Technology Registry 계약](../data/2026-09-01-technology-registry-v1.md)
