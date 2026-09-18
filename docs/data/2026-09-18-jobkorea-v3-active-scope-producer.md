# JobKorea v3 active-scope producer

`S15P21E102-335`. 이 문서는 `--input-format` 이 아니라 **collection mode** 로 갈리는
JobKorea collector 의 두 회차 종류를 적는다. v3 소비 계약은 `S15P21E102-289` 에서
이미 develop 에 있었고, 이 작업은 **생산자** 를 공식 repo 로 옮긴 것이다.

## 왜 별도 mode 인가

legacy 회차는 등록일 기준으로 정렬된 목록을 읽어 **요청한 기간 안** 의 공고만
남긴다. v3 는 기간을 보지 않고 사이트가 **아직 게시 중인** 공고를 duty scope 별로
전부 가져온다. 모집단이 다르므로 계약도 다르다 — 그래서 하나의 상수로 두 회차를
표시할 수 없다.

| | `date_range` (legacy) | `active_listing` (v3) |
|---|---|---|
| 선택 기준 | 등록일이 요청 기간 안 | 사이트가 목록에 올려둠 |
| duty | `--duty-code` 한 개 | `--duty-preset` 의 16개 scope |
| `collector_version` | `jobkorea-crawler/v2` | `jobkorea-crawler/v3` |
| manifest `source.mode` | `category` | `active_listing` |
| manifest `source.duty_scopes` | 없음 | scope 별 코드·역할·종료사유 |
| 기간 밖 조기 종료 | `before_start_date` 로 중단 | 하지 않음 |
| 등록일 미파싱 행 | 선택되지 않음 | **선택됨** (`posted_at=None`) |

## 실행

```bash
# v3 — 고정 16 duty scope 전체 활성 공고
python -m JobKorea_Collector_V1 --duty-preset service-roles \
  --max-pages 300 --output-dir data/jobkorea-active

# legacy — 기존 회차. 인터페이스가 바뀌지 않았다
python -m JobKorea_Collector_V1 --duty-code 1000229 --days-back 1 --max-pages 40
```

`--duty-preset` 을 주면 mode·version·duty_scopes 가 함께 정해진다. 둘을 따로
지정해 어긋나게 만들 수 있는 조합은 없다.

## 16 duty scope

`JobKorea_Collector_V1/duties.py` 의 `SERVICE_ROLE_DUTIES` 가 정본이며 16개 duty
code 를 5개 target role 로 묶는다 — BACKEND 1, FRONTEND 1, AI_DATA 8,
INFRASTRUCTURE 5, MOBILE 1.

이 목록은 **소비 계약과 같은 집합이어야 한다.**
`job.jobkorea_contract.JOBKOREA_V3_DUTY_ROLE_PAIRS` 가 같은 16쌍을 갖고 있고,
`active_snapshot_metadata` 는 manifest 가 보고한 쌍이 그 집합과 정확히 같을 때만
회차를 complete 로 인정한다. 한쪽만 바꾸면 완전히 수집된 회차도 거부된다.
`tests/test_jobkorea_v3_active.py` 가 두 집합의 동일성을 고정한다.

## 완료·실패 판정

scope 마다 종료 사유를 기록하고, 회차 사유는 그것들을 줄여서 만든다.

| scope 종료 사유 | 뜻 | 종결? |
|---|---|---|
| `short_page` | 마지막 페이지가 page_size 미만 | **예** |
| `empty_page` | **2페이지 이상** 에서 빈 응답 = 목록 소진 | **예** |
| `first_page_empty` | **1페이지** 가 빈 응답 | **아니오** |
| `max_pages` | 종료 조건 전에 페이지 상한 도달 | **아니오** |

회차 사유는 scope 가 하나면 그 scope 의 사유를 그대로 쓰고(legacy manifest 가
언제나 그랬다), 여러 개면 **모든** scope 가 종결 사유일 때만
`all_scopes_complete` 가 된다.

### 1페이지 empty 를 성공으로 처리하지 않는 이유

빈 첫 페이지는 **목록이 소진된 것이 아니라 scope 가 응답하지 않은 것** 이다.
차단이거나 markup 이 바뀌어 parser 가 아무것도 읽지 못한 경우가 여기에 해당한다.

