# 게임잡 채용공고 수집

> **상태: 기준 A 미통과. 수집기 구현 완료, 스케줄 비활성.**
>
> 게임잡은 [`-149` 기준 A 심사](2026-09-08-source-criterion-a-review.md) §3에서
> **미통과** 판정을 받았다. 운영사 웍스피어가 잡코리아와 동일 법인
> (사업자등록번호 `110-81-34859`, 앱 패키지명 `com.jobkorea.gamejob`)이라
> `-94`의 판례·소송 근거가 그대로 적용되고, 그 문서는 채용공고 source를
> **워크넷·사람인 2종으로 확정**했다.
>
> 이 수집기는 그 판정을 확인한 뒤에도 구현했다. `schedule.toml`의 두 회차는
> `enabled = false`이고 회귀 테스트가 이를 고정한다
> (`test_gamejob_is_declared_but_never_scheduled`). 켜는 전제는 웍스피어와의
> **데이터 제공 계약**이며, 기술적 우회는 `-94`가 이미 배제한 선택지다.
>
> 아래 내용은 계약이 확보됐을 때 쓸 수 있도록 남긴 **사이트 실측 기록**이다.
> source 채택 근거가 아니다.

게임잡(gamejob.co.kr)을 네 번째 채용공고 source **후보**로 구현하고, 수집
결과를 HDFS Raw에 적재한다.

Kafka 발행은 이 수집기에 없다. S15P21E102-103이 회차의 Raw 적재가 성공한 뒤
스케줄러에서 `jobs.collected`를 발행하므로, 게임잡은 `schedule.toml`에
선언되는 것만으로 발행 대상이 된다.

구현은 `AI/GameJob_Collector_V1/`이고, 계약은 S15P21E102-90의
`job-analysis-input/v1`, 계약 매핑은 S15P21E102-99의
`job/collector/normalize.py`를 그대로 쓴다. 사용법은
[수집기 README](../../AI/GameJob_Collector_V1/README.md)에 있다.

이 문서는 **사이트 실측에서 확인한 제약**을 남긴다. 워크넷·사람인과 다르게
동작하는 부분이 있고, 그 차이가 수집기 구조를 결정했기 때문이다.

측정일: 2026-09-08. 대상: `https://www.gamejob.co.kr`.

## 1. robots.txt

```text
User-agent: *
Disallow: /List_GG/
Disallow: /Login/
Disallow: /User/
Disallow: /Text_User/
Disallow: /Text_Co/
Disallow: /Project/
Disallow: /Help/
Disallow: /Corp/Person/Find
```

| 상태 | 경로 | 용도 |
|---|---|---|
| **Disallow** | `/List_GG/GG_Total_List.asp` | 목록 (사이트 헤더에 링크됨) |
| **Disallow** | `/Project/PM_Pro_List.asp` | 프로젝트·외주 |
| 미언급(=허용) | `/List_Gi/GI_Total_List.asp` | 목록 |
| 미언급(=허용) | `/Recruit/GI_Read/View?GI_No=` | 공고 상세 |
| 미언급(=허용) | `/Recruit/GI_Read_Comt_Ifrm`, `/Recruit/GI_Read_GI_Comment_Ifrm` | 본문 |

**`/List_GG/`가 금지이고 `/List_Gi/`가 허용이다.** 한 글자 차이이고 둘 다
사이트 헤더에 링크되어 있어서 혼동하기 쉽다. 수집기는 `/List_Gi/`만
요청하고, 회귀 테스트가 금지 경로 7개를 각각 고정한다
(`test_no_disallowed_path_is_ever_requested`).

`/Project/`가 금지이므로 프리랜스·외주 공고는 수집 범위 밖이다.

## 2. 서버측 필터·정렬을 query string으로 받지 않는다

목록 페이지는 필터 컨트롤을 렌더링한다.

| 파라미터 | 값 |
|---|---|
| `duty` | 1 게임제작 · 2 사운드·영상제작 · 3 플랫폼 제작 · 4 기술지원 · 5 게임운영·QA · 6 사업기획 · 7 마케팅·미디어 · 8 영업·영업관리 · 9 경영지원 · 10 교육·강의 |
| `orderTab` | 1 추천순 · 2 경력순 · 3 등록일순 · 4 수정일순 · 5 마감일순 |
| `psTab` | 20 · 40 |
| `local` · `divice` · `genre` · `Tabcd` | 지역 · 플랫폼 · 장르 · 기업형태 |

