# 채용공고 회차 간 중복 — 원인과 posting identity store

Jira: `S15P21E102-215`
측정: 2026-09-11, 운영 HDFS `/gitjob/raw/{worknet,saramin,career,gamejob}` 전수

---

## 1. 무엇이 문제였나

같은 공고가 회차마다 다시 적재됐다. 수집 레코드 **16,394건 중 2,102건(12.8%)이 재수집분**이다.

| source | 회차 | 레코드 | 고유 `posting_id` | 중복 레코드 | 중복률 |
| --- | ---: | ---: | ---: | ---: | ---: |
| worknet | 7 | 6,133 | 5,230 | 903 | **14.7%** |
| saramin | 5 | 9,100 | 7,905 | 1,195 | **13.1%** |
| gamejob | 2 | 22 | 18 | 4 | **18.2%** |
| career | 1 | 1,139 | 1,139 | 0 | 0% |
| 합계 | 15 | **16,394** | **14,292** | **2,102** | **12.8%** |

career가 0%인 것은 dedup이 동작해서가 아니라 **회차가 1번뿐**이기 때문이다.

재수집된 1,926개 `posting_id` 중

- **1,776개는 `content_hash`가 같다** — 같은 공고를 그대로 다시 받은 순수 낭비
- **150개는 `content_hash`가 바뀌었다** — 내용이 실제로 수정된 공고

두 번째 집합 때문에 "이미 본 id는 버린다"는 단순 dedup은 틀렸다. 그렇게 하면 공고 수정본을 영구히 놓친다.

---

## 2. 원인은 둘이고 서로 무관하다

### 2.1 `Cursor`가 date range에 묶여 있다

4개 수집기 모두 같은 가드를 갖는다.

```python
if (raw.get("start_date") != fresh.start_date
        or raw.get("end_date") != fresh.end_date):
    # A different range: the stored ids say nothing about this run.
    return fresh
```

*resume* 관점에서는 옳다. 2026-09-10의 중단된 회차를 2026-09-09의 페이지 커서로 재개하면 안 된다. 문제는 **일일 스케줄이 매일 새 range를 요청한다**는 점이다. 그래서 매일 첫 회차는 빈 id 집합으로 시작한다.

manifest가 그대로 보여준다.

```text
WORKNET-20260908T003203Z   ids_before=0     skipped=57
WORKNET-20260908T122534Z   ids_before=0     skipped=0      ← 리셋
WORKNET-20260909T022801Z   ids_before=0     skipped=0      ← 리셋
WORKNET-20260909T130027Z   ids_before=260   skipped=254    ← 같은 range, 정상 동작
WORKNET-20260910T050845Z   ids_before=0     skipped=0      ← 리셋
WORKNET-20260910T133656Z   ids_before=295   skipped=290    ← 같은 range, 정상 동작
WORKNET-20260911T001007Z   ids_before=0     skipped=0      ← 리셋
```

`ids_before > 0`인 회차는 **같은 날 두 번째 실행**이다. range가 같으니 커서가 살아남고 dedup이 254·290건을 걸러낸다. 로직은 멀쩡했고, 수명이 하루짜리였을 뿐이다.

### 2.2 collector 컨테이너에 마운트가 없다

```text
docker inspect gitjob-data-collector-1 --format '{{range .Mounts}}...'
→ 0개
find / -name cursor.json  → 없음
```

`--cursor ../data/<site>/cursor.json`은 WORKDIR `/app` 기준으로 `/data/<site>/cursor.json`인데, `/data`가 볼륨이 아니라 컨테이너 파일시스템이다. 컨테이너가 재생성되면 커서도 사라진다.

**볼륨만 붙여서는 2.1이 남는다.** 날짜가 바뀌는 순간 여전히 전부 잊는다. 두 가지를 같이 고쳐야 한다.

---

## 3. 식별자 실측 — 무엇을 identity로 쓸 수 있나

| 확인 | 결과 |
| --- | --- |
| `source_posting_id` 누락 | **0건 / 16,394건** (4개 소스 전부) |
| `source_url` 누락 | **0건** |
| 재수집분에서 `source_url` 변경 | **0건 / 1,926건** |
| 한 URL이 여러 `posting_id`에 매핑 | **0건** |

URL은 안정적이지만 `posting_id`가 전부 존재하므로 fallback으로만 둔다. 실제로 URL은 id를 품고 있다.

