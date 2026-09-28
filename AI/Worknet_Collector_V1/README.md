# Worknet Collector V1

워크넷(work24.go.kr) 공개 채용공고를 **등록일 범위**로 수집해
`job-analysis-input/v1` 배치로 출력하는 V1 구현입니다. (S15P21E102-148)

계약은 S15P21E102-90이 확정한 `AI/job/contracts.py`를 그대로 사용하며 새로
정의하지 않습니다. 모듈 구성은 `AI/JobKorea_Collector_V1`(S15P21E102-159)과
같은 배치입니다.

| 파일 | 역할 |
|---|---|
| `client.py` | 요청 간격 · 지수 백오프 3회 · 차단 응답 감지 |
| `html_tree.py` | 표준 라이브러리 기반 최소 HTML 트리 (문서 순서 보존) |
| `parser.py` | `wantedAuthNo` 링크와 라벨 텍스트 기준 추출 (클래스명 비의존) |
| `crawler.py` | 목록→상세, 커서 저장·복원, 출력 기록, CLI |
| `dates.py` | 등록일·마감일 파싱 |

외부 파싱 의존성이 없습니다. 표준 라이브러리와 `pydantic`(계약 검증)만
사용하므로 `AI/requirements.txt` 외에 추가 설치가 필요하지 않습니다.

## 실행

저장소 루트에서 실행합니다.

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m Worknet_Collector_V1 `
  --start-date 2026-09-07 `
  --end-date 2026-09-07 `
  --occupation-preset dev `
  --output-dir data\worknet
Remove-Item Env:PYTHONPATH
```

목록만 받아 동작을 확인하려면 `--no-detail`을 붙입니다. 상세 요청을
보내지 않으므로 레코드는 `body_status=MISSING`으로 기록되며, 이는 의도된
실행이라 `detail_errors`로 집계되지 않습니다.

### 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--start-date` · `--end-date` | 오늘(UTC) | 등록일 범위. 양끝 포함 |
| `--output-dir` | `data/worknet` | 출력 루트 |
| `--page-size` | `50` | 목록 1페이지 건수 |
| `--max-pages` | `20` | 페이지 상한 |
| `--request-delay` | `1.0` | 요청 간 대기(초) |
| `--no-detail` | 꺼짐 | 목록만 수집 |
| `--base-url` | `https://www.work24.go.kr` | |
| `--region-code` | 없음 | 워크넷 지역 코드(`codeDepth1Info`) |
| `--cursor` | 없음 | 재기동 상태 파일. 생략하면 재기동 복원 없음 |
| `--keyword` | 없음 | 자유 검색어. 생략하면 전 직종 수집 |
| `--occupation` | 없음 | 워크넷 직종 코드. 쉼표로 구분 |
| `--occupation-preset` | 없음 | `software` · `dev` · `dev-extended` |

종료 코드는 `0`(1건 이상 수집) · `1`(0건) · `2`(인자 오류)입니다.
중단이 발생해도 수집된 레코드가 있으면 `0`이며, 중단 사유는 stderr와
`manifest.json`의 `stopped_reason`에 남습니다.

## 직무 필터 — 반드시 지정하십시오

**필터 없이 실행하면 개발 직무 공고가 사실상 들어오지 않습니다.** 실측에서
요양보호사·가구제조·제조 단순종사원 공고가 채워졌고, 개발 공고는 한 건도
나오지 않았습니다. 전 직종은 유입량도 시간당 150건 수준이라 하루 2회
스케줄(S15P21E102-107)로는 결번이 생깁니다.

### `--occupation-preset dev` 를 쓰십시오

개발 직무 직종 코드는 `occupations.py`에 있습니다.

| 프리셋 | 직종 코드 | 범위 |
|---|---|---|
| `software` | `024` | 소프트웨어 |
| **`dev`** | `024 025 026 023` | + 네트워크·정보보안, 데이터·정보시스템·웹 운영, 컴퓨터시스템 |
| `dev-extended` | + `022` | + 컴퓨터하드웨어·통신공학 |

`dev`가 `022`를 빼는 이유는 하드웨어·통신공학이 인접 직무이고 그 스택이
기술 수요 집계를 왜곡하기 때문입니다. 필요하면 `dev-extended`를 쓰십시오.

`--occupation`으로 leaf 코드를 직접 넘길 수도 있고, 프리셋과 함께 쓰면
합쳐집니다 (`--occupation-preset dev --occupation 133206`).

### 코드 목록은 어디서 왔나

워크넷은 검색 페이지에 코드 목록을 싣지 않습니다. 한국표준직업분류도
아닙니다. 직종 선택기가 쓰는 엔드포인트에서 받아옵니다.

```
POST /wk/l/b/1100/selectJobsSubSearchList.do
superJobsCd=<상위 코드>&type=worknet
```

`superJobsCd`를 비우면 1차 분류 13건이 오고, 각 단계가 자기 하위를
반환합니다. 워크넷이 분류를 개편하면 이 엔드포인트로 갱신하십시오.

**프리셋은 중분류(3자리)를 씁니다.** 안정적이고, 그룹에 leaf가 새로 생겨도
코드 변경 없이 따라갑니다.

### 프리셋은 분류기가 아니라 거친 사전 필터입니다

