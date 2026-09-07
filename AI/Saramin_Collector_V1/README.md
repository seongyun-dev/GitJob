# Saramin Collector V1

사람인(saramin.co.kr) 채용공고를 **등록일 범위**로 수집해
`job-analysis-input/v1` 배치로 출력합니다. (S15P21E102-148)

계약은 S15P21E102-90의 `AI/job/contracts.py`를 그대로 쓰고, 계약 매핑은
S15P21E102-99의 `job/collector/normalize.py`에 위임합니다.

| 파일 | 역할 |
|---|---|
| `parser.py` | 목록·상세 추출 (`div.item_recruit`, `div.user_content`) |
| `dates.py` | `등록일 26/09/07` · `~ 10/07(수)` 파싱 |
| `categories.py` | `cat_kewd` 직군 코드와 프리셋 |
| `crawler.py` | 목록→상세, 커서, 출력, CLI |

HTTP 클라이언트와 HTML 트리는 `job/collector/`의 공용 부품을 씁니다.

## robots.txt — 먼저 읽으십시오

**사람인은 일반적인 공고 상세 경로를 `User-agent: *`에 대해 금지합니다.**

| 상태 | 경로 |
|---|---|
| **Disallow** | `/zf_user/recruit/view/` · `/zf_user/recruit/recruit-posting/` · `/recruit/recruit_view.php` · `/zf_user/company/` |
| **Allow** | `/zf_user/jobs/view/popup` · `/zf_user/jobs/public/popup-view` · `/zf_user/jobs/relay/recruit-view` |
| 미언급(=허용) | `/zf_user/search/recruit` (검색 목록) |

이 수집기는 **허용된 `/zf_user/jobs/view/popup`만** 요청합니다. 실측에서 이
팝업이 같은 상세요강 본문을 제공합니다(431KB 페이지 중 본문 약 1.7KB).
금지 경로는 한 번도 요청하지 않으며, 회귀 테스트가 이를 고정합니다
(`test_no_disallowed_path_is_ever_requested`).

**요청을 추가하기 전에 robots.txt를 다시 확인하십시오.** S15P21E102-94가
잡코리아를 제외한 근거가 크롤링 적법성이었고, 같은 판단 기준이 여기에도
적용됩니다.

`source_url`에는 목록 링크의 추적 파라미터(`search_uuid` 등)를 넣지 않고
공고 id로 팝업 경로를 직접 구성합니다 — 실행마다 값이 달라지면 같은 공고가
다른 URL로 저장됩니다.

## 실행

저장소 루트에서 실행합니다.

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m Saramin_Collector_V1 `
  --category-preset dev `
  --start-date 2026-09-07 `
  --end-date 2026-09-07 `
  --output-dir data\saramin
Remove-Item Env:PYTHONPATH
```

### 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--start-date` · `--end-date` | 오늘(UTC) | 등록일 범위, 양끝 포함 |
| `--days-back` | `0` | `--end-date` 기준 N일 전까지 확장 (스케줄용) |
| `--output-dir` | `data/saramin` | 출력 루트 |
| `--page-size` | `50` | 목록 1페이지 건수 |
| `--max-pages` | `20` | 페이지 상한 |
| `--request-delay` | **`2.0`** | 요청 간 대기(초) |
| `--no-detail` | 꺼짐 | 목록만 수집 |
| `--cursor` | 없음 | 재기동 상태 파일 |
| `--keyword` | 없음 | 자유 검색어 |
| `--category` | 없음 | `cat_kewd` 코드, 쉼표 구분 |
| `--category-preset` | 없음 | `software` · `dev` · `dev-extended` |

**요청 간격 기본값이 워크넷(1.0초)보다 느린 2.0초입니다.** 사람인은 상업
사이트이고 우리에게 API 허가가 아직 없습니다(S15P21E102-161 제출·대기).

## 직군 필터 — 반드시 지정하십시오

필터 없이 실행하면 카지노·호텔 공채, 생산기술직, 생산직 보전반이 채워집니다.
`cat_kewd=84`는 백엔드 개발자·클라우드 아키텍트를 반환합니다.

| 프리셋 | 범위 |
|---|---|
| `software` | 백엔드·웹·프론트엔드·앱·풀스택·S/W·펌웨어 |
| **`dev`** | + 데이터·AI·DevOps·클라우드·API·SI·개발PM·QA |
| `dev-extended` | + 네트워크·IT컨설팅·기술지원·유지보수·H/W |

### 프리셋에 기술스택 코드를 넣지 마십시오