**실측 결과: `Page`를 제외한 어느 것도 query string으로 동작하지 않는다.**

| 요청 | 응답 크기 | 1행 등록일 |
|---|---|---|
| `GI_Total_List.asp` | 364,189 B | 07/03(금) 등록 |
| `?orderTab=3` (등록일순) | 364,189 B | 07/03(금) 등록 |
| `?psTab=40` | 364,189 B | 07/03(금) 등록 |
| `?duty=1` | 364,189 B | 07/03(금) 등록 |
| `?Page=2` | 364,189 B | (다른 공고 40건) |

바이트 단위로 동일하다. 이 컨트롤들은 세션에 POST되고 목록이 세션 상태로 다시
렌더링되는 구조다. 페이지 조각 endpoint(`/recruit/_GI_Job_List?Page=N`)도
같은 세션에 의존해서, 같은 요청이 어떤 때는 106,725 B를 어떤 때는 0 B를
돌려준다.

### 결정

- **목록은 `/List_Gi/GI_Total_List.asp?Page=N`으로 받는다.** 무상태이고
  실측에서 매번 40행을 돌려준다. 조각 endpoint가 3.4배 가볍지만 신뢰할 수
  없다.
- **조기 종료하지 않는다.** 기본 정렬이 추천순이라 범위 밖 공고만 있는
  페이지 다음에 더 새 공고가 올 수 있다. 사람인은 `recruitSort=reg_dt`가
  동작하므로 "범위 밖 페이지가 나오면 중단"이 안전하지만, 여기서는 같은
  최적화가 공고를 조용히 누락시킨다. 회차마다 `--max-pages`를 전부 읽는다.
- **직무 필터는 클라이언트측에서 돈다.** 목록의 `p.info`는 모집분야를 찍지
  않고, 제목 링크의 `GA_Application_Prdt` 추적 호출에 든 첫
  `IsNullOrWhiteSpace(...)` 인자가 유일한 출처다(40행 전부에서 인자 3개, 순서
  고정 확인). 상세 요청을 아끼는 용도이며 정확성 경계가 아니다 — 모집분야를
  못 읽은 행은 **버리지 않고** 남기고 `counts.kept_unknown_category`에
  센다. 저장되는 값은 상세 페이지의 모집분야 행에서 온다.

`--max-pages`를 워크넷·사람인의 20보다 낮은 10으로 둔 이유가 이것이다.

## 3. 본문이 iframe에 있다 — 공고 1건이 최대 3요청

상세 페이지의 `div.job-sub-section__body`에는 본문 텍스트가 없고 iframe이 있다.

| 섹션 | 경로 |
|---|---|
| 담당업무 | `/Recruit/GI_Read_Comt_Ifrm?gno={id}` |
| 자격조건 | `/Recruit/GI_Read_GI_Comment_Ifrm?gno={id}` |

`parse_detail`은 그래서 혼자 `description_text`를 만들지 못한다.
`body_iframe_refs`가 페이지에서 src를 읽고(하드코딩하지 않는다 — 엔드포인트가
바뀌면 잘못된 본문 대신 `PARSE_FAILED`가 된다) crawler가 받아 이어붙인다.
기업정보·기업뉴스 섹션의 iframe은 제외한다: 같은 markup으로 렌더링되지만
공고 본문이 아니라 기업 소개라서, 넣으면 모든 공고 본문과 content hash에 기업
boilerplate가 섞인다.

`--max-body-sections`(기본 4)가 상한이다. 요청 간격을 워크넷 수준으로 낮추지
않는 이유이기도 하다.

이미지 전용 공고가 흔하다 — 담당업무 iframe이 텍스트 없이 업로드된 이미지만
쌓여 있는 경우가 있고, 그때는 `body_status=IMAGE_ONLY`와
`raw_artifact_uri`(절대 URI)로 남는다. 권한 없는 OCR은 하지 않는다.

## 4. 날짜가 네 가지 형태이고 연도가 없다

목록의 등록일 칸:

```text
07/28(화) 등록      연도 없음
38분 전 등록        상대 시각
3시간 전 등록       상대 시각
6일 전 등록         상대 시각
```

마감일 칸: `채용시`(33/40행), `~11/08`, `2026.07.15`.