실측(2026-09-07) `024`는 "AI 역량이 높은 Back End SW 개발자" ·
"Full-Stack 개발자" · "결제플랫폼 앱개발"을 잡지만 "제어팀 정규직 구인" ·
"PMO/PI"도 같이 옵니다. **직종은 구인기업이 직접 고르기 때문에** 소프트웨어
코드 아래에 소프트웨어가 아닌 공고가 있습니다. 후보 집합을 좁히는
수단으로 쓰고, 최종 판단은 수집한 공고 본문에서 하십시오.

### `--keyword`는 정밀도가 낮습니다

`--keyword 개발자`는 동작하지만 실측 10건 중 소프트웨어 개발은 1~2건이고
나머지는 전기집진필터·인버터·바이오 개발이었습니다. **`--occupation-preset`을
우선 쓰십시오.**

## 출력

각 실행은 `<output-dir>/<pipeline-run-id>/` 아래에 세 파일을 남깁니다.
`pipeline_run_id`는 `WORKNET-<UTC 타임스탬프>` 형식입니다.

| 파일 | 내용 |
|---|---|
| `job_analysis_input.json` | `job-analysis-input/v1` 계약 출력. 검증을 통과한 레코드만 |
| `postings.csv` | 분석용 요약 15열 (`source_record_id` … `description_char_count`) |
| `manifest.json` | 실행 조건, 건수, `body_status` 분포, 커서 상태, 중단 사유, 오류 표본 |

세 파일 모두 임시 파일에 쓰고 `os.replace`로 교체하는 원자적 기록입니다.

`manifest.json`의 `request` 절에 `keyword`·`occupation_codes`를 포함한 실행
조건 전체가 들어가므로, 같은 결과를 다시 만들려면 이 값을 그대로 넘기면
됩니다.

**수집 산출물은 저장소에 커밋하지 않습니다.** `/data/worknet/`이
`.gitignore`에 있습니다 (팀 규칙 — 원본 데이터·덤프 커밋 금지).

## 재기동

워크넷 목록에는 안정적인 offset이 없습니다. 그래서 커서는 페이지 번호가
아니라 **해당 날짜 범위에서 이미 수집·검증된 공고 id 목록**을 저장하고,
재실행 시 그 id를 건너뜁니다(`skipped_already_collected`).

```powershell
& $python -m Worknet_Collector_V1 --cursor data\worknet\cursor.json
```

**날짜 범위가 달라지면 저장된 id는 무시됩니다.** 다른 범위의 id 목록은 이번
실행에 대해 아무것도 말해주지 않기 때문입니다. 커서 파일이 깨져 있어도
빈 상태로 시작합니다.

사이트별 커서 격리는 S15P21E102-101에서 다룹니다.

## V1 인수인계 참고

- **레이아웃 변경에 대한 degrade 방향.** 상세 본문 범위를
  `div.cont_wrap_area` → `div#contents` → `section#container` 순으로 좁히고,
  전부 없으면 `<body>`로 되돌아갑니다. 공고를 잃지 않는 쪽을 택한 결과이므로,
  **레이아웃이 바뀌면 본문에 header·GNB·footer가 조용히 섞여 들어옵니다.**
  `manifest.json`의 `description_char_count`가 갑자기 커지면 이것을 먼저
  의심하십시오. 같은 페이지 기준 정상값은 약 3,900자, 공통 영역 포함 시
  약 7,700자입니다.
- **파싱은 라벨 텍스트 기준입니다.** 클래스명 변경에는 견디지만 라벨 문구가
  바뀌면 조용히 실패합니다. 실제로 상세 라벨이 "등록일"이 아니라
  "등록일시"여서 등록일 추출이 실패한 적이 있습니다.
- **등록일은 상세 우선, 실패 시 목록 컬럼입니다.** 본문 첫 날짜를 집어오는
  fallback은 제거했습니다 — 마감일을 등록일로 저장해 미래 날짜가 찍히는
  원인이었습니다. 두 값이 다를 때 어느 쪽을 신뢰할지는 아직 명시되지
  않았습니다.
- **차단은 사이트 단위로 중단합니다.** `WorknetBlockedError`가 별도 타입인
  것은 한 사이트가 막혔을 때 다른 사이트 수집을 멈추지 않기 위한 것입니다
  (S15P21E102-101 계약). 중단 사유는 `manifest.json`의 `stopped_reason`에
  남습니다.
- **집계 시 source별 분모를 분리해야 합니다.** 사이트마다 수집 범위가 달라
  전체 공고 수를 하나의 분모로 쓰면 기술 점유율이 왜곡됩니다
  (S15P21E102-94 §3.5). 이 모듈은 레코드마다 `source_site`를 기록하는
  것까지만 담당하고, 분모 분리는 S15P21E102-146에서 다룹니다.
- API 발급이 되지 않아 크롤링 방식으로 갑니다(S15P21E102-161은 제출·대기).
  API가 승인되면 `client.py`·`parser.py`를 대체하고 `crawler.py`의 계약
  매핑은 유지할 수 있습니다.

## 테스트

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m pytest AI\tests\test_worknet.py -q
```

63건입니다. 실제 사이트로만 드러난 결함(공통 영역 혼입, 등록일 미래 날짜,
`--no-detail` 오류 오집계)에는 회귀 테스트가 붙어 있습니다. 고정 HTML 단위
테스트만으로는 세 건 모두 통과했으므로, **파서를 손볼 때는 실제 페이지로
한 번 돌려보십시오.**
