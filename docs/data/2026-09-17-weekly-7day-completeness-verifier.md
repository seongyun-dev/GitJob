# Weekly 7-day Stream Completeness Verifier Runbook

이 문서는 `Infra/spark/jobs/weekly_activity_verify.py`의 실행 계약과 순서를
기록한다. 이 verifier는 Weekly aggregation **이전**에 실행하는 read-only
pre-flight이며, Production Weekly 실행이나 Streaming backlog 복구를 수행하지
않는다 (S15P21E102-264 범위).

## 왜 필요한가

`repo_activity_weekly`의 stream 게이트는 **hour 존재 여부**만 본다.

```python
# jobs/repo_activity_weekly.missing_stream_hours
seen = {value for value in observed if isinstance(value, str)}
return tuple(hour for hour in expected_stream_hours(...) if hour not in seen)
```

hour에 행이 한 줄이라도 있으면 그 hour는 "커버됨"이다. 이것으로 충분하지
않다는 것이 2026-09-17 census에서 실측으로 확인됐다.

pre-`S15P21E102-257` publisher는 hour 중간에서 실패했고, 실패 직전까지 ACK된
레코드는 broker에 durable로 남았다. 다음 cron pass는 checkpoint가 없으므로
같은 hour를 처음부터 다시 보냈고, 이 과정이 반복되며 **같은 prefix가 4~12배로
증폭**됐다.

결과적으로 publisher가 checkpoint하지 못한 82시간 중 **80시간이 HDFS에
존재**했다. 게이트는 이를 통과시킨다.

| | WEEK A (`week_start=2026-08-31`) | WEEK B (`week_start=2026-09-07`) |
|---|---|---|
| risk hours | 20 | 62 |
| HDFS에 존재 (게이트 통과) | 20 | 60 |
| expected events | 1,674,237 | 4,915,804 |
| deduplicated in HDFS | 633,972 | 1,993,207 |
| **coverage** | **37.9%** | **40.5%** |
| duplicate rows | 6,209,301 | 9,442,581 |

WEEK A는 누락 hour 0건으로 게이트를 통과하고, **이벤트의 37.9%만 가진 Weekly
결과가 `_SUCCESS`와 함께 산출**된다. 이것이 이 verifier가 존재하는 이유다.

중복 자체는 실패가 아니다. 재전송은 `-102` §4.1이 선택한 trade이고
aggregation이 `DEDUP_KEYS`로 접는다. 실패하는 것은 **짧은 hour**다.

## expected count의 truth source

완전성은 archive만으로 판정할 수 없다. 반드시 source 측 개수가 필요하다.

우선순위:

1. `--expected-counts` — `{hour_key: event_count}` JSON. **우선한다.**
2. `--publish-checkpoint` — publisher checkpoint의 `published[hour].events`

checkpoint가 canonical runtime metadata이지만 **끝난 hour만 기록한다.**
중간에 실패한 hour는 항목 자체가 없으므로, 복구가 관심 갖는 hour는 정확히
checkpoint가 비어 있는 hour다. 그래서 `--expected-counts`가 우선하고, 그것이
없으면 해당 hour는 `UNKNOWN`으로 **fail-closed** 처리된다.

`--expected-counts`의 값은 GH Archive 원본 파일의 줄 수로 만든다. 2026-09-17에
정상 발행된 대조군 5시간에서 `zcat | wc -l` 결과가 publisher checkpoint의
`events`와 **delta 0으로 일치**함을 확인했다.

```
2026-09-08T00  gz_lines 83,301  checkpoint 83,301  delta 0
2026-09-08T01  gz_lines 83,456  checkpoint 83,456  delta 0
2026-09-08T02  gz_lines 81,592  checkpoint 81,592  delta 0
2026-09-08T03  gz_lines 74,609  checkpoint 74,609  delta 0
2026-09-08T04  gz_lines 76,083  checkpoint 76,083  delta 0
```

