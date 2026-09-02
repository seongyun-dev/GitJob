# S15P21E102-109 Repo Activity Top-N 검증 보고서

- 작성일: 2026-09-02
- Jira: S15P21E102-109
- 프로젝트: GitJob
- 목적: 이미 적재된 GH Archive Historical Raw를 Spark로 전량 집계해 Repo 활동량, Top-N 후보, Coverage를 산출하고 immutable Parquet 결과를 검증한다.

## 1. 한 줄 요약

2026년 8월 744개 Raw 파일(87,516,869 events)을 Spark 3.5.3으로 읽어 5,711,133개 Repo를 집계했고, Top-20,000이 valid event의 24.5638%를 포함하는 Parquet 결과를 1,050.916초에 생성·read-back 검증했다.

## 2. 입력 Dataset

| 항목 | 실측값 |
|---|---|
| Historical range | [2026-08-01T00:00:00Z, 2026-09-01T00:00:00Z) (744시간) |
| Raw HDFS path | hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz |
| Input files | 744 (31 partitions × 24 files) |
| Compressed Raw | 10.85 GiB (S15P21E102-105 Dataset 실측) |
| Decompressed Raw | 53.51 GiB (S15P21E102-105 Dataset 실측) |
| Total input events | 87,516,869 |

Spark StructType을 명시했다. 실제 입력에 사용한 최소 필드는 다음과 같다.

~~~text
repo: struct<id:bigint,name:string>
type: string
created_at: string
_corrupt_record: string
~~~

_corrupt_record는 malformed JSON 측정을 위한 Spark corrupt-record 컬럼이며, Repo 집계 키에는 사용하지 않는다. 전체 Repo 결과를 driver로 collect()/toPandas()하지 않았다.

## 3. 집계 정의

- activity_count: 유효한 repo.id와 repo.name을 가진 GH Archive event 행을 1건으로 세어 Repo별 COUNT한다. 별도 dedup이나 Event Type 가중치는 적용하지 않았다.
- grouping key: repo.id (long)
- event type 범위: 모든 GH Archive Event Type (PushEvent, IssuesEvent, PullRequestEvent, WatchEvent, ForkEvent 등)
- repo_name 정책: 먼저 기간 내 이름 충돌을 측정한 뒤, max(struct(created_at, repo_name))으로 가장 최근 created_at의 이름을 선택한다. 동일 시각이면 이름의 사전식 최댓값으로 tie를 해소한다. 따라서 동일 입력에서 재현 가능하며 rename 이후 이름을 보존한다.
- rank: row_number를 사용해 activity_count DESC, repo_id ASC 순으로 전역 순위를 부여했다. 동률에서도 순위가 유일하고 Top-N의 Repo 수가 정확히 N(고유 Repo 수보다 크면 전체)이다.
- period: period_start=2026-08-01T00:00:00Z, period_end=2026-09-01T00:00:00Z (end exclusive)

## 4. Data Quality

| 지표 | 값 |
|---|---:|
| Total input events | 87,516,869 |
| Valid Repo events | 87,516,805 |
| repo.id null | 64 |
| repo.name null | 64 |
| repo.id/repo.name 중 하나라도 null | 64 |
| Malformed JSON | 0 |
| Unique repo.id | 5,711,133 |
| 이름 충돌 Repo 수 (name_count > 1) | 38,726 |
| 이름 충돌 Repo 비율 | 0.678079% (전체 unique Repo 대비) |
| 충돌 Repo에 속한 valid event | 1,056,012 |

repo.id null과 repo.name null 건수는 동일하며, invalid event 수 64와 일치했다. 이름 충돌이 실제로 관측됐으므로 위의 latest-timestamp/lexicographic 정책을 적용했다.

## 5. 구현 구조

~~~text
GH Archive Raw
  → Spark explicit schema read
  → Data Quality aggregation/filter
  → Repo activity groupBy(repo.id)
  → deterministic row_number ranking
  → Top-N event/repo counts
  → valid/total Coverage 및 이전 N 대비 Δ
  → immutable Parquet + read-back validation
~~~

- Spark job: Infra/spark/repo_activity_topn.py
- 실행 wrapper: Infra/scripts/spark-repo-activity-topn.sh
- 순수 함수/경계 테스트: AI/tests/test_repo_activity_topn.py

## 6. Top-N Coverage 실측

coverage_valid = Top-N event count / 87,516,805, coverage_total = Top-N event count / 87,516,869로 계산했다. Δ는 직전 표의 N 대비 coverage 증가폭이며, 표시는 퍼센트포인트다.