`cat_kewd`는 한 이름공간에 두 종류를 섞어 씁니다.

```
84  백엔드/서버개발   ← 직무
235 Java            ← 기술스택
```

**직무 코드만 프리셋에 들어갑니다.** 기술스택으로 필터하면 이 수집이
공급하는 측정이 순환합니다 — Java 태그 공고를 모아서 Java 수요를 세는 것이
됩니다. 스택 코드는 재발견하지 않도록 `categories.py`에 기록만 해뒀습니다.

### 코드 목록은 어디서 왔나

검색 결과의 각 공고 행이 자기 태그를
`/zf_user/jobs/list/job-category?cat_kewd=<코드>`로 링크합니다. 검색을 한 번
돌려 그 링크를 모으면 갱신됩니다.

## 서버측 날짜 범위가 없습니다

워크넷과 달리 검색에 등록일 범위 파라미터가 없습니다. 그래서
`recruitSort=reg_dt`로 등록일 내림차순을 요청하고 **범위 밖 행을 클라이언트
쪽에서 버립니다.** 한 페이지에 범위 내 공고가 하나도 없으면 그 뒤는 전부 더
오래된 것이므로 페이징을 멈춥니다 — 정렬이 이 조기 종료를 안전하게 만드는
근거입니다.

**등록일이 없는 행은 건너뛰고 `skipped_undated`로 셉니다.** 서버측 필터가
없으니 날짜 없는 행을 범위 안이라고 가정할 수 없습니다.

## 등록일 vs 수정일

목록의 날짜 칸은 `등록일 26/09/07` 또는 `수정일 26/09/07`입니다. 실측 40건
중 8건이 등록일 없이 수정일만 있었습니다.

수정일은 등록일이 아닙니다. 그래서 파서는 **어느 라벨이었는지 함께
반환하고**, manifest의 `listing_date_labels`에 그 분포를 남깁니다. 한쪽을
다른 쪽인 척 조용히 저장하지 않기 위한 것입니다.

## 출력

`<output-dir>/<pipeline-run-id>/` 아래 세 파일입니다.
`pipeline_run_id`는 `SARAMIN-<UTC 타임스탬프>`입니다.

| 파일 | 내용 |
|---|---|
| `job_analysis_input.json` | 계약 배치. 검증 통과 레코드만 |
| `postings.csv` | 분석용 요약 17열 (기술 id 목록 포함) |
| `manifest.json` | 실행 조건·건수·`robots`·날짜 라벨 분포·기술 추출 건수 |

**수집 산출물은 커밋하지 않습니다.** `/data/saramin/`이 `.gitignore`에
있습니다.

## V1 인수인계 참고

- **상세 본문을 못 찾으면 `None`을 반환합니다.** 워크넷은 `<body>`로
  degrade하지만 여기서는 하지 않습니다. 워크넷은 콘텐츠 영역이 페이지의 약
  절반인데 사람인 팝업은 본문이 10분의 1 미만이라, 문서 전체를 본문으로
  저장하는 쪽이 훨씬 나쁩니다. `body_status=PARSE_FAILED`로 기록됩니다.
- **지역은 위치가 아니라 "링크를 가진 span"으로 찾습니다.** `job_condition`은
  지역·경력·학력·고용형태 순서지만, 학력 span이 빠지는 공고가 있어 인덱스
  기준은 값이 조용히 밀립니다.
- **제목은 `title` 속성에서 읽습니다.** 링크 텍스트는 검색어가 `<b>`로
  감싸져 조각나 있습니다.
- **마감일에 연도가 없습니다.** `~ 10/07(수)`를 오늘 기준으로 해석하고,
  한 달 이상 지난 날짜는 내년으로 봅니다 — 12월에 보이는 `~ 01/15`는 내년
  1월입니다. 한 달의 여유를 둬서 방금 마감된 공고가 1년 뒤로 밀리지
  않습니다.
- **차단은 사이트 단위로 중단합니다.** `BlockedError`가 별도 타입인 것은 한
  사이트가 막혔을 때 다른 사이트를 멈추지 않기 위한 것입니다.
- **집계 시 source별 분모를 분리해야 합니다** (S15P21E102-94 §3.5). 사람인과
  워크넷의 수집 범위가 다릅니다.

## 테스트

```powershell
& $python -m pytest AI\tests\test_saramin.py -q
```

58건입니다. robots.txt 준수(금지 경로 미요청, 추적 파라미터 제외)에도 회귀
테스트가 붙어 있습니다.
