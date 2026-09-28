# GitHub Streaming 1-hour E2E Canary Runbook (S15P21E102-259)

이 문서는 `S15P21E102-259`의 repository-side 검증 절차다. 한 번에 정확히
한 개의 UTC hour만 대상으로 한다.

```text
GH Archive hour
  → watch checkpoint
  → publisher checkpoint / progress
  → Kafka github.events
  → C1 Spark checkpoint / commit
  → HDFS Streaming Parquet readback
  → offline reconciliation
```

이 runbook은 `S15P21E102-257`의 최종 계약을 전제로 한다.

- `max_request_size`와 pre-send gate는 `1,048,576` bytes다.
- oversized event는 `publish-rejected-events.jsonl`에 durable lineage로 기록하고
  Kafka에는 보내지 않는다.
- transient failure는 마지막 ACK 이후 `publish-progress.json`의
  `next_line`에서 재개한다.
- 정상적인 재시도에서 허용하는 최대 duplicate window는 한 flush chunk인
  `5,000` events다.

현재 변경에서 production 명령은 실행하지 않는다. 특히 watch/publish,
Kafka produce, cron 복구, HDFS write/delete, checkpoint reset/delete,
Connect start/stop, historical resume를 실행하지 않는다.

## 1. Preflight gate

운영자가 캡처한 artifact를 별도 로컬 디렉터리에 둔다. repository 안에
운영 상태를 저장하지 않는다. 아래 파일은 모두 read-only snapshot이다.

```text
<artifact-root>/source.json.gz
<artifact-root>/watch-checkpoint.json
<artifact-root>/publish-checkpoint.json
<artifact-root>/publish-progress.json
<artifact-root>/publish-rejected-events.jsonl
<artifact-root>/kafka-before.json
<artifact-root>/kafka-after.json
<artifact-root>/c1-snapshot.json
<artifact-root>/parquet-readback.json
<artifact-root>/cron-snapshot.json
```

`cron-snapshot.json`은 반드시 다음 형태로 만든다. 빈 `entries`는 확인된
비활성 상태를 뜻하고, 파일 누락이나 `active` 누락은 verifier가 실패시킨다.

```json
{
  "captured_at": "2026-09-14T01:00:00Z",
  "active": false,
  "entries": []
}
```

GH Archive watch/publish entry가 하나라도 active이면 E2E는 fail-closed다.
PASS 전에 cron을 복구하지 않는다.

## 2. Kafka before/after snapshot

`github.events`의 partition별 next offset을 canary 직전에
`kafka-before.json`, canary 및 C1 drain 뒤에 `kafka-after.json`으로 저장한다.
이 repository tool은 Kafka에 접속하지 않고 아래 normalized JSON만 읽는다.

```json
{
  "captured_at": "2026-09-14T01:00:30Z",
  "topic": "github.events",
  "partitions": {
    "0": 123400,
    "1": 90321,
    "2": 77110,
    "3": 120004,
    "4": 81220,
    "5": 99201
  }
}
```

Before/after의 topic과 partition set은 같아야 하고 offset은 감소하면 안 된다.
offset delta가 publisher acknowledged event 수보다 작으면 FAIL이다. 다른
producer가 섞인 경우에도 offset window의 Parquet readback과 source ID
reconciliation이 맞지 않으면 FAIL이다.

## 3. C1 checkpoint / commit snapshot

C1은 Kafka consumer group offset을 사용하지 않는다. Spark checkpoint가
single source of truth이므로, checkpoint를 read-only로 확인해 다음 normalized
JSON을 만든다.

```json
{
  "captured_at": "2026-09-14T01:08:00Z",
  "topic": "github.events",
  "checkpoint_path": "hdfs:///gitjob/checkpoints/c1/github.events",
  "batch_id": 42,
  "committed": true,
  "last_commit": "2026-09-14T01:08:00Z",
  "start_offsets": {"0": 123400, "1": 90321},
  "end_offsets": {"0": 123450, "1": 90371},
  "lag": {"0": 0, "1": 0}
}
```

실제 canary에서는 모든 partition을 포함한다. `committed != true`, commit
marker 누락, checkpoint end offset 불일치, 또는 `lag != 0`이면 즉시 FAIL이다.
`startingOffsets=earliest`를 다시 지정하거나 checkpoint를 reset/delete하지
않는다.