| Top-N | Events | Valid Coverage | Total Coverage | Δ Valid | Δ Total |
|---:|---:|---:|---:|---:|---:|
| 100 | 1,490,173 | 1.702728% | 1.702727% | 1.702728pp | 1.702727pp |
| 500 | 3,155,004 | 3.605026% | 3.605024% | 1.902299pp | 1.902297pp |
| 1,000 | 4,641,879 | 5.303986% | 5.303982% | 1.698959pp | 1.698958pp |
| 3,000 | 8,022,231 | 9.166504% | 9.166497% | 3.862518pp | 3.862515pp |
| 5,000 | 10,307,313 | 11.777524% | 11.777516% | 2.611021pp | 2.611019pp |
| 10,000 | 14,859,453 | 16.978971% | 16.978959% | 5.201447pp | 5.201443pp |
| 20,000 | 21,497,460 | 24.563808% | 24.563790% | 7.584837pp | 7.584831pp |

이번 결과는 후보별 비용 측정을 위한 coverage curve이며, 운영 Top-N을 확정하지 않는다.

## 7. Spark Runtime

실행 시각은 2026-09-02 UTC이며, gitjob-s15p21e102-109-repo-activity-topn 애플리케이션이 실제 HDFS 744개 파일을 전량 읽었다.

| 항목 | 실측값 |
|---|---|
| Spark | 3.5.3 (Java 11.0.24) |
| Application ID | app-20260902010624-0004 |
| Master | spark://spark-master:7077 |
| Alive worker | 1 |
| Worker capacity | 2 cores / 2 GiB |
| Executor | 1개, 2 cores, 1 GiB executor allocation (standalone report) |
| Driver memory | spark-submit에서 별도 지정하지 않음; 이 실행에서 유효한 기본값은 별도 노출되지 않음 |
| spark.sql.shuffle.partitions | 200 |
| AQE | true |
| defaultParallelism | 2 |
| Driver-measured wall runtime | 1,050.916초 (약 17분 31초) |

주요 stage 로그에는 Raw scan stage 1(117 tasks, 351.282초), Repo groupBy stage 4(117 tasks, 554.829초), 이후 19-task 집계 stage 6(20.160초)이 기록됐다. 전체 stage 완료 로그는 read-back을 포함해 34개였다.

shuffle read/write 바이트는 Spark History Server/event log를 켜지 않은 baseline 실행이라 수집되지 않았다. 따라서 0으로 추정하지 않고 미수집으로 남긴다.

## 8. Skew 관찰

- 기존 Historical 측정에서 hourly gzip 크기는 약 0.8 MB~77 MB(약 93배)였고 gzip은 non-splittable이다.
- 이번 job의 Raw scan stage는 각각 117 tasks였다. stage 1 task duration은 599~8,772 ms(평균 6,001.8 ms), stage 4는 649~11,801 ms(평균 9,480.6 ms)로 편차가 관측됐다.
- 큰 파일을 처리하는 task가 더 오래 걸리는 입력 크기 편차는 관찰됐지만, 로그 기준 lost/retry/FetchFailed task, 명시적 straggler 실패, spill 로그는 0건이었다.
- Shuffle partition별 read/write와 skew 상세는 event log 미수집으로 확인하지 못했다. 따라서 이번 baseline에서는 이유 없는 repartition/salting/broadcast 최적화를 넣지 않았다.

## 9. Output

출력은 기존 Raw를 수정하지 않고 새 snapshot에 errorifexists로 생성했다. 동일 snapshot이 있으면 job이 시작 단계에서 중단한다.

~~~text
hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=s15p21e102-109-20260902/
├── repo_activity/
├── topn_coverage/
└── data_quality/
~~~

### repo_activity schema

~~~text
repo_id: bigint
repo_name: string
activity_count: bigint
rank: bigint
period_start: string
period_end: string
~~~

### topn_coverage schema

~~~text
top_n: bigint
selected_repo_count: bigint
event_count: bigint
coverage_valid: double
coverage_total: double
coverage_delta_valid: double
coverage_delta_total: double
period_start: string
period_end: string
~~~

### data_quality schema

~~~text
input_path:string
input_file_count:bigint
period_start:string
period_end:string
total_input_events:bigint
repo_id_null_count:bigint
repo_name_null_count:bigint
invalid_repo_event_count:bigint
malformed_json_count:bigint
valid_repo_event_count:bigint
unique_repo_id_count:bigint
repo_name_collision_count:bigint
collision_event_count:bigint
repo_name_collision_ratio:double
~~~

| 검증 항목 | 실측값 |
|---|---:|
| Activity output rows | 5,711,133 |
| Activity unique repo_id | 5,711,133 |
| Null repo_id / activity_count | 0 / 0 |
| Rank min / max | 1 / 5,711,133 |
| Duplicate rank count | 0 |
| Parquet files (전체 snapshot) | 5 |
| Parquet logical bytes | 190,138,207 bytes (약 181.3 MiB) |
| HDFS du -s -h | 181.3 M logical / 544.0 M disk usage |
| Parquet file replication | target 3 / live 1 |
| Coverage read-back | 집계 결과와 Top-N event count 모두 일치 |

