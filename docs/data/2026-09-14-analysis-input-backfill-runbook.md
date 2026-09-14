# 기존 Raw → analysis_input backfill 실행 Runbook

Jira: `S15P21E102-248`
측정: 2026-09-14, 운영 HDFS 전수 (READ-ONLY)
전제: `S15P21E102-220` 게시 경로가 이미 develop 에 있다 (`0433942`, `07ccc0d`)

> **이 문서를 읽는 시점에 실제 backfill 은 아직 실행되지 않았다.** Production 은 root disk P0 복구 중이고, §5 GO gate 가 전부 충족되기 전에는 `--execute` 를 쓰지 않는다.

---

## 0. 이 backfill 이 만드는 것과 만들지 않는 것

| | 뜻 | 이 backfill |
| --- | --- | --- |
| `HISTORICAL_ANALYSIS_CORPUS` | 과거 Raw 포함. 기술 수요·트렌드·통계 분석용 | **만든다** |
| `CURRENT_ACTIVE_JOBS` | 현재 열려 있는 공고. 사용자 GitHub 기술 매칭·공고 노출용 | **만들지 않는다** |

> **historical backfill 결과를 current active matching corpus 로 그대로 사용하면 안 된다.**
>
> 여기서 게시되는 회차는 2026-09-08 부터의 관측 기록이다. 그 안의 공고가 지금도 열려 있는지는 **이 파이프라인이 답하지 않는다.** 마감된 공고, 내려간 공고, `posting_status` 가 이미 CLOSED 인 공고가 그대로 들어 있다.
>
> 사용자에게 "당신 기술과 맞는 공고" 로 보여주려면 활성 여부 판정이 따로 필요하고, 그것은 이 이슈의 범위가 아니다. 수치도 같은 이유로 조심해서 읽어야 한다 — §2 의 BACKEND 2,130 건은 **historical corpus 에서 분석 가능한 최대 규모**이지 현재 지원 가능한 공고 수가 아니다.

---

## 1. 왜 필요한가

`-220` 은 **앞으로 수집되는** 회차를 게시한다. 수집기가 Raw 업로드에 성공한 직후 `publish_from_env` 를 부르는 구조이므로, 그 코드가 머지되기 **전에** 수집된 회차는 게시되지 않았다.

| | HDFS Raw 회차 | 로컬 `/data` 회차 | analysis_input 게시됨 |
| --- | ---: | ---: | ---: |
| worknet | 13 | 6 | 2 |
| saramin | 10 | 5 | 3 |
| career | 6 | 5 | 1 |
| gamejob | 7 | 5 | 1 |
| **합계** | **36** | **21** | **7** |

**29 회차가 미게시**이고, 그중 15 회차는 로컬 디렉터리조차 없다 — `collector-state` 볼륨(2026-09-11 생성)보다 먼저 수집돼 HDFS 에만 있다. 수집기에게 다시 게시하라고 시킬 수 없는 이유가 이것이고, backfill 이 Raw 를 읽는 이유도 이것이다.

## 2. 무엇이 늘어나는가

```
현재 C 분석 입력   하루 delta 155건 중 BACKEND 15건
Raw 전체           record 17,615  unique(site:id) 14,868   81.8 MiB
dedup 후 BACKEND   2,130건 (본문 확보 1,788건)
```

`build_input_union` 의 최신 관측 선택을 offline 으로 재현해 센 값이다. Historical analysis corpus 에서 BACKEND 후보를 **15건 수준의 최근 delta 분석에서 최대 2,130건 규모로 확장 가능**하다는 뜻이며, **현재 활성 공고 수가 아니다**(§0).

source 별 기여는 고르지 않다.

| source | unique | BACKEND | 비고 |
| --- | ---: | ---: | --- |
| saramin | 8,289 | 2,041 | 대부분이 여기서 나온다 |
| worknet | 5,336 | 81 | `raw_job_category` 가 0% 라 제목 매칭만 걸린다 |
| career | 1,221 | 8 | |
| gamejob | 22 | 0 | 표본이 작아 통계 의미 없음 |

