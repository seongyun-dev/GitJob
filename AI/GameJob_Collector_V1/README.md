# GameJob Collector V1

> **이 수집기는 기준 A 미통과 대상입니다. 돌리기 전에 읽으십시오.**
>
> `-149` 심사(`docs/data/2026-09-08-source-criterion-a-review.md` §3)가 게임잡을
> **미통과**로 판정했습니다. 운영사 웍스피어가 잡코리아와 동일 법인이라
> `-94`의 판례·소송 근거가 그대로 적용됩니다. `schedule.toml`의 게임잡 회차는
> `enabled = false`이고, 켜는 전제는 웍스피어와의 데이터 제공 계약입니다.
>
> 코드는 구현·검증을 마쳤습니다. 판정을 뒤집는 문서는 아닙니다.

게임잡(gamejob.co.kr) 채용공고를 **등록일 범위**로 수집해
`job-analysis-input/v1` 배치로 출력하고 HDFS Raw에 적재합니다.

계약은 S15P21E102-90의 `AI/job/contracts.py`를 그대로 쓰고, 계약 매핑은
S15P21E102-99의 `job/collector/normalize.py`에 위임합니다.

| 파일 | 역할 |
|---|---|
| `parser.py` | 목록·상세 추출 (`tr`, `dl.recruit-data-item`, 본문 iframe) |
| `dates.py` | `07/28(화) 등록` · `3시간 전 등록` · `~11/08` 파싱 |
| `duties.py` | 모집분야 토큰과 프리셋 (클라이언트측 필터) |
| `crawler.py` | 목록→상세→본문, 커서, 출력, CLI |

HTTP 클라이언트와 HTML 트리는 `job/collector/`의 공용 부품을 씁니다. HDFS
적재도 사이트별 코드가 아니라 `job/collector/raw_sink.py`입니다.

**Kafka 코드는 이 패키지에 없습니다.** S15P21E102-103이 회차의 Raw 적재가
성공한 뒤 스케줄러(`job/collector/__main__.py`)에서 `jobs.collected`를
발행하고, 그 event는 공고를 싣지 않고 run 위치만 가리키는 Claim Check입니다.
수집기마다 producer를 두면 그걸 중복하거나 회차 하나를 공고 수만큼의 메시지로
쪼개게 되므로, 이 수집기는 `schedule.toml`에 선언되는 것만으로 발행됩니다.

## robots.txt — 먼저 읽으십시오

`https://www.gamejob.co.kr/robots.txt` (2026-09-08 확인)

| 상태 | 경로 |
|---|---|
| **Disallow** | `/List_GG/` · `/Login/` · `/User/` · `/Text_User/` · `/Text_Co/` · `/Project/` · `/Help/` · `/Corp/Person/Find` |
| 미언급(=허용) | `/List_Gi/` · `/List_GI/` (목록) · `/Recruit/` (상세·본문 iframe) |

이 수집기는 `/List_Gi/GI_Total_List.asp`와 `/Recruit/...`만 요청합니다.

**`/List_GG/GG_Total_List.asp`는 사이트 헤더에 링크되어 있고 금지입니다.**
여기서 쓰는 `/List_Gi/`와 이름이 한 글자 차이라서 따로 적어 둡니다 — 바꾸지
마십시오. 회귀 테스트가 이를 고정합니다
(`test_no_disallowed_path_is_ever_requested`).

`/Project/`(프로젝트·외주)도 금지이므로 프리랜스 공고는 이 수집기의 범위
밖입니다.

**요청을 추가하기 전에 robots.txt를 다시 확인하십시오.**

## 사이트 제약 — 서버측 필터·정렬이 없습니다

목록 페이지는 `duty`(직무)·`orderTab`(정렬)·`psTab`(페이지 크기) 컨트롤을
렌더링하지만, **query string으로는 받지 않습니다.** 세션에 POST되고 목록이
세션 상태로 다시 렌더링되는 구조입니다.

2026-09-08 실측: `?duty=1`, `?orderTab=3`, `?psTab=40` 모두 필터 없는 요청과
**바이트 단위로 동일한** 응답(364,189 bytes)을 돌려줍니다.

**`?Page=N`도 무시됩니다.** 80페이지를 요청해 3,200행을 받았는데 **고유 공고는
40건**이었습니다 — 모든 페이지가 같은 페이지입니다. 즉 query string으로 닿을 수
있는 목록 전체가 그 40건이고, `--max-pages`는 데이터가 아니라 요청만 늘립니다.

그래서 **새 공고 id를 하나도 주지 않는 페이지가 나오면 중단**합니다. `--max-pages
10` 회차가 목록 요청 10번에서 2번으로 줄어듭니다.

실제 페이징은 세션 기반 `/recruit/_GI_Job_List` 조각에만 있는데, 반복 요청에서
0바이트를 돌려줘서 쓰지 않습니다.

여기서 두 가지가 더 따라옵니다.

- **범위 밖 행만 있는 페이지로는 끝내지 않습니다.** 기본 정렬이 추천순이라
  범위 밖 다음에 더 새 공고가 올 수 있습니다. 사람인처럼 조기 종료하면 공고가
  조용히 누락되는데, 그게 S15P21E102-107이 막으려는 실패입니다. **새 공고가
  없는 페이지**만 종료 조건입니다.
