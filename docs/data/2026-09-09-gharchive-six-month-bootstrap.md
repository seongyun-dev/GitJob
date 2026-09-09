# GH Archive 6개월 Historical Bootstrap 검증

- Jira: `S15P21E102-179`
- 대상 환경: `J15E102A`
- 검증일: 2026-09-09
- 대상 기간: `2026-03-01T00:00:00Z` 이상, `2026-09-01T00:00:00Z` 미만
- HDFS Raw: `hdfs:///gitjob/raw/gharchive/dt=YYYY-MM-DD/*.json.gz`
- 상태: **Historical Bootstrap 및 Spark 전량 집계 Runtime 검증 완료**

## 1. 목적과 범위

기존 2026-08 GH Archive Historical Dataset을 유지하면서 2026-03~07 Raw를
동일 HDFS namespace에 추가해 6개월 연속 입력을 확보했다. 2026-08 Raw는 다시
다운로드하거나 overwrite하지 않고 기존 검증 결과를 재사용했다.

이번 작업은 A조의 Raw 수집·검증과 Spark read-only event count까지다. Repo Activity,
Top-N, Weekly/Monthly Activity, Artifact Fetch, 기술 의미 판정은 수행하지 않았다.

## 2. 최종 Dataset

| 월 | expected files | HDFS files | compressed bytes | decompressed bytes | Spark events | 처리 |
|---|---:|---:|---:|---:|---:|---|
| 2026-03 | 744 | 744 | 28,686,728,512 | 153,382,973,605 | 116,247,544 | 신규 적재 |
| 2026-04 | 720 | 720 | 26,298,491,449 | 141,939,489,790 | 108,985,876 | 신규 적재 |
| 2026-05 | 744 | 744 | 21,257,111,736 | 107,929,596,096 | 112,261,316 | 신규 적재 |
| 2026-06 | 720 | 720 | 16,383,304,260 | 82,343,506,692 | 112,240,168 | 신규 적재 |
| 2026-07 | 744 | 744 | 15,866,856,716 | 79,242,577,071 | 122,830,131 | 신규 적재 |
| 2026-08 | 744 | 744 | 11,654,413,308 | 57,458,023,922 | 87,516,869 | 기존 Dataset 재사용 |
| **합계** | **4,416** | **4,416** | **120,146,905,981** | **622,296,167,176** | **660,081,904** | **완료** |

- 압축 총량: 120,146,905,981 B = 약 111.90 GiB
- 해제 총량: 622,296,167,176 B = 약 579.56 GiB
- HDFS의 압축 총량은 2026-09-09 최종 listing을 다시 합산했다.
- 2026-03~07 해제 총량은 각 월 `validate` 결과, 2026-08 해제 총량은 기존
  744시간 전수 gzip 검증 기록을 사용했다.

## 3. 수집·적재 무결성

2026-03~07의 월별 `download` / `validate` / `upload` 결과는 모두 다음 조건을
만족했다.

- expected와 completed가 일치
- missing `0`
- invalid `0`
- download/upload failed `0`
- 신규 3,672시간 checkpoint 상태 전부 `complete`
- 각 월 `published_bytes`와 HDFS 최종 compressed bytes 일치

HDFS 최종 listing에서 2026-03~08 경로와 파일명을 다시 대조한 결과다.

| 항목 | 결과 |
|---|---:|
| expected hours | 4,416 |
| HDFS target files | 4,416 |
| 유효한 고유 hour | 4,416 |
| missing | 0 |
| duplicate hour | 0 |
| unexpected path/file | 0 |

### 2026-08 재사용 근거

- `S15P21E102-105`에서 이미 검증한 2026-08 Dataset은 744 files,
  11,654,413,308 compressed bytes, 57,458,023,922 decompressed bytes다.
- 최신 `develop`의 `docs/data/README.md` §14.1에는 같은 날 다른 HDFS volume
  namespace에서 이 Dataset이 보이지 않았던 중간 관측이 기록돼 있다. 최종 검증은
  현재 active `gitjob-data-hdfs-namenode-1`을 기준으로 다시 수행했다.
- 현재 active HDFS에서 첫 파일과 마지막 파일 mtime은 각각
  2026-09-01 06:34:15 UTC, 07:14:20 UTC다. `S15P21E102-179`의 2026-03~07
  upload 시각인 2026-09-09보다 앞서므로 `-179`에서 다시 올린 파일이 아니다.
- `S15P21E102-179` checkpoint는 2026-03-01~2026-07-31의 3,672시간만 가지며
  전부 `complete`다. 2026-08 신규 download/upload 기록은 만들지 않았다.
- 최종 HDFS read-only 조회에서 2026-08은 기존 값과 동일한 744 files,
  11,654,413,308 bytes였다.
