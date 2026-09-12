# C GH Archive 활동 추세 계약 (`S15P21E102-201`)

`trend.archive`는 GH Archive의 기간별 repository 활동량과 **현재 고정 commit에서
확인한 양성 기술 관측**을 repository ID로 결합한다. 결과 schema는
`c-gharchive-trend/v1`, 알고리즘은
`c-gharchive-current-evidence-join/v1`이다.

이 결과는 `trend.github`의 Innovation Graph `languages.csv` 계약을 대체하지 않는다.
Innovation Graph의 `num_pushers / UNIQUE_PUSHERS / QUARTER`와 이 결과의
`gh_archive_event_count / EVENTS / WEEK|MONTH`는 출처, 단위와 기간이 다르며 합산하지
않는다.

## 입력 경계

`archive_trend(tech_id, period_inputs, registry, periods=...,
granularity=..., include_partial=False)`는 다음 입력만 받는다.

- `tech_id`: 전달된 `TechnologyRegistry`의 ACTIVE 기술 ID. 요청자가 repository별
  `tech_ids` 또는 `technologies`를 직접 전달할 수 없다.
- `periods`: `MONTH`이면 `YYYY-MM`, `WEEK`이면 월요일인 `YYYY-MM-DD`. 한 결과에 두
  granularity를 섞을 수 없고 기간은 중복 없이 오름차순이어야 한다.
- `ArchiveActivityMetadata`: C가 직접 읽는 immutable CSV/NDJSON export의 URI와
  `source_hash`, 원 A Repo Activity snapshot의 `upstream_source_uri/hash`, A
  schema/version/ID, period, Top-N, selected repository/event 수, valid event 분모 및
  Top-N event coverage. API는 `source_hash`를 export bytes와 비교한다.
- `activity_rows`: A 계약의 `repo_id`, `repo_name`, `event_count`와 월별 `period` 또는
  주별 `week_start`. `repo_id` 중복/null/문자열, 음수 count, metadata와 다른 기간,
  metadata count 불일치를 거절한다.
- `PublicBatchResult`: `github-repo-snapshot/v1`을 C가 Registry로 분석한
  `c-public-repo-analysis/v1`. Registry version과 `include_partial` 선택이 요청과
  정확히 같아야 한다.
- public snapshot URI/SHA-256: URI는 저장된 C artifact ID를 사용한
  `c-compute://snapshot/{stored_PUBLIC_GITHUB_snapshot_id}`, hash는 DB에 저장한
  `PublicBatchResult` payload에 `worker.store.digest()`를 적용한 값이다. stored ID는
  `c- + digest({kind: PUBLIC_GITHUB, owner: null, payload: ...})`이므로 A의
  `dataset_snapshot_id`와 다르다. pure 함수도 wrapper ID와 payload hash를 다시
  비교한다.

2026-03~07은 각 월 Top 10,000, 2026-08은 기존 Top 20,000 snapshot을 재사용할 수
있다. 월별 표본과 분모가 다르므로 각 point에 `selected_repo_count`,
`selected_event_count`, `sample_repo_count`, `sample_event_count`,
`analyzed_repo_coverage`, `analyzed_event_coverage`,
`selection_event_coverage`를 독립적으로 저장한다.

`iter_bounded_activity_file()`은 CSV/JSONL/NDJSON을 한 행씩 읽고 `max_rows` 초과 시
중단한다. API가 read/hash한 동일 bytes를 TOCTOU 없이 파싱할 때는
`iter_bounded_activity_stream(io.StringIO(decoded_bytes), suffix=...)`을 사용한다.
API 프로세스에는 Parquet dependency를 추가하지 않았다.

`Infra/spark/jobs/export_c_archive_activity.py`는 기존 Spark runtime에서 790만 행 수준의
Parquet와 bounded `repo-fetch-candidates/v1`, `github-repo-snapshot/v1` 또는
`c-public-repo-analysis/v1` ID 파일을 broadcast left-semi join한다. 원본 전체 row를
Driver로 collect하지 않고, 선택된 Top-N 이하만 `toLocalIterator()`로 immutable
CSV/NDJSON에 쓴다. 출력에는 `metadata.json`, 그 hash와 data hash를 가진
`manifest.json`이 포함되고 기존 output directory는 덮어쓰지 않는다. 최종
`metadata.source_hash`는 export data hash이고 원 Parquet URI/hash는 upstream lineage로
이동한다. CLI stdout의 `metadata`는 이 최종 `metadata.json`과 같으며 상류 hash를
`source_hash`로 잘못 전달하지 않는다. Linux 게시 경로는 디렉터리 `0555`, 세 파일
`0444`로 확정해 Spark와 UID가 다른 read-only Worker도 경로를 통과해 읽을 수 있게
한다. 원본 전체의
repo/event 분모는 Spark aggregate scalar만 Driver로 가져온다.

