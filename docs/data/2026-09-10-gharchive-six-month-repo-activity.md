# S15P21E102-193 GH Archive 6개월 Repo Activity 결과

- Jira: `S15P21E102-193`
- 검증일: 2026-09-09 UTC
- 입력 기간: 2026-03-01T00:00:00Z ~ 2026-09-01T00:00:00Z
- 입력 HDFS: `hdfs:///gitjob/raw/gharchive/dt=2026-03-* ... dt=2026-08-*`
- 최종 상태: **PASS**

## 1. 입력과 최종 Spark 실행

6개월 Raw 4,416개 파일을 Spark standalone에서 분산 집계했다. 실제 최종 성공 application은
`app-20260909135033-0019`이다.

| 항목 | 결과 |
|---|---|
| input files | **4,416** |
| raw events | **660,081,904** |
| Spark application | `app-20260909135033-0019` |
| Spark status | **SUCCESS** (exitCode 0) |
| runtime | **11,408.885초** |
| 종료 시각 | 2026-09-09 17:00:40 UTC |
| 로그 | `.local/gharchive-six-month-analysis/repo-activity-spark.log` |

## 2. Repo Activity 결과

| 항목 | 결과 |
|---|---:|
| rows | **47,466,125** |
| unique repos | **47,466,125** |
| valid repo events | **660,076,996** |
| invalid/null repo events | **4,908** |
| duplicate rank | **0** |
| rank range | **1..47,466,125** |
| readback_top_n_match | **true** |

Top-N coverage는 valid repo events 기준이다.

| Top-N | events | coverage |
|---:|---:|---:|
| 20,000 | 145,693,731 | 22.0722% |
| 50,000 | 182,104,504 | 27.5884% |
| 100,000 | 219,296,133 | 33.2228% |
| 200,000 | 265,480,463 | 40.2196% |
| 300,000 | 297,920,090 | 45.1341% |
| 500,000 | 344,069,676 | 52.1257% |

## 3. HDFS output과 read-back

출력 snapshot은 새로 덮어쓰지 않고 다음 immutable 경로에 존재한다.

`hdfs:///gitjob/parquet/github/repo_activity/period=2026-03-08/snapshot=s15p21e102-193-20260909`

- `repo_activity/_SUCCESS`
- `topn_coverage/_SUCCESS`
- `data_quality/_SUCCESS`
- output parquet files: 5
- HDFS read-back 및 Top-N 재검증: PASS

## 4. watcher 원인과 summary 복원

기존 watcher는 Spark application ID `app-20260909134849-0018`만 고정 검증했다.
해당 ID가 최종 성공 application이 아니어서 실제 HDFS output이 존재함에도
`state=MISSING`으로 chain이 STOP됐다. 최종 성공 결과는 `0019`이며 A를 재실행하지 않았다.

누락됐던 local-only summary는 기존 Spark 결과 로그의 최종 JSON을 읽어 다음 경로에 복원했다.

`/home/ubuntu/workspace/S15P21E102/.local/gharchive-six-month-analysis/repo-activity-summary.json`

복원 과정에서 Raw 재집계·HDFS write·output overwrite는 수행하지 않았다.

## 5. 검증과 후속 경계

- Spark 집계는 Raw 전체를 Driver로 수집하지 않고 분산 aggregate 후 결과 metadata만 기록했다.
- 관련 unit test/lint 결과는 MR 확인 항목에 함께 기록한다.
- 2026-03~08 Top50k Artifact 수집은 후속 `S15P21E102-194` 범위이며 이 문서/브랜치에 성능·ETA·raw-fetch·reuse 분석을 포함하지 않는다.