- 따라서 2026-08은 재다운로드·재업로드·overwrite 없이 기존 Raw를 그대로
  **REUSED**한 것으로 확인했다.

## 4. Spark 전량 event count

6개월 Raw 전체를 Spark standalone cluster에서 분산 read하고 파일 경로에서 월을
추출한 뒤 `groupBy("month").count()`로 집계했다.

| 항목 | 결과 |
|---|---|
| application name | `s15p21e102-179-six-month-event-count` |
| Spark application ID | `app-20260909100853-0017` |
| input files | **4,416** |
| total events | **660,081,904** |
| 최종 상태 | **SUCCESS** |
| exception/error | 없음 |
| 관측 시작 시각 | 2026-09-09 10:08:44 UTC / 19:08:44 KST (tmux 생성) |
| 종료 시각 | 2026-09-09 12:50:27 UTC / 21:50:27 KST |
| 관측 실행 시간 | 2시간 41분 43초 |
| 실행 로그 | `.local/gharchive-six-month-179/spark-event-count.log` |

실행 스크립트의 `.collect()`는 Raw 전체에 적용되지 않는다. 파일별 월을 계산하고
`groupBy` / `count` / `orderBy`가 끝난 뒤 월별 결과 최대 6행만 Driver로 가져온다.
이번 검증에서 Driver로 전체 Raw를 모으는 동작은 없었다.

실행 로그에는 `started_at`, `finished_at`, `duration`, `success/error`를 하나의
구조화된 summary로 남기지 않았다. 최종 result와 Spark 종료 로그는 충분하지만,
해당 metadata는 후속 실행 도구의 관측 가능성 개선 사항이다.

## 5. HDFS health와 용량

2026-09-09 13:10 UTC에 `/gitjob/raw/gharchive`를 read-only로 다시 검사했다.

| 항목 | 결과 |
|---|---|
| fsck | **HEALTHY** |
| missing blocks | 0 |
| corrupt blocks | 0 |
| under-replicated blocks | 0 |
| HDFS Configured Capacity | 995,138,396,160 B / 926.79 GB |
| HDFS DFS Used | 122,591,576,064 B / 114.17 GB / 32.60% |
| HDFS DFS Remaining | 253,403,418,624 B / 236.00 GB |
| host filesystem | `/dev/root`, 309G total / 231G used / 79G available / 75% |
| host exact available | 84,467,802,112 B |

세 DataNode는 같은 물리 host filesystem을 사용하므로 HDFS Configured Capacity를
물리 가용량으로 해석하지 않는다. 운영상 여유 공간 판단은 host `df`의 79G를
기준으로 한다.

## 6. 검증 근거와 재현성

서버의 Git tracked 경로에는 실행 산출물을 만들지 않았다. 아래 local-only 결과를
읽어 문서화했다.

- `.local/gharchive-six-month-179/2026-03-{download,validate,upload}.json`
- `.local/gharchive-six-month-179/2026-04-{download,validate,upload}.json`
- `.local/gharchive-six-month-179/2026-05-{download,validate,upload}.json`
- `.local/gharchive-six-month-179/2026-06-{download,validate,upload}.json`
- `.local/gharchive-six-month-179/2026-07-{download,validate,upload}.json`
- `.local/gharchive-six-month-179/checkpoint.json`
- `.local/gharchive-six-month-179/spark-event-count.log`

HDFS 검증은 `dfs -count`, recursive listing, `fsck`, `dfsadmin -report` 조회만
사용했다. 최종 확인 과정에서 HDFS write, Raw 삭제, overwrite, 재다운로드 또는
재업로드를 수행하지 않았다.

## 7. 완료 조건 대조

| Jira 완료 조건 | 결과 |
|---|---|
| 2026-03~08 결번 없이 확보 | 충족: 4,416/4,416 |
| 2026-08 중복/overwrite 없음 | 충족: 기존 744시간 REUSED |
| 월별 files/events/용량 | 충족 |
| 전체 files/events/용량 | 충족 |
| HDFS read-back / Spark read | 충족: 4,416 files 전량 Spark 집계 성공 |
| checkpoint/replay/idempotency 유지 | 충족: 신규 3,672시간 complete, 기존 8월 유지 |
| HDFS 사용량/남은 용량 기록 | 충족 |
| 결과 문서화 | 이 문서와 `docs/data/README.md`에 반영 |

## 8. 후속 작업

- 6개월 Repo Activity와 Top-N 집계
- 6개월 Weekly/Monthly Activity 집계
- Spark Worker 1 vs 3 benchmark
- Spark 실행 summary의 시작/종료/소요시간/success/error metadata 구조화

위 후속 작업은 이번 `S15P21E102-179` 변경 범위에 포함하지 않는다.