## 4. HDFS Parquet actual readback

C1 commit 이후 다음 read-only Spark helper를 사용해 offset window에 해당하는
Parquet만 읽고 stdout을 `parquet-readback.json`으로 보존한다. helper는
`writeStream`을 시작하지 않고 HDFS에 쓰지 않는다.

```bash
spark-submit Infra/spark/gharchive_e2e_readback.py \
  --topic github.events \
  --parquet-root hdfs:///gitjob/parquet \
  --kafka-before <artifact-root>/kafka-before.json \
  --kafka-after <artifact-root>/kafka-after.json \
  > <artifact-root>/parquet-readback.json
```

기대 형태는 다음과 같다.

```json
{
  "format": "spark.parquet",
  "topic": "github.events",
  "archive_path": "hdfs:///gitjob/parquet/stream/github.events",
  "row_count": 100,
  "distinct_source_id_count": 100,
  "duplicate_source_id_count": 0,
  "source_id_sha256": "...",
  "offset_rows": {"0": {"count": 100, "min": 123400, "max": 123499}},
  "rejected_row_count": 0,
  "rejected_source_ids": [],
  "read_only": true
}
```

`row_count`, partition offset count, distinct count, duplicate count, source ID
digest, C1 reject count를 서로 대조한다. `_rejected/github.events`가
존재하면 같은 offset window의 reject lineage도 읽어서 `rejected_source_ids`에
담는다. C1 readback이 실제 Parquet가 아니거나 archive path가 없으면 PASS로
간주하지 않는다.

## 5. Offline verifier 실행

검증기는 모든 입력을 read-only로 열고 PASS/FAIL JSON만 출력한다.

```bash
PYTHONPATH=AI bash Infra/scripts/gharchive-streaming-e2e-preflight.sh \
  --hour 2026-09-14T01:00:00Z \
  --source <artifact-root>/source.json.gz \
  --watch-checkpoint <artifact-root>/watch-checkpoint.json \
  --publish-checkpoint <artifact-root>/publish-checkpoint.json \
  --publish-progress <artifact-root>/publish-progress.json \
  --rejected-log <artifact-root>/publish-rejected-events.jsonl \
  --kafka-before <artifact-root>/kafka-before.json \
  --kafka-after <artifact-root>/kafka-after.json \
  --c1-snapshot <artifact-root>/c1-snapshot.json \
  --parquet-readback <artifact-root>/parquet-readback.json \
  --cron-snapshot <artifact-root>/cron-snapshot.json \
  --pretty
```

검증 항목:

1. source gzip이 parseable하고 source ID가 unique인지 확인한다.
2. watch checkpoint의 해당 hour가 `complete`/`gzip_valid`인지 확인한다.
3. publisher checkpoint가 `events`/`rejected`를 기록했는지 확인한다.
4. `publish-progress`가 completed hour에 남아 있지 않은지 확인한다.
5. oversized rejection의 `hour`, `source_id`, `bytes`, `limit`, `reason`이
   source와 publisher checkpoint에 맞는지 확인한다.
6. Kafka before/after delta를 계산한다.
7. C1 checkpoint start/end/commit/lag를 확인한다.
8. HDFS Parquet row count와 source ID digest를 확인한다.
9. duplicate amplification을 계산한다. `5,000` 이하만 bounded retry로
   허용하며, 초과하면 FAIL이다.
10. cron active 또는 lag non-zero이면 다른 항목이 맞아도 FAIL이다.

## 6. PASS 기준과 중단 기준

PASS는 verifier의 모든 check가 PASS인 경우에만 허용한다.

- `source → publisher → Kafka → C1 → HDFS` count와 identity가 일치한다.
- oversized event는 Kafka/HDFS accepted 경로에 없고 durable rejection log에
  남아 있다.
- duplicate는 0이거나 한 flush chunk 이내이며 hour 전체 재증폭이 아니다.
- C1 checkpoint commit이 실제 Parquet readback보다 앞서지 않는다.
- Kafka/C1 lag가 0이다.
- watch/publish cron이 inactive다.

어느 하나라도 FAIL이면 canary를 PASS 처리하지 않고, backlog 전체 복구나
cron 복구로 진행하지 않는다. 이 runbook은 historical monthly chain resume나
대량 재발행을 승인하지 않는다.
