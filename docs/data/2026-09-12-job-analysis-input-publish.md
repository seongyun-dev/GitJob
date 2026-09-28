# 채용공고 A→C analysis_input 게시

- Jira: `S15P21E102-220`
- 선행: `S15P21E102-99`(Raw 적재), `S15P21E102-215`(회차 간 dedup), `S15P21E102-219`(collector-state 권한)
- 기준일: 2026-09-12
- 상태: **A publish 구현됨 · Unit test 검증됨 · Runtime 미검증** / **C 배선은 blocker**

## 1. 문제

C조가 채용공고를 쓰려면 `hdfs:///gitjob/raw/<source>/dt=.../<RUN_ID>/`를 직접 뒤져야 했다.
Raw는 일어난 일의 기록이라 일찍 멈춘 회차, 0건 회차, 상세 수집이 실패한 회차까지 전부 남는다.
C가 그 안에서 쓸 수 있는 회차를 스스로 골라야 하고, 고르는 규칙이 A와 C 양쪽에 생긴다.

## 2. 결정

검증을 통과한 회차만 고정 경로에 한 번 더, 불변으로 게시한다.

```
Raw     hdfs:///gitjob/raw/<source>/dt=YYYY-MM-DD/<RUN_ID>/     (그대로 유지, 수정 없음)
Publish hdfs:///gitjob/analysis_input/jobs/<source>/<RUN_ID>/   (신규)
```

파일은 회차가 쓰는 세 개 그대로다 — `job_analysis_input.json`, `postings.csv`, `manifest.json`.
GitHub 쪽이 이미 `analysis_input/github/repo_snapshot/`에 게시하므로 jobs는 그 형제 namespace를 쓴다.

`dt=` 파티션을 두지 않았다. Raw는 영구 누적이라 정리 경계가 필요하지만, 이 경로는 source별 root
하나 아래의 회차 디렉터리를 나열해 읽는 소비자가 대상이라 층을 더하면 그 나열만 깊어진다.

## 3. A는 게시만 한다 — 통합본을 만들지 않는다

이 작업은 **current/upsert 통합본을 만들지 않는다.** 최신/중복/`as_of` 판정은 C 책임이다.

`docs/ai/c-compute-runtime.md`가 "자동 실행은 지정된 roots 의 검증된 완료 입력 관측 합집합을
C에서 만든다. A에 새로운 통합 batch 를 요구하지 않는다"로 정하고 있고,
`AI/job/input_union.py`의 `build_input_union`이 `source_record_id`·`collected_at` 기준으로
`SELECTED`/`SUPERSEDED`/`DUPLICATE`/`AFTER_AS_OF`를 이미 판정한다. 그 코드는 건드리지 않았다.

## 4. 게시 조건

`AI/job/collector/analysis_input.py`의 `release_blockers()`가 게시 전에 회차를 검사하고,
하나라도 걸리면 **바이트를 하나도 올리지 않고** 거부한다.

| 코드 | 뜻 |
|---|---|
| `MISSING_FILE:<name>` | 세 파일 중 하나가 없다 |
| `MANIFEST_UNREADABLE` | manifest가 JSON 객체가 아니다 |
| `MANIFEST_OUTPUT_MISMATCH` | `outputs`가 고정 sibling 이름을 가리키지 않는다 |
| `UNBOUND_LEGACY_MANIFEST` | `output_sha256`이 없다 |
| `BATCH_CHECKSUM_MISMATCH` | `output_sha256[batch]`가 실제 batch 바이트와 다르다 |
| `IDENTITY_MISMATCH` | manifest의 `source_site`/`pipeline_run_id`가 회차와 다르다 |
| `COLLECTOR_STOPPED_EARLY` | `stopped_reason`이 있다 |
| `DETAIL_COLLECTION_FAILED` | `counts.detail_errors > 0` |
| `INVALID_SOURCE_RECORDS` | `counts.invalid_records > 0` |
| `EMPTY_RUN` | `counts.records <= 0` (SUCCESS_EMPTY여도 analysis_input에는 게시하지 않는다) |