5개 Parquet 파일의 HDFS metadata replication은 모두 3이다. Spark worker에서
dfs.replication을 명시하지 않았을 때 해당 경로의 client default replication은
3이었고, parent directory에는 별도 EC policy가 없었다. 따라서 du는 logical size의
약 3배인 544.0 MiB를 replication 반영 사용량으로 표시한다. 단, 현재 DataNode는 1개라
fsck상 6/6 blocks의 Live_repl은 1이고 12 replicas가 부족한 under-replicated
상태다. 즉 target은 3이지만 물리적으로 3개 replica가 존재하는 것은 아니다. NameNode
컨테이너의 현재 dfs.replication 기본값은 1이며 설정은 변경하지 않았다.

실행 직후 Raw를 다시 확인했을 때도 744 files, 10.9 G로 동일했다.

## 10. 검증

- 작은 fixture Spark 실행: 12 events → valid 10, unique Repo 3, collision 1, Top-1/2/10 coverage, Parquet read-back 성공.
- 순수 단위 테스트: 6 passed (AI/tests/test_repo_activity_topn.py)
- 대상 job의 Ruff check/format 검증 통과.
- 실제 HDFS 744-file 실행: exit code 0, input file count 744 확인.
- Parquet read-back에서 schema, row count, unique Repo, null, rank 범위/중복, Top-N event count를 확인했다.
- git diff --check와 secret/PEM 패턴 검사를 최종 변경 파일에 수행했다.

### 기존 repository baseline issue

origin/develop (1a2972d17e1a3ce9f01bb8715f1e97e6b76474bd)의 별도 detached
worktree에서 동일 명령을 실행했다. pytest는 동일한
test_committed_json_schema_matches_contract_model_exactly CRLF/LF mismatch로
145 passed, 1 failed였고, Ruff도 현재 branch와 동일한 I001 8건이었다. 실패 대상
schema의 Git blob은 양쪽 모두 a6242a92eaa6de16a952e2b92c6220558b68fb08이며,
pytest/Ruff 실패 대상 파일은 이번 branch diff에 없다. 따라서 두 결과는
S15P21E102-109가 만든 regression이 아니다.

실측은 실행 중인 spark-worker 컨테이너에 동일한 job 파일을 임시 주입해 수행했다. compose image 자체는 변경하지 않았으므로 merge 후 배포 시 Spark image rebuild가 필요하다.

## 11. 트러블슈팅

1. Spark 이미지의 Python 3.8에서는 datetime.UTC가 제공되지 않아 fixture 실행이 실패했다. 제품 코드에서 timezone.utc를 사용하도록 수정했고 이후 fixture/744-file 실행이 성공했다. 이는 Python 런타임 호환성 문제다.
2. 첫 출력 통계 구현은 local filesystem의 Java listing 결과를 재귀 순회할 때 directory loop로 실패했다. Hadoop FileSystem.listFiles(path, True) iterator로 parquet 파일만 세도록 바꿨고 이후 output file/byte 검증이 성공했다. 이는 검증 보조 코드 문제이며 Raw/출력 데이터는 삭제하거나 덮어쓰지 않았다.

## 12. 하지 않은 범위

이번 Jira에서는 다음을 구현하거나 결정하지 않았다.

- GitHub REST/GraphQL Repo Fetch, Tree/Manifest/Artifact fetch
- 기술명 정규화, Technology Registry/tech_id 매핑, Evidence/LLM 분석
- 최종 API budget 또는 운영 Top-N 확정
- Raw 재수집·수정·삭제, 기존 Parquet Dataset 삭제
- Kafka, Source/Manifest 수집, 추천/트렌드 의미 분석

## 13. 다음 작업

S15P21E102-104에서 위 후보 N별로 다음을 실제 측정해야 한다.

- GitHub API 호출 수와 rate-limit/quota 소모
- Repo별 성공률 및 전체 runtime
- Tree fetch, artifact/source fetch 비용과 bytes/repo
- 실패·retry·응답 크기 분포
- 100/500/1,000/3,000/5,000/10,000/20,000 후보의 비용-coverage 비교

이번 문서의 coverage만으로 운영 N을 확정하지 않는다.

## 14. 최종 판정

- S15P21E102-109: A — MR 가능. 실제 744-file Spark 실행이 exit code 0으로 끝났고, Data Quality, ranking/coverage, immutable Parquet 생성 및 read-back 검증이 완료됐다.
- S15P21E102-104: 진행 가능. 다만 위 Top-N들은 확정값이 아니라 GitHub API 비용을 측정할 후보군이다.