**등록일과 마감일은 연도를 반대 방향으로 추정한다.** 등록일은 미래일 수 없어서
1월에 본 `12/28`은 지난해다. 마감일은 보통 앞쪽이라 12월에 본 `01/15`는
다음해다. 하나의 추정을 공유하면 공고가 조용히 1년 옮겨진다 —
S15P21E102-148이 마감일을 등록일로 저장한 것과 같은 부류의 결함이다.

상대 시각 때문에 파서가 `now`를 받아야 하고, `CrawlConfig.now`로 고정할 수
있다(JobKorea가 이미 갖고 있는 override). 없으면 fixture 기반 테스트가 실제
시각에 따라 깨진다.

상세 페이지는 정확한 분까지 준다 — `2026-07-03 17:07 등록` /
`2026-09-08 14:02 수정`. `posted_at`은 이 값을 우선하고, 목록 칸은 목록만 받는
실행의 fallback이다. 실측 실행에서 `posted_at`이 `13:43`, `11:03`으로 찍히는
것으로 확인했다.

목록 40행 중 `수정`만 있는 행이 있으므로, 어느 label로 날짜를 매겼는지
manifest의 `listing_date_labels`에 센다.

## 5. 키워드는 수집하되 저장하지 않는다

상세 페이지에는 이 프로젝트가 원하는 그대로의 `키워드` 행이 있다.

```text
영상제작·편집, 서버, MS-SQL, 네트워크, Unreal, Unity, 보안설계,
시스템엔지니어링, 게임프로그래밍, 개발PM
```

**그래도 계약에 넣지 않는다.** `job.contracts.SourceSurface`가
`TITLE | BODY`뿐이라 사이트 자체 태그에서 나온 mention을 기록할 surface가
없고, `BODY`로 저장하면 공고 본문이 하지 않은 말을 했다고 주장하게 된다.
승격하려면 `SITE_TAG` surface 추가라는 계약 변경이 필요하고 그건
S15P21E102-90의 결정이다.

manifest에 개수를 남긴다(`technology_extraction.site_keyword_count`,
`site_keywords_stored: false`). 실측 2건 실행에서 규칙 기반 추출이 4건인 반면
사이트 키워드는 16건이었으므로, 계약 변경의 값은 작지 않다.

## 6. 실측 실행

목록만 (상세·본문 요청 없음):

```text
page 1: 40 rows
records=6 pages=1 invalid=0 detail_errors=0
counts: rows_seen 40, skipped_out_of_range 34, skipped_undated 0, invalid_records 0
listing_date_labels: {"등록": 40}
```

상세·본문 포함, `--duty-preset software`:

```text
records=2 pages=1 invalid=0 detail_errors=0
counts: rows_seen 40, skipped_out_of_range 34, skipped_out_of_preset 4
body_status_counts: {"TEXT_AVAILABLE": 2}
technology_extraction: mention_count 4, site_keyword_count 16
```

본문 1,117자 / 1,008자가 두 iframe에서 이어붙어 들어왔고, 규칙 기반 추출이
`python`, `cpp`, `csharp`를 잡았다. `skipped_out_of_preset` 4건은
모델링·애니메이션 등 아트 직무다.

두 실행 모두 `WEBHDFS_URL`이 없는 환경이라 `raw=skipped`로 로컬 전용 실행이
되었다. **NameNode를 붙인 실제 적재는 아직 검증되지 않았다** — 이 문서에서
확인한 범위는 파싱·정규화·계약 검증과 Raw sink의 미설정 경로까지다.

## 7. 아직 확인되지 않은 사항

- HDFS NameNode를 붙인 실제 Raw 적재. 이 환경에서는 Docker가 내려가 있어
  확인하지 못했다.
- 스케줄러를 통한 `jobs.collected` 발행. S15P21E102-103의 producer가 게임잡
  회차에 대해 실제로 발행하는지는 broker와 -108의 topic 생성 이후로 남는다.
- 하루 2회 스케줄에서의 실효 수집량. 목록 1페이지 40건 중 하루 범위에 드는
  것이 6건이었으므로 10페이지면 명목 400건 대상이지만, 실제 등록 분포와
  `--duty-preset dev` 통과율은 연속 운영 기록이 필요하다.
- 차단 여부. S15P21E102-101의 "7일 연속 수집 중 차단 0회"는 이 사이트에 대해
  아직 측정 구간이 없다.