정상 empty run은 collector/scheduler 관점에서는 SUCCESS_EMPTY이다. 다만 C가 계산할
입력은 하나 이상의 검증된 공고 record를 전제로 하므로, analysis_input의 EMPTY_RUN은
collector 장애가 아니라 0-row publish를 막는 별도의 release blocker로 유지한다.

이 목록은 `AI/worker/intake.py`의 `load_job_output`이 거부하는 것과 같은 규칙이다. C가 거절할
회차를 A가 `analysis_input`에 올려 두면, 그 경로가 하는 유일한 약속이 그 자리에서 깨진다.
`worker`를 import하지 않고 다시 적은 이유는 그쪽이 C의 패키지이고 psycopg를 끌어오는데
collector 이미지에는 그것이 없기 때문이다.

게시 후에는 세 파일을 다시 읽어 로컬 바이트와 그대로 비교한다(read-back). `raw_verify`는 길이만
확인하는데, 그쪽은 보관 점검이라 34MB batch를 매번 다시 읽을 값어치가 없고 이쪽은 회차당 한 번
인수인계 자체를 보증하기 때문이다.

## 5. 멱등성

업로드 루프는 새로 만들지 않고 `raw_sink.upload_run_files`로 추출해 Raw와 공유한다. 두 경로가
같은 불변성 규칙을 쓰도록 강제하는 것이 목적이다. 그 아래는 기존 `WebHdfsClient.store_immutable`
이며 계약은 이렇다.

- 같은 `RUN_ID` + 같은 내용 → `unchanged`. 아무것도 쓰지 않고 통과한다.
- 같은 `RUN_ID` + 다른 내용 → 거부(`object exists with different content`). 기존 게시본은 그대로 남는다.
- overwrite 없음. 임시 파일에 올린 뒤 `RENAME`으로 원자적으로 붙인다.

회차 디렉터리에는 `analysis_input_publish.json`을 남긴다(`raw_upload.json` 옆). 업로드되지 않으며,
거부된 경우에도 `blockers`와 함께 기록한다.

## 6. 자동 흐름

```
Crawler 실행 → 로컬 회차 디렉터리 → Raw 업로드(성공) → 게시 조건 검사 → analysis_input 게시 → read-back
```

4개 crawler(`Worknet`·`Saramin`·`Career`·`GameJob`)가 Raw 업로드 직후 같은 프로세스에서
`publish_from_env()`를 호출한다. 별도 스케줄 단계로 떼지 않은 이유는, 떼면 반쯤 쓰인 회차
디렉터리를 대상으로 돌 수 있기 때문이다. 게시 거부는 정상 결과이며 수집을 실패로 만들지 않는다.
게시 실패(HDFS 오류·read-back 불일치)는 Raw 실패와 같이 exit 1로 스케줄러에 드러낸다.

`WEBHDFS_URL`이 없으면 Raw와 마찬가지로 건너뛴다. 루트는 `ANALYSIS_INPUT_JOBS_ROOT`로 바꿀 수 있다.

## 7. C 배선 — blocker

**Jira `-220`의 "C조 배선" 서술은 현재 코드와 맞지 않는다.** 티켓은

> `AI/worker/intake.py`의 `job_roots`를 `hdfs:///gitjob/analysis_input/jobs/`로 설정하면 기존
> `poll_once`/`build_input_union`이 그대로 동작한다

라고 적었지만, 실제 코드는 그렇게 동작하지 않는다.

**근거 1 — `job_roots`는 로컬 경로 전용이다.** `IntakeConfig.job_roots`는 `tuple[Path, ...]`이고
validator가 이렇게 강제한다.

```python
for root in self.job_roots:
    if (not root.is_absolute() or not root.is_dir()
            or root.is_symlink() or root.is_junction()):
        raise ValueError("input roots must be existing absolute directories")
```

`hdfs:///...` 문자열은 `is_dir()`에서 탈락해 **설정 검증 단계에서 거부된다.** 이어지는 읽기도 전부
로컬 API다 — `_manifests()`는 `os.scandir`, `load_job_output`은 `Path.stat()`/`open()`.