Exporter는 요청 `--period`를 무조건 붙이지 않는다. MONTH는 source의 유일한 `period`
값 또는 `period_start/period_end`가 요청 월의 `[월초, 다음 월초)`와 정확히 같은지
검증하고, WEEK는 source의 유일한 `week_start`가 요청 월요일과 같은지 검증한다.
따라서 `period=2026-03-08`인 6개월 aggregate를 `2026-03` 월간 값으로 재라벨하면
실패한다. 월간 추세에는 A가 별도로 만든 월별 Repo Activity snapshot이 필요하다.

예시:

```bash
spark-submit Infra/spark/jobs/export_c_archive_activity.py \
  --input hdfs:///gitjob/parquet/github/repo_activity/period=2026-03/snapshot=.../repo_activity \
  --repo-ids /approved/candidates-2026-03.json \
  --output /approved/c-archive/2026-03/snapshot-001 \
  --period 2026-03 --granularity MONTH --top-n-limit 10000 \
  --source-version spark-repo-activity/v2 \
  --dataset-snapshot-id activity-2026-03-snapshot-001 \
  --source-hash 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

C API는 `C_ARCHIVE_ACTIVITY_ROOT` 아래 relative path만 허용하고 32 MiB 상한 안에서
data bytes를 한 번 읽어 manifest checksum과 비교한 뒤 그 같은 bytes를 stream
adapter에 전달한다. 요청 전체는 64 MiB와 100,000 rows를 넘길 수 없으며, 현재
2026-03~07 월별 Top 10,000과 2026-08 Top 20,000의 최대 70,000 rows를 허용한다.
누적 상한을 넘기면 일부 기간만 집계하지 않고 요청 전체를 거절한다. checksum,
UTF-8, row 계약 위반은 422 입력 오류이고, 신뢰 mount의 누락·권한·I/O 실패는
재시도 가능한 503 `ARCHIVE_INPUT_UNAVAILABLE`이다. 전체 Parquet를 JSON 배열로
받거나 API 메모리에 올리지 않는다.

## 집계 의미

한 period에서 `sample_repo_count`는 활동 row와 결합된
`included_in_denominator=true` public repository 수다. 기본은 collection
`COMPLETE`와 완전한 결과를 사용하며 `REUSED` complete snapshot도 사용할 수 있다.
`PARTIAL`은 public 분석과 archive 요청 양쪽에서 `include_partial=true`를 명시한
경우에만 포함하고 `PARTIAL_COLLECTION_INCLUDED` quality를 남긴다.

public parser v6의 분모 기준은
`ELIGIBLE_REPOSITORIES_WITH_SUPPORTED_ARTIFACT_OR_LANGUAGE`다. hash 검증 뒤 지원 parser가
읽은 artifact 또는 Registry의 `GITHUB_LANGUAGE` mapping과 일치한 A
`language_metadata`가 하나 이상 있어야 한다. 언어 원문·파일 수·대표 경로와
MATCHED/AMBIGUOUS/UNKNOWN 결과를 public record에 함께 보존한다. language metadata만
있는 repository도 매핑이 성공하면 분모와 양성 관측에 포함하고, unknown만 있으면
분모 밖 `INSUFFICIENT_DATA`로 유지한다. 일부 언어가 unresolved이거나 다른 artifact가
미확인이어도 확인된 양성은 보존하되 repository 상태를 `READY`로 높이지 않는다.
이 의미 변경은 `c-public-repo-analysis/v2`와 `c-public-static-observations/v6`로
구분한다. 저장된 v1 결과는 읽을 수 있지만 v5 checkpoint는 v6 실행에 재사용하지 않는다.

`event_count`는 해당 표본 중 **현재 pinned commit에서 기술의 양성 관측이 있는
repository**의 그 기간 GH Archive event 합, `active_repo_count`는 그 중 event가 1개
이상인 repository 수다. 따라서 후보 선정 기간은 과거여도 artifact를 지금 수집한
경우 결과는 과거 기술 도입·사용을 주장하지 않는다. 응답에는
`CURRENT_PINNED_POSITIVE_OBSERVATIONS_ONLY`를 고정한다.

- period 입력 자체가 없으면 metric과 분모는 `null`이며 `MISSING_PERIOD_INPUT`이다.
- eligible parsed 표본은 있으나 target의 양성 관측이 없으면 숫자 `0`이다. 이는
  `ZERO_MEANS_NO_CURRENT_POSITIVE_OBSERVATION`이며 기술 미사용·부재가 아니다.
- `FAILED`, `NOT_FOUND`, artifact 미확인, 표본에서 빠진 repository는 분모와 0 판정에
  넣지 않는다. eligible parsed 표본이 0이면 metric은 `null`이다.
- COMPLETE repository에서도 mapper unresolved 또는 parser/coverage 문제가 있으면
  양성 관측은 보존하되 point는 `INSUFFICIENT_DATA`와 quality reason을 갖는다.

각 point는 activity/public schema와 version, snapshot/run/collector/parser, URI와
hash를 보존한다. 응답 폭증을 막기 위해 artifact 전체를 복제하지 않고 최대 20개의
결정적 evidence example만 `{repo_snapshot_id, repo_id, pinned_commit_sha, path, uri,
content_hash}`로 싣는다. 전체 근거는 `evidence_lookup`의
`public_dataset_snapshot_id + tech_id`로 public snapshot을 조회한다.

## 내부 API 계약

`worker.api.ArchiveTrendCompleted`와 `worker.archive_input.ArchiveTrendFields`는
`POST /internal/v1/c/archive-trends/completed`에서 대용량 row 배열 대신 period별 local
export와 저장된 `PUBLIC_GITHUB` snapshot reference를 받는다.

```json
{
  "schema_version": "c-compute-event/v1",
  "event_id": "archive-2026-03-react-v1",
  "trace_id": "trace-archive-2026-03-react-v1",
  "occurred_at": "2026-09-10T00:00:00Z",
  "tech_id": "react",
  "granularity": "MONTH",
  "periods": ["2026-03"],
  "include_partial": false,
  "inputs": [
    {
      "metadata": {
        "source_schema_version": "repo-activity/v1",
        "source_version": "spark-repo-activity/v2",
        "dataset_snapshot_id": "activity-2026-03-snapshot-001",
        "source_uri": "c-archive-activity://export/activity-2026-03-snapshot-001/activity.ndjson",
        "source_hash": "<activity.ndjson SHA-256>",
        "upstream_source_uri": "hdfs:///gitjob/parquet/github/repo_activity/period=2026-03/snapshot=.../repo_activity",
        "upstream_source_hash": "<A immutable source SHA-256>",
        "period": "2026-03",
        "granularity": "MONTH",
        "top_n_limit": 10000,
        "selected_repo_count": 10000,
        "selected_event_count": 123456,
        "valid_event_count": 500000,
        "total_active_repo_count": 7000000,
        "selection_event_coverage": 0.246912
      },
      "public_snapshot_id": "c-<stored PUBLIC_GITHUB artifact digest>",
      "activity_path": "2026-03/snapshot-001/activity.ndjson"
    }
  ]
}
```

API adapter는 다음 순서로 연결한다.

1. `C_ARCHIVE_ACTIVITY_ROOT` 아래 `activity_path`만 local `Path`로 해석하고 symlink
   escape, absolute path, drive/colon과 역슬래시를 거절한다.
2. data file은 **고정 32 MiB**까지만 한 번 읽고, 그 bytes의 SHA-256을
   `metadata.source_hash`와 직접 비교한다. API는 별도 manifest를 읽지 않는다.
   검증한 동일 bytes를 UTF-8로 decode하여 `iter_bounded_activity_stream()`에
   전달하므로 hash/read 사이 pathname 교체에 노출되지 않는다.
3. stream parser의 절대 상한은 **50,000 rows**다. 이어 pure 집계가 row count/sum,
   duplicate와 `metadata.top_n_limit` 이하 여부를 다시 검증한다. 여러 입력의 누적
   상한은 64 MiB와 100,000 rows이며 초과 입력은 pure 집계 전에 전부 실패한다.
4. `public_snapshot_id`로 DB의 `PUBLIC_GITHUB` payload를 읽어
   `PublicBatchResult.model_validate()`하고 요청 Registry version 및
   `include_partial`을 확인한다. public URI와 payload hash는 서버가 stored artifact와
   payload에서 만들며 request field로 받지 않는다.
5. `ArchiveTrendResult.model_dump(mode="json")`을 기존 `TREND` artifact로 저장한다.
   Innovation Graph 결과와 stream key/source를 구분한다.

전체 evidence 조회가 필요하면 별도 public snapshot 조회에서
`dataset_snapshot_id`, `tech_id`, 선택적으로 `repo_id`로 필터링한다. archive trend
응답에 모든 artifact path를 다시 포함하지 않는다.

## 월별 historical v2 Worker 연결

기존 요청은 `archive_version`을 생략하며 v1 current-HEAD 계산과 기존 request/stream
identity를 그대로 사용한다. 월별 historical 계산만 `archive_version=v2`를 명시하고
각 input에 A의 additive `github-repo-snapshot/v1` 원본 reference를 추가한다.

아래는 기존 필수 metadata를 생략하고 v2 추가 필드만 강조한 요청 발췌다.

```json
{
  "archive_version": "v2",
  "tech_id": "react",
  "periods": ["2026-08"],
  "granularity": "MONTH",
  "inputs": [
    {
      "metadata": {"...": "기존 v1의 전체 ArchiveActivityMetadata"},
      "public_snapshot_id": "c-<PUBLIC_GITHUB snapshot digest>",
      "activity_path": "2026-08/activity.ndjson",
      "a_snapshot_path": "2026-08/github-repo-snapshot.json",
      "a_snapshot_uri": "hdfs:///gitjob/repo_snapshot/2026-08/snapshot.json",
      "a_snapshot_sha256": "<exact A snapshot bytes SHA-256>"
    }
  ]
}
```

두 path는 모두 `C_ARCHIVE_ACTIVITY_ROOT` 아래의 안전한 POSIX 상대 경로여야 한다.
Worker는 symlink escape, drive/colon, 역슬래시와 `..`를 거절하고 exact bytes를 한 번
읽는다. activity는 파일당 32 MiB, A snapshot은 파일당 128 MiB, v2 요청 전체는
256 MiB와 activity 100,000 rows로 제한한다. 각 파일을 열기 전에 남은 전체 byte
budget과 파일 크기를 확인하고, 실제 read도 `min(파일별 한도, 남은 budget)+1`로
제한한다. activity metadata hash, A snapshot
SHA-256, DB의 PUBLIC_GITHUB payload hash를 각각 검증한다.

`C_ARCHIVE_A_SNAPSHOT_URI_ROOT`에는 staging 디렉터리가 mirror하는 불변 HDFS root를
지정한다. Worker는 `a_snapshot_path`를 이 URI root 아래에 붙인 값이 요청의
`a_snapshot_uri`와 정확히 같은지 검증한다. 따라서 올바른 local bytes에 무관한 HDFS URI를
붙여 provenance를 위조할 수 없다. v2에서 이 환경 변수가 없으면 503으로 준비되지 않은
운영 설정을 알리고 계산하지 않는다.

v2는 A snapshot에서 6개 additive SHA lineage 필드만 제거한 copy를 현재
`GitHubRepoSnapshotBatch` 전체 계약으로 먼저 검증한다. 축약 record나 잘못된 collection
state·tree·artifact는 수용하지 않는다. 원본의 additive lineage는 별도로 검증한 뒤 base
record와 다시 결합한다. dataset/pipeline/collector/collection-policy version과 C public
snapshot의 lineage도 같은지 확인한다. repository는
`sha_source=MONTH_EVENT_SHA`,
`pinned_commit_sha == selected_commit_sha == monthly_event_sha`, `target_period`와 public
activity period가 요청 월에 일치하고, A base/public의 repo id·snapshot id·pinned SHA·
activity period가 모두 같을 때만 역사 표본에 포함한다.

- `CURRENT_DEFAULT_HEAD`와 optional lineage가 없는 legacy v1은 현재 관측으로는
  유지하지만 historical v2에서는 `HISTORICAL_HEAD_UNAVAILABLE`로 제외한다.
- commit, snapshot 또는 기간 결합이 다르면 `HISTORICAL_HEAD_MISMATCH`로 제외한다.
- 결과 schema는 `c-gharchive-historical-trend/v2`, algorithm은
  `c-gharchive-monthly-push-head-join/v2`, semantics는
  `HISTORICAL_MONTHLY_PUSH_HEAD_POSITIVE_OBSERVATIONS_ONLY`다.
- matched/unavailable/mismatch repository와 event coverage, 기존 failed/partial/
  unresolved 및 activity/A/public snapshot lineage를 함께 저장한다.

TREND payload는 기존 JSONB snapshot에 저장되므로 DB migration은 필요하지 않다.
request idempotency에는 v2 algorithm version과 A reference가 포함되며, v1은 새 default
field를 request hash에서 제외해 배포 전 retry identity를 유지한다.

## 검증 범위

`AI/tests/test_trend_archive.py`는 월/주 기간, period 혼합·월요일 검증, Registry/period
불일치, repo ID null/중복, actual 0과 missing, FAILED/NOT_FOUND 제외, PARTIAL opt-in,
월별 표본 변화, 임의 client 기술 set 차단, bounded streaming을 합성 fixture로
검증한다. exporter 회귀는 최종 metadata/stdout 계약과 POSIX 게시 mode를 검사한다.
이는 A의 2026-03~08 실제 Parquet read-back, 실제 다른 UID container mount 또는 실제
Top 10k/20k public snapshot 완성을 증명하지 않는다.