- **직무 필터는 우리 쪽에서 돕니다.** 목록의 추적 호출에서 모집분야를 읽어
  상세 요청을 아끼는 용도이며, 정확성 경계가 아닙니다. 모집분야를 못 읽은
  행은 **버리지 않고 남기고** manifest에 셉니다
  (`counts.kept_unknown_category`).

## 공고 하나가 최대 3요청입니다

본문이 iframe에 있습니다.

| 섹션 | 경로 |
|---|---|
| 담당업무 | `/Recruit/GI_Read_Comt_Ifrm?gno={id}` |
| 자격조건 | `/Recruit/GI_Read_GI_Comment_Ifrm?gno={id}` |

`parse_detail`은 그래서 혼자서 `description_text`를 만들지 못합니다.
`body_iframe_refs`가 페이지에서 src를 읽고 crawler가 받아옵니다 — 경로를
하드코딩하지 않으므로 엔드포인트가 바뀌면 잘못된 본문을 가져오는 대신
`body_status=PARSE_FAILED`가 됩니다.

기본 요청 간격(2초)을 워크넷 수준으로 낮추지 않는 이유가 이것입니다.

## 키워드는 저장하지 않습니다

상세 페이지에는 이 프로젝트가 원하는 그대로의 `키워드` 행이 있습니다 —
`서버, MS-SQL, 네트워크, Unreal, Unity, 게임프로그래밍`.

**그래도 `GameJobDetail`에서 멈춥니다.** `job.contracts.SourceSurface`가
`TITLE | BODY`뿐이라 사이트 자체 태그에서 나온 mention을 기록할 surface가
없고, `BODY`로 저장하면 공고 본문이 하지 않은 말을 했다고 주장하게 됩니다.
승격하려면 계약 변경(`SITE_TAG` surface)이 필요하고 그건 S15P21E102-90의
결정입니다. manifest에 개수를 남기므로
(`technology_extraction.site_keyword_count`) 그 변경의 값은 보입니다.

## 실행

저장소 루트에서 실행합니다.

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m GameJob_Collector_V1 `
  --duty-preset dev `
  --days-back 1 `
  --max-pages 10 `
  --output-dir data/gamejob
```

목록만 받는 스모크 실행(상세·본문 요청 없음, `body_status=MISSING`):

```powershell
& $python -m GameJob_Collector_V1 --no-detail --max-pages 1
```

### 출력

`{output-dir}/{pipeline_run_id}/` 아래에 씁니다.

| 파일 | 내용 |
|---|---|
| `job_analysis_input.json` | 검증된 `job-analysis-input/v1` 배치 |
| `postings.csv` | 분석자용 평면 표 |
| `manifest.json` | 요청 파라미터·건수·본문 상태·중단 사유 |
| `raw_upload.json` | HDFS Raw 적재 결과 (적재한 경우) |

### HDFS Raw

`WEBHDFS_URL`이 스위치이고, 없으면 로컬 전용 실행이 됩니다
(`raw=skipped (WEBHDFS_URL 미설정)`). 경로는
`/gitjob/raw/gamejob/dt=YYYY-MM-DD/{pipeline_run_id}/`입니다.

적재 실패는 예외로 올리지 않고 exit code 1과 `raw_upload.json`으로 보고합니다
— 공고는 다시 수집할 수 없으므로 로컬 snapshot을 버리지 않는 쪽을 택합니다.
`--no-upload-raw`로 끕니다.

Kafka 발행은 스케줄러가 합니다. 회차 event는 적재가 성공한 회차에만 나가므로,
`raw=skipped`인 로컬 실행에서는 발행도 없습니다 — S15P21E102-103 참고.

## 스케줄

`AI/schedule.toml`의 `gamejob-morning` · `gamejob-evening`가 09:50 / 21:50에
돕니다. 워크넷(09:10)·사람인(09:30)과 20분씩 벌려 둔 것은 세 수집의 요청이
같은 시각에 겹치지 않게 하려는 것입니다.

```powershell
& $python -m job.collector --run gamejob-morning
```

## 날짜 파싱에서 주의할 점

목록은 등록일을 네 가지로 씁니다. **아무 것도 연도를 담지 않습니다.**

```text
07/28(화) 등록      연도 없음
38분 전 등록        상대 시각
3시간 전 등록       상대 시각
6일 전 등록         상대 시각
```

마감일은 두 가지가 더 있습니다: `채용시`(마감 없음), `~11/08`(연도 없음),
`2026.07.15`(전체 날짜).

**등록일과 마감일은 연도를 반대 방향으로 추정합니다.** 등록일은 미래일 수
없으므로 1월에 본 `12/28`은 지난해 12월입니다. 마감일은 보통 앞쪽이므로
12월에 본 `01/15`는 다음해 1월입니다. 하나의 추정을 공유하면 공고가 조용히
1년 옮겨지는데, 그게 S15P21E102-148이 기록한 버그 부류입니다.

상세 페이지는 정확한 시각을 줍니다 (`2026-07-03 17:07 등록`). `posted_at`은
이 값을 우선하고, 목록의 날짜 칸은 목록만 받는 실행의 fallback입니다.