## hour 분류

| classification | 조건 |
|---|---|
| `COMPLETE` | `deduplicated == expected` |
| `PARTIAL` | `0 < deduplicated < expected` |
| `MISSING` | `deduplicated == 0` (expected > 0) |
| `OVERFULL_AFTER_DEDUP` | `deduplicated > expected` |
| `UNKNOWN` | expected count 없음 |

`OVERFULL_AFTER_DEDUP`은 중복이 아니다. 고유 식별자가 source보다 많다는 뜻이며
재발행으로 설명되지 않으므로 사람이 봐야 한다.

`COMPLETE` 외의 모든 분류는 복구를 막는다.

## PASS 계약

```
missing = 0
partial = 0
unknown = 0
overfull_after_dedup = 0
모든 hour: deduplicated_event_count == expected_event_count
전체 합계: expected_event_total == deduplicated_event_total
duplicate raw rows: 허용하되 수치 보고
```

"hour가 존재한다"만으로 PASS하지 않는다. FAIL이면 종료 코드 1이므로 runbook
단계가 실수로 통과하지 못한다.

## 실행

Spark 자원은 1 core / 1g로 제한한다. C1 archiver가 2 core를 상주 점유하므로
클러스터에 남는 것이 정확히 그만큼이다.

```bash
compose exec -T spark-worker /opt/spark/bin/spark-submit \
  --master spark://100.70.66.38:7077 \
  --total-executor-cores 1 --executor-memory 1g --driver-memory 1g \
  --conf spark.hadoop.fs.defaultFS=hdfs://100.70.66.38:8020 \
  --conf spark.hadoop.dfs.client.use.datanode.hostname=true \
  /opt/gitjob/spark/jobs/weekly_activity_verify.py \
  --input hdfs:///gitjob/parquet/stream/github.events \
  --period-start 2026-09-07T00:00:00Z \
  --period-end   2026-09-14T00:00:00Z \
  --publish-checkpoint /opt/gitjob/state/gharchive-watch/publish-checkpoint.json \
  --expected-counts    /opt/gitjob/state/weekly-expected-counts.json \
  --report-output      /tmp/weekly-verify-2026-09-07.json
```

`--input`은 `fs.defaultFS`가 설정되지 않은 컨테이너에서 `hdfs:///`가
`Incomplete HDFS URI, no host`로 실패한다. 위처럼 `spark.hadoop.fs.defaultFS`를
함께 주거나 authority를 명시한다.

## 전체 7단계 (Jira 목표 1~10)

lineage 증거를 함께 주면 한 번의 실행이 목표 1~10을 모두 판정한다.

```bash
compose exec -T spark-worker /opt/spark/bin/spark-submit \
  --master spark://100.70.66.38:7077 \
  --total-executor-cores 1 --executor-memory 1g --driver-memory 1g \
  --conf spark.hadoop.fs.defaultFS=hdfs://100.70.66.38:8020 \
  --conf spark.hadoop.dfs.client.use.datanode.hostname=true \
  /opt/gitjob/spark/jobs/weekly_activity_verify.py \
  --input         hdfs:///gitjob/parquet/stream/github.events \
  --period-start  2026-09-07T00:00:00Z \
  --period-end    2026-09-14T00:00:00Z \
  --expected-counts /opt/gitjob/state/weekly-expected-counts.json \
  --weekly-output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-09/snapshot={id}/repo_activity_weekly/week=2026-09-07 \
  --weekly-manifest   /mnt/weekly/week=2026-09-07/_SUCCESS.json \
  --observed-row-count  {read-back row count} \
  --observed-row-digest {slice_row_digest value} \
  --export-manifest /mnt/c-export/public={pid}/snapshot={sid}/week=2026-09-07/manifest.json \
  --export-metadata /mnt/c-export/public={pid}/snapshot={sid}/week=2026-09-07/metadata.json \
  --export-data     /mnt/c-export/public={pid}/snapshot={sid}/week=2026-09-07/activity.csv \
  --trend-records   /tmp/trend-records-2026-09-07.json \
  --report-output   /tmp/weekly-verify-2026-09-07.json
```