```text
worknet  …empDetailAuthView.do?wantedAuthNo=K180412609080001&…
saramin  …/zf_user/jobs/view/popup?rec_idx=54985427
career   …/recruit/view/22139956
gamejob  …/Recruit/GI_Read/View?GI_No=284738
```

따라서 identity는 `source_site` + `source_posting_id`다 — 이미 `normalize.source_record_id_for()`가 만드는 `"{site}:{id}"`. 숫자 id가 사이트마다 겹치므로(worknet `54944929`, saramin `54985427`) 네임스페이스는 필수다.

`content_hash`는 **identity가 아니라 변경 감지기**다. `normalize.content_hash_for()`가 `collected_at`과 run id를 의도적으로 제외하므로 같은 공고는 언제 받아도 같은 해시가 된다.

---

## 4. 무엇을 만들었나

`AI/job/collector/identity.py` — range를 모르는 저장소.

```text
/data/<site>/cursor.json     기존. range 스코프, 페이지 재개용
/data/<site>/identity.json   신규. range 무관, posting_id -> {content_hash,
                             first_seen_at, last_seen_at}
```

판정은 셋뿐이다.

| 상황 | 결정 | 동작 |
| --- | --- | --- |
| `posting_id` 최초 등장 | `NEW` | 레코드 방출, `first_seen_at` 기록 |
| 기존 + hash 동일 | `UNCHANGED` | **방출하지 않음**, `last_seen_at`만 전진 |
| 기존 + hash 변경 | `CHANGED` | **update로 방출**, `last_seen_at` 전진 |

`first_seen_at`은 한 번 쓰고 움직이지 않는다. `last_seen_at`은 `UNCHANGED`에서도 전진한다 — 여전히 목록에 있다는 것 자체가 정보다.

### 4.1 감수한 비용: 재수집분도 detail을 받아야 한다

기존 커서는 **목록 단계에서** skip했다. 요청을 아꼈지만, 그래서 내용이 바뀌었는지 알 수 없었다.

변경을 감지하려면 `content_hash`가 필요하고, 해시는 detail 페이지가 있어야 계산된다. 그래서 판정 지점이 목록에서 **detail fetch 이후로** 내려갔다. 재수집분(약 14%)은 받아보고 버린다.

피할 수 있는 비용이 아니다. 이걸 아끼면 150건의 수정 공고를 영구히 놓친다.

커서는 두 경우 모두 해당 id를 claim한다. 같은 range 안에서는 이미 처리한 공고이므로, 재개된 회차가 다시 받아봐야 같은 결론에 도달할 뿐이다.

### 4.2 영속화 시점

`write_outputs`가 batch를 기록한 **뒤에만** 저장한다. 커서와 같은 규칙이고 같은 이유다 — `S15P21E102-174`에서 커서가 batch보다 먼저 기록되어 사람인 공고 2,337건과 296건을 잃었다. identity store가 같은 실수를 반복하면 재개 회차가 그 공고를 영원히 건너뛴다.

손상된 store는 치명적 오류가 아니라 빈 store로 취급한다. 한 회차 중복이 하루치 수집 실패보다 싸다.

---

## 5. 크기 전망

현재 고유 공고 14,292건. 항목당 약 150 B(id + sha256 + timestamp 2개)이므로

| 시점 | 예상 항목 | 예상 크기 |
| --- | ---: | ---: |
| 현재 | 14,292 | ~2 MB |
| 1년 | 50만~70만 | ~100 MB |

JSON 한 파일로 수 개월은 문제없다. **10만 건을 넘으면** 매 회차 전체를 파싱·직렬화하는 비용이 눈에 띄기 시작하므로 SQLite 전환을 검토한다. 지금 Redis/PostgreSQL로 옮기는 것은 과하다 — 이 저장소는 수집기 안에서만 쓰이고 다른 서비스가 읽지 않는다.

---

## 6. HDFS Raw는 손대지 않는다

과거 15회차 스냅샷은 그대로 둔다. Raw는 원본 바이트의 자리이고 `-190` 검증이 그 파일 수를 센다. 이미 적재된 2,102건의 중복은 **serving/analysis 단계에서 통합**할 문제이지 Raw를 고쳐 지울 문제가 아니다.

dedup은 이 변경 **이후 회차부터** 적용된다.