**worknet 의 낮은 비율은 `S15P21E102-247` 이 고친 결함의 흔적이다.** 그 수정은 앞으로 수집될 회차에만 적용된다. 과거 6,446 record 는 정규화된 결과만 Raw 에 있고 원본 HTML 이 없어 **재파싱으로 되살릴 수 없다.** worknet 과거분의 BACKEND 기여는 81건에서 늘지 않는다.

## 3. 명령

```bash
# 데이터 서버 collector 컨테이너 안에서 실행한다.
docker exec gitjob-data-collector-1 python -m job.collector.backfill_cli <옵션>
```

`--execute` 가 없으면 **항상 dry run** 이다. 쓰기는 플래그를 붙여야만 일어난다.

| 옵션 | 뜻 |
| --- | --- |
| `--source {worknet,saramin,career,gamejob}` | 한 source 만. 반복 지정 가능 |
| `--execute` | 실제 게시 |
| `--checkpoint PATH` | 재개 파일. 기록된 회차는 건너뛴다 |
| `--limit N` | N 회차에서 멈춘다 (canary) |
| `--json` | 기계 판독용 요약 |

## 4. 단계별 절차

각 단계는 앞 단계의 성공 조건을 만족한 뒤에만 진행한다.

### 4.1 storage GO gate

- **명령**: `df -h /` (양 호스트), `hdfs dfsadmin -report`, `hdfs fsck /gitjob -files` 요약
- **성공 조건**: §5 의 8개 항목 전부 충족
- **중단 조건**: 하나라도 미충족
- **rollback**: 해당 없음 (읽기만)

### 4.2 전체 dry run

- **명령**: `... backfill_cli --json`
- **입력**: HDFS Raw 전체
- **출력**: `counts` 에 `WOULD_PUBLISH` / `BLOCKED` / `ALREADY_PUBLISHED`
- **성공 조건**: `FAILED` 0건. `WOULD_PUBLISH + ALREADY_PUBLISHED + BLOCKED == 36`
- **중단 조건**: `FAILED` 가 하나라도 있으면 원인 확인 전까지 진행 금지
- **rollback**: 불필요 (쓰기 없음)

`BLOCKED` 는 정상이다. 빈 회차·중단된 회차·`output_sha256` 없는 회차는 C 가 어차피 거부하므로 게시하지 않는다. 각 사유는 출력에 그대로 찍힌다.

### 4.3 예상 record / bytes

- dry run 의 `WOULD_PUBLISH` 회차 수 × 회차당 파일 3개
- 상한: **81.8 MiB** (Raw 전체 크기. 같은 바이트를 한 벌 더 쓰는 것이므로 이보다 커질 수 없다)
- `dfs.replication` 이 1 이면 디스크 증가도 ~82 MiB, 3 이면 ~246 MiB
- **성공 조건**: 서비스 호스트 root 여유가 이 값의 최소 10배

> DataNode4 볼륨이 서비스 호스트 root 에 있다. 2026-09-14 측정 시 그 디스크는 **98% 사용 / 6.4G 여유** 였다. 82 MiB 자체는 작지만, P0 가 해소되지 않은 상태에서 쓰기를 더하지 않는다.

### 4.4 source 하나 canary

- **명령**: `... backfill_cli --source gamejob --execute --checkpoint /data/analysis_input_backfill.json`
- **왜 gamejob 인가**: 회차 7개 / 26 record / 0.1 MiB 로 가장 작다. 실패해도 손상 범위가 최소다
- **성공 조건**: 종료 코드 0, `FAILED` 0건
- **중단 조건**: `FAILED` 1건 이상 → 즉시 멈추고 §4.5 로 검증
- **rollback**: **삭제하지 않는다.** `store_immutable` 이 덮어쓰기를 거부하므로 잘못된 바이트가 들어갈 수 없다. 문제가 있으면 게시본을 지우는 대신 원인을 고치고 재실행한다 (재실행은 `ALREADY_PUBLISHED` 로 수렴)