이것을 `empty_page` 로 적으면 소비 계약의 `_TERMINAL_SCOPE_REASONS` 가 종결로
인정하므로, **한 scope 를 통째로 못 가져온 회차가 16 duty 전체 모집단을 가졌다고
주장** 하게 된다. 그래서 `first_page_empty` 라는 별도의 비종결 사유를 쓴다 —
생산자에서 fail-closed 이므로 소비 계약을 수정하지 않는다.

legacy(단일 scope) 회차는 기존대로 `JobKoreaHttpError` 를 던진다. 가져올 scope 가
하나뿐인데 그것이 응답하지 않았다면 회차 전체가 의미가 없다. v3 는 나머지 15개
scope 를 계속 수집하고, 대신 그 회차는 complete 를 주장할 수 없다.

## cross-scope 중복

하나의 공고가 여러 duty 목록에 동시에 올라온다. 선택은 `source_posting_id` 를
키로 하는 dict 에 모으므로 raw 행 수와 distinct 공고 수가 갈린다.
2026-09-15 실측: **raw 9,128 행 → distinct 5,859 공고**.

manifest `stats` 에 `raw_rows_seen`, `unique_rows_seen`,
`cross_scope_duplicates` 가 따로 기록된다. `cross_scope_duplicates` 는
`duplicates_skipped` 의 부분집합이며, 같은 페이지를 두 번 읽은 것이 아니라
scope 간 중복이라는 뜻이다 — 회차가 정상일 때도 큰 값이 나온다.

## 등록일이 없는 공고

v3 선택 기준은 "사이트가 목록에 올려둠" 이므로, 등록일 label 을 parser 가 읽지
못해도 공고를 버리지 않는다. 그 경우 `posted_at=None` 이 그대로 흐르고
`ListingRow.posted_on` 은 `None` 이 된다 (`date | None`).

**날짜를 만들어 넣지 않는다.** 공통 normalizer 의 `_as_datetime(None)` 이 `None`
을 돌려주므로 레코드의 `posted_at` 도 비어 있다. 수집 시각으로 채우면 하류에서
실제 등록일과 구분할 수가 없다. 미파싱 행 수는 scope·페이지 단위 warning 으로
남는다.

## Production publication 은 별도 절차

이 문서와 이 코드는 **회차를 재현 가능하게 만드는 것** 까지다. Production
publication 은 이 작업 범위가 아니며 다음이 각각 확인돼야 한다.

- `S15P21E102-333` (COHORT `mapping_context` payload 축소) **배포** 완료
  — merge 만으로는 부족하고 데이터호스트 checkout 에 반영돼야 한다
- publication 직전 양 호스트 disk 실측
- cross-source(JOBKOREA + SARAMIN) 중복 처리 방침 — 별도 Jira.
  `canonical_job_id` 자동 생성이나 fuzzy merge 는 하지 않는다

## Scheduler

`AI/schedule.toml` 의 `jobkorea-morning`/`jobkorea-evening` 은 legacy
`--duty-code` 회차이며 이 작업에서 **바꾸지 않았다**. v3 항목도 추가하지 않았다.

이유는 실측 때문이다 — 2026-09-15 v3 full run 은 **약 11시간 13분** 이 걸렸다.
하루 2회 full scan 은 성립하지 않는다. 그리고 현재 코드에 **incremental 수집
기능은 없다**: `active_listing` 은 scope 마다 목록을 처음부터 훑고, cursor 는
이미 기록한 공고의 **상세 요청만** 건너뛴다(`skipped_already_collected`) —
목록 스캔 자체는 줄지 않는다.

따라서 없는 기능을 가정한 schedule 을 적지 않는다. 지금 지원되는 범위에서
가능한 형태는 다음 정도이며, 확정은 별도 결정 사항이다.

- full v3 baseline 을 낮은 빈도(예: 주 1회)로 두고
- 그 사이 freshness 는 기존 legacy `date_range` 회차로 유지

schedule 을 실제로 켜는 것은 `AI/schedule.toml` 의 선언과 **OS crontab 설치** 두
곳이 모두 필요하다. 2026-09-18 확인 시 crontab 은 설치되어 있지 않았다.