**근거 2 — 탐색 깊이가 한 단계다.** `_manifests()`는 root 자신과 root 바로 아래 디렉터리에서만
`manifest.json`을 찾는다. 따라서 로컬로 마운트하더라도 `.../jobs` 하나를 root로 주면
`jobs/<source>/<RUN_ID>/manifest.json`은 **두 단계라서 발견되지 않는다.** source별로 4개 root를
줘야 한다(`job_roots`는 최대 32개).

**근거 3 — HDFS→로컬 경로가 존재하지 않는다.** 조사 결과:

| 확인한 것 | 결과 |
|---|---|
| `worker` 서비스 volumes (`Infra/compose/compose.yaml`) | **없음** — 마운트가 하나도 없다 |
| collector ↔ worker 공유 볼륨 | 없음. `collector-state`는 collector에만 붙는다 |
| HDFS fuse mount / materialization 스크립트 | 없음 |
| WebHDFS download 경로 | 있으나 **GitHub 전용** — `public_sources` → `ReadOnlyWebHdfsReader` → `github.snapshot_input.load_published_snapshot`. 공고 batch를 읽지 않는다 |

`docs/ai/c-compute-runtime.md`는 job 입력을 **호스트 bind mount**로 규정한다
(`/input/jobs/saramin`, `/input/jobs/worknet` read-only). 그 마운트는 현재 compose에 없다.

### 선택지 — 결정 필요

| 안 | 내용 | 대가 |
|---|---|---|
| A | C intake에 공고용 WebHDFS 경로 추가(`public_sources`의 jobs판) | **C 코드 변경.** A조 범위 밖이며 C 소유 |
| B | HDFS→로컬 materialization 단계 추가 후 그 디렉터리를 mount | **새 동기화 계층.** 승인 없이 만들지 않았다 |
| C | collector가 로컬에도 게시 디렉터리를 쓰고 worker에 mount | C가 A의 작업 디렉터리를 읽게 된다. 불변 게시본을 읽는다는 이 작업의 취지와 어긋남 |

A publish는 이 결정과 무관하게 값어치가 있다. 게시본은 C가 무엇으로 읽든 같은 불변 경로에 있고,
Raw를 뒤지는 일이 사라진다. 그래서 게시만 먼저 구현하고 배선은 분리했다.

## 8. 검증

### 로컬에서 검증됨

- `python -m pytest tests/test_job_analysis_input.py tests/test_job_raw_sink.py tests/test_raw_verify.py tests/test_job_collector.py -q` → **112 passed**
  - 신규 26건: 경로 형태·traversal 거부, 3파일 게시와 read-back, manifest 마지막 게시 순서,
    같은 내용 재게시 `unchanged`, 같은 RUN_ID 다른 내용 거부 및 기존 게시본 보존,
    게시 조건 7종이 각각 **업로드 0바이트**로 차단, checksum 불일치 차단, 파일 누락 차단,
    read-back 불일치 보고, 업로드 실패가 raise 대신 반환, env 스위치, 로컬 기록 파일
- `ruff check` 통과. `ruff format`은 4개 crawler에 기존 부채가 있어(develop에서도 동일) 돌리지 않았고,
  추가한 블록이 부채를 늘리지 않는 것은 develop 원본과 diff 라인 수를 비교해 확인했다.

### 미검증 — Runtime

실제 WebHDFS·크롤링은 **수행하지 않았다.** 개발 PC가 관리자망(Tailscale)에 접근할 수 없어
NameNode에 도달하지 않고, 4개 source의 실제 수집도 돌리지 않았다. 따라서 다음은 미검증이다.

- 실제 NameNode에 대한 게시·read-back
- 4개 source의 실제 회차가 게시 조건을 통과하는지
- 운영 회차 디렉터리의 manifest가 여기서 가정한 필드 구성과 일치하는지

서버에서 확인할 때는 회차 하나를 골라 `analysis_input_publish.json`의 `blockers`가 비어 있고
`read_back`이 3건인지 보면 된다.

## 9. 후속

- C 배선 선택지 A/B/C 결정 후 별도 티켓
- 결정 후 `docs/ai/c-compute-runtime.md`의 job 입력 절에 실제 경로 반영(C 소유 문서)
- Runtime 검증 후 이 문서 8장 갱신