### 4.5 manifest 검증

- **명령**: 게시 경로의 `manifest.json` 을 읽어 `output_sha256[job_analysis_input.json]` 이 같은 디렉터리 배치 바이트의 SHA-256 과 일치하는지 확인
- **성공 조건**: canary 회차 전부 일치
- **중단 조건**: 하나라도 불일치 → 전체 게시 중단

### 4.6 staging 검증

- **명령**: C 의 `worker.intake.load_job_output` 이 게시본을 받아들이는지 확인 (`job_roots` = `hdfs:///gitjob/analysis_input/jobs/`)
- **성공 조건**: `UNBOUND_LEGACY_MANIFEST` 등 거부 사유 없이 로드됨
- **중단 조건**: C 가 거부 → 게시 게이트와 C 의 수용 기준이 어긋난 것이므로 코드 수정 후 재개

### 4.7 전체 4-source 게시

- **명령**: `... backfill_cli --execute --checkpoint /data/analysis_input_backfill.json`
- **성공 조건**: `FAILED` 0건, `PUBLISHED + ALREADY_PUBLISHED + BLOCKED == 36`
- **중단 조건**: `FAILED` 발생 시 그 회차만 기록하고 계속 진행한다. 종료 후 원인을 보고 재실행
- **rollback**: 없음. 중간에 죽어도 checkpoint 에서 재개하며, 이미 올라간 회차는 불변이다

### 4.8 input_union

- C 의 `poll_once` → `build_input_union` 이 게시본을 관측 합집합에 넣는다
- **A조는 여기 개입하지 않는다.** dedup·최신 선택은 C 책임이다
- **성공 조건**: cohort 의 `input_union.observations` 에 backfill 회차가 나타남

### 4.9 COHORT / DEMAND

- C 조 담당. `as_of` 설정과 함께 C 가 실행한다
- **A조 범위 밖이며 이 runbook 은 여기서 끝난다**

## 5. Production GO gate

전부 충족될 때만 §4.4 이후로 간다.

1. 서비스 호스트 root disk 안정 (P0 해소, 여유가 예상 출력의 10배 이상)
2. Kafka 정상 (broker healthy, 대상 토픽 정상)
3. PostgreSQL 정상 (P0 당시 PANIC 이력 있음)
4. HDFS 정상 (NameNode·DataNode healthy)
5. `hdfs fsck /gitjob` 에서 missing / corrupt **0**
6. DataNode storage 정책 확정 (DataNode4 가 계속 서비스 호스트 root 를 쓰는지)
7. Historical 재개 여부와 자원 충돌 없음
8. §4.3 예상 출력 bytes 산출 완료

## 6. 실패 시 재처리

| 증상 | 처리 |
| --- | --- |
| 중간에 프로세스가 죽음 | 같은 명령을 다시 실행. checkpoint 가 이미 올라간 회차를 건너뛴다 |
| checkpoint 파일 유실 | 그대로 재실행. `ALREADY_PUBLISHED` 로 수렴하고 바이트는 바뀌지 않는다 |
| 한 회차만 `FAILED` | 나머지는 이미 처리됐다. 원인(대개 WebHDFS 일시 오류) 해소 후 재실행 |
| 게시본이 Raw 와 다르다고 의심 | `store_immutable` 이 다른 바이트를 거부하므로 구조상 불가능하다. `manifest.output_sha256` 으로 확인 |

## 7. 하지 않는 것

- 기존 Raw 회차 수정·삭제 — Raw 는 불변이고 `-190` 검증이 파일 수를 센다
- 통합본(current/upsert) 생성 — `build_input_union` 이 C 쪽에서 한다
- JobKorea 게시 — `-230` 결정에 따라 Raw 에만 남긴다. backfill 의 source 목록에 없다
- COHORT / DEMAND snapshot 생성 — C 조 범위