| 단계 | 목표 | report section |
|---|---|---|
| 1 | source/event completeness (1·2·3) | `input_completeness` |
| 2 | valid repo event + (repo_id, week_start) 재계산 → Weekly output 비교 (4·5·6) | `weekly_output_reconciliation` |
| 3 | `_SUCCESS.json` / row_count / row_digest (7) | `success_manifest` |
| 4 | publication identity (7) | `success_manifest` |
| 5 | C export manifest/metadata/data lineage (8) | `c_export_lineage` |
| 6 | TREND snapshot/head lineage (9) | `trend_lineage` |
| 7 | 전체 PASS/FAIL (10) | `summary.passed` / `result` |

각 section은 `checked` / `pass` / `errors` 를 갖는다. **증거를 주지 않은
section은 `checked=false, pass=false` 이고 전체 리포트를 FAIL시킨다.** 확인하지
않은 것을 통과로 기록하면 리포트의 의미가 없어지기 때문이다.

`--trend-records` 는 `public_snapshot_id`, `registry_version`, 그리고 저장된
TREND 행의 `records` 배열을 담은 JSON이다. read-only 조회 결과를 그대로 넣는다.

### lineage identity 계약

```
Weekly output rows  --(row_count, row_digest)-->  _SUCCESS.json
_SUCCESS.json       --(dataset_snapshot_id, week_start == period)--> C export metadata
C export metadata   --(data_sha256, metadata_sha256)--> C export manifest
PUBLIC_GITHUB head  --(public_snapshot_id, week_start)--> TREND record
```

`worker/weekly_activity_intake` 가 소비 시점에 강제하는 것과 같은 계약이다.
차이는 그 모듈이 첫 위반에서 멈추는 반면 verifier는 **모든 링크를 한 번에
보고**한다는 점이다.

## 복구 순서 (fail-closed)

```
1. 복구 전 verifier 실행
2. 168h completeness 확인
3. PARTIAL / MISSING hour 목록 추출  (report.summary.blocking_hours)
4. 해당 hour만 복구 (publisher replay / redownload)
5. verifier 재실행
6. PASS 후에만 Weekly aggregation 실행
7. aggregation 후 lineage 증거를 붙여 verifier 재실행
8. 전체 PASS 후에만 다음 stage(candidate / Artifact / publication / C export / TREND)
```

각 stage는 이전 stage의 verifier PASS를 전제로만 진행한다. FAIL이면 종료 코드
1이므로 스크립트가 다음 단계로 넘어가지 않는다.

4단계의 실제 실행은 이 문서의 범위가 아니다. Streaming backlog 복구와
Production Weekly 실행은 S15P21E102-296이 담당한다.

## 범위 밖 — production coverage gate

`repo_activity_weekly`의 presence-only 게이트는 이번 작업에서 **변경하지
않았다.** S15P21E102-264의 Out of Scope에 "Weekly business logic 변경"이
명시돼 있다.

현재는 runbook 계약으로 강제한다 — aggregation 전에 verifier가 PASS해야 한다.
production 게이트 자체를 completeness 기반으로 강화하는 것은 별도 Jira로
제안한다.

## 참고

- S15P21E102-257 — publisher oversize/transient 재전송 방지 (증폭의 원인과 수정)
- S15P21E102-296 — 2026-09 Weekly Streaming backlog 복구 및 E2E 운영 실행
- S15P21E102-295 — Historical→Streaming 전환 주차 Weekly 집계 지원
- `docs/data/2026-09-12-repo-activity-weekly.md` — Weekly 집계 계약
- `docs/data/2026-09-15-github-weekly-artifact-trend-runbook.md` — A→C 연결 경로
