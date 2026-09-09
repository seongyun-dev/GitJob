# C MVP 검증 결과와 서비스 인수

> 상태: 완료된 로컬 구현의 검증 기록. 운영 배포·B/FE 인수 완료 보고서가 아님
>
> 기준일: 2026-09-08 · Jira: S15P21E102-29/31/33/36/88/160
>
> 처음 읽는 경우: [C조 구현 안내](README.md)

## 1. 이 기록의 기준

구현 브랜치 `feat/S15P21E102-33-branch`의 `ce4c24f801fe9c1f88f5caf13084620f2e6d082b`까지를 기준으로 한다. 기준점 `edfa96db1e75c45931c3b08cc2408b7b8fa26a5b` 이후 기능별 로컬 커밋 25개, 변경 파일 78개다. 이후 문서 편집을 위한 새 실행 결과나 현재 원격/배포 상태를 뜻하지 않는다.

2~6절은 위 초기 기준의 기록이다. 후속 리뷰 보완은 7~8절, 최신 월별 집계 분리와 전체
**1060개** 검증 결과는 9절을 확인한다. 각 절의 원본 데이터·코드 버전을 구분한다.

9/8 구현 검증 당시 push·MR·merge·배포를 하지 않았다. 원래 develop checkout은 변경하지 않았고 테스트 Worker/DB는 검증 후 중지했다. 이미지·테스트 DB·원본 검증 자료는 보존했다.

원시 실행 JSON, 실제 수집 원문, 개인 PC의 테스트 주소/설정은 저장소 밖 검증 workspace에 보존한다. 이 팀 문서는 읽을 수 있는 결과 요약과 코드·테스트·재현 조건을 제공하며 개인 PC 파일을 팀 공용 경로인 것처럼 링크하지 않는다.

## 2. 무엇을 실제로 검증했나

| 검증 층 | 실행 결과 | 이 결과로 주장할 수 없는 것 |
|---|---|---|
| 전체 AI 테스트 | Python 3.12.14, 실제 격리 PostgreSQL 포함 **973 passed / 0 failed / 0 skipped**, 의존성 deprecation warning 2개 | B 실제 귀속 정확도·운영 서비스 완성 |
| 정적 검증 | 후속 변경 Python 39개 Ruff check/format, base..HEAD diff check PASS | 저장소 전체 lint가 깨끗하다는 주장 |
| 이미지·설정 | Worker Docker build/startup, 테스트 환경값을 사용한 Compose config PASS | 운영 환경·비밀값·권한·네트워크 준비 |
| DB 호환 | 기존 public 베이스라인 13개 테이블 후 C migration 2회 적용, 기존 열 불변·별도 C 4개 테이블 확인 | 운영 DB migration 수행 |
| HTTP·DB 통합 | 실제 writer 형식 합성 공고/Evidence → 자동 감지 → 계산 → 저장 → 조회·재시작 | 실제 B 분석 완료 callback 또는 실계정 FE E2E |
| A 공개 데이터 | 실제 Top20k 완료 입력 검증·27개 분할 전체 처리·재개·최종 DB/HTTP 조회 | 모든 Repo 기술 판정 성공·개인 수준 판정·정상 tree lineage |
| 실제 채용 데이터 | 기존 10개 + 신규 4개 공고 품질 검수 | 충분한 목표 직무 모집단·월별 시장 추세 확보 |
| 공식 언어 Trend | 실제 Innovation Graph CSV의 Java KR 두 분기 계산·DB/HTTP 조회 | 라이브러리 기술 추세나 JOB 과거 데이터 확보 |

전체 Ruff에 남아 있는 기존 `I001` 7건: `collector/gharchive/sinks.py`, `github/repo_fetch_store.py`, `github/repo_snapshot_bootstrap.py`, `llm/test_server.py`, `tests/test_repo_fetch_benchmark.py`, `tests/test_repo_fetch_orchestrator.py`, `tests/test_repo_snapshot_bootstrap.py` (모두 AI 기준). 별도 type checker 설정은 없다.

최종 실행 이미지 ID는 `sha256:9e3517cc20f0a934068069b484d4e5461c52735ed1c3fc70c1c726067f436155`이다. build 후 최종 format-only 차이는 실제 컨테이너의 cohort/demand/input_union/intake/api와 최종 로컬 소스 AST SHA-256 비교 및 관련 회귀로 확인했다. 따라서 최종 commit과 byte-identical 이미지라고 주장하지 않는다.

## 3. 핵심 인수 사례

### 개인 Evidence와 추천

[합성 calibration 18개](../../AI/tests/test_evidence_calibration.py) 및 관련 Evidence·구 결과 호환 120개 테스트에서 정책을 검증했다. 실제 Docker HTTP에서는 유효 L1/L2/L3, source-only L0, proofless L3, 접근 권한만 있음, 모순 관측의 7경우를 확인했다.

앞의 4경우는 HELD·현재 부합 1개, 뒤의 3경우는 UNKNOWN·현재 부합 0개였다. 이것은 [확인 기술 정책](c-recommendation.md)의 일관성을 검증한 것이며 L0~L3를 같은 숙련도로 평가한 결과가 아니다.

동일 완료 event의 재전달은 동일 저장 Snapshot을 반환했다. 타 사용자 조회는 404였고, Rule 설명과 What-if의 신규 공고 ID가 실제 목록과 일치했다. 구 Snapshot은 조회 때 재계산하거나 새 기본 필드를 추가하지 않고 hash·목록을 유지했다.

### 자동 공고 갱신과 다중 출처

Worker 시작 시 실제 Saramin writer로 발행한 합성 공고 4개를 자동 감지했다. JOB 완료 POST 없이 코호트가 준비됐다. 실행 중 다른 출처의 더 오래된 관측을 추가한 뒤 그 공고의 최신 CLOSED 관측을 발행했다.

| 시점 | 공고 분모 | 같은 Evidence의 현재 부합 | Docker 추가 후 부합 | 신규 부합 |
|---|---:|---:|---:|---:|
| 최초 Saramin | 4 | 1 | 2 | 1 |
| Worknet 관측 추가 | 5 | 2 | 3 | 1 |
| Worknet 최신 CLOSED | 4 | 1 | 2 | 1 |

출처가 다른 동일 raw ID는 구분됐고 CLOSED 이후 과거 ACTIVE로 되돌아가지 않았다. 이전 5개 코호트의 불변 조회와 컨테이너 재시작 후 최종 4개 코호트·개인 결과 보존도 확인했다.

회귀: [입력 통합](../../AI/tests/test_job_input_union.py), [통합 자동화](../../AI/tests/test_job_union_intake.py), [실제 writer 호환](../../AI/tests/test_intake_producer_compat.py), [HTTP 계약](../../AI/tests/test_compute_api.py).

### 실제 A Top20k

고정 입력 ID: `s15p21e102-114-phase1-20260907-fix-001`. 원래 HDFS root와 입력·해석 규칙은 [공개 분석 계약](c-public-analysis.md)에 있다.

- 후보 20,000: COMPLETE 13,101 / PARTIAL 291 / NOT_FOUND 6,579 / FAILED 29.
- Snapshot record는 13,410개다. 원천 failures/summary와의 차이를 검증했으며 빠진 Repo를 기술 미사용 record로 만들지 않았다.
- COMPLETE 중 파일 없음 12,235개. 원천 선언 Artifact 4,876개는 모두 MANIFEST이며 SOURCE는 0개다.
- parser v2로 27/27 분할 처리, COMPLETE Artifact 2,108개 실제 read·size/hash 검증. WebHDFS GET 4,236회, retry 0, 총 29,025,310 bytes.
- 재실행은 27개 파티션 재사용, metadata GET 20회, Artifact 재읽기 0회. 최종 결과의 로컬 PostgreSQL 왕복·재시작·Worker HTTP 조회도 확인했다.
- 지원 parser의 **분석 분모 848개** 중 **승인 기술 긍정 관측 저장소 189개**, **관측 행 799개**, **기술 15개**다. 미해결 관측 저장소 736개는 긍정 관측 저장소와 겹칠 수 있다.
- 실행은 COMPLETED지만 품질은 **INSUFFICIENT_DATA**다. tree SHA가 commit SHA로 기록된 문제는 실제 GitHub 표본 2건에서 확인했고 원본을 교체하지 않았다. 초기 Consumer 인수는 8개 항목 중 7개 통과, lineage 1개 실패다.

파이프라인 ID: `4900a19f9b3653e10faa62347da3d468a6ddf1d39874c04e124088239688c444`. 저장 ID: `c-841ee2f34b5c8a3d237efd6c0b758f4c4177c0405dd451e3d6059ddc0b389b13`.

상세 재개·실패·최종 게시 규칙과 테스트 범위는 [공개 파이프라인](c-public-pipeline.md)을 따른다.

### 실제 공고와 공식 Trend

[실공고 14개 검수표](c-job-demand.md)의 BACKEND 포함 수는 모두 0이고, 기존 Saramin AI_DATA의 Python 필수 공고 1개는 해당 검수 기준 `min_jobs=2`에 미달했다. MariaDB를 MySQL로 합치거나 모호한 조건을 임의 승인하지 않았다. 새 4개는 원본 HTML/hash까지 대조했으며 이전 10개는 저장된 본문/manifest까지 대조했다.

등록일/수정일 혼재 때문에 실제 게시일 기준 JOB 월별 추세 검증으로 인정하지 않았다. 공식 Innovation Graph는 Java KR 2025-Q4 32,342 → 2026-Q1 29,166, 변화 -3,176을 실제 CSV·HTTP·DB에서 확인했다. 원본 CSV commit/hash는 [Trend 계약](c-public-trend.md)에 있다.

## 4. 다시 검증하는 방법

[AI 개발 환경](../../AI/README.md)의 Python 3.12 및 `requirements-dev.txt` 설치 환경을 재사용한다. 아래는 **AI 디렉터리** 기준이며 기존 AI 내부 venv를 우선 사용하고 없으면 개발 환경 안내의 저장소 루트 venv를 사용한다. 둘 다 없으면 먼저 개발 환경을 준비한다.

```powershell
$python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "..\.venv\Scripts\python.exe"
}
$env:PYTHONPATH = (Get-Location).Path + ";" + (Resolve-Path ..\Infra\spark).Path
& $python -m pytest tests/test_evidence_calibration.py tests/test_job_input_union.py tests/test_recommendation_engine.py -q
```

위는 DB 없이 실행하는 좁은 회귀다. 전체 973개 결과와 동일한 검증을 하려면 실행자가 별도 PostgreSQL 테스트 DB를 준비하고 `C_COMPUTE_TEST_DATABASE_URL`을 지정한다. 테스트는 해당 DB에 테스트 schema를 생성·변경·정리하므로 운영 DB를 사용하면 안 된다. DSN이 없으면 DB 테스트가 skip되어 같은 검증 범위가 아니다.

```powershell
if (-not $env:C_COMPUTE_TEST_DATABASE_URL) {
    throw "먼저 격리 PostgreSQL 테스트 DB를 지정하세요."
}
& $python -m pytest tests -q
```

주요 추가 회귀는 `test_compute_store.py`, `test_compute_api.py`, `test_recommendation_legacy.py`, `test_worker_intake.py`, `test_public_pipeline.py`, `test_public_intake.py`, `test_public_hdfs_reader.py`다. 네트워크 응답을 주입한 단위 테스트와 실제 HDFS 재실행은 별개다.

실제 HDFS를 다시 읽으려면 [public_run 실행 계약](c-public-pipeline.md)에 맞는 권한·고정 root·reader route·checkpoint를 준비한다. 다른 입력/버전에는 다른 checkpoint를 쓰고 손상이나 실패를 없애려고 기존 checkpoint를 삭제하지 않는다. DB 저장은 CLI 단독 실행이 아니라 Worker 게시 경로까지 확인해야 한다.

커밋 경계는 저장소 루트에서 `git log --reverse --oneline edfa96db..ce4c24f`로 확인한다. 대표 경계는 `8ec3d2d` Evidence 정책, `c4a9d65` 공개 분할/재개, `e51ccd6` 완료 검증/게시, `07ac3de` 자동 입력, `365471f` 공고 통합, `ce4c24f` 현재 입력에 맞춘 자동 조회다. 구현과 해당 회귀 테스트를 같은 기능 커밋에 묶었다.

## 5. 서비스 MVP 인수에 남은 항목

아래는 타 조의 납기 확약이나 새 계약 재설계 요청이 아니라 실제 서비스 인수 조건이다.

| 항목 | 필요한 작업·담당 경계 | 완료 확인 |
|---|---|---|
| 공고 품질·양 | A 수집 결과 공급, C 품질 검수·동일 기준 집계 | 충분한 목표 직무 유효 공고, 게시일 근거, 수요/증가 수와 실공고 목록 대조 |
| 공개 근거 품질 | A tree 보정 및 SOURCE 제공 범위 확인, C 재인수 | 원본 lineage 일치, 실제 제공 파일 범위와 관측 한계 확인 |
| 개인 분석·화면 | B 실제 Evidence/완료 callback·인증 조회, C 소비 검증, FE 표시 | 실제 계정으로 완료→추천→What-if→목록, 부분 실패·재전달·사용자 격리 |
| 검수 운영 연결 | C 검토 이력·재처리 경계와 B 관리자 승인/DB 연결 | 승인한 Registry 버전과 원본으로 재계산, 시도·근거 이력 보존 |
| 운영 실행 | 승인된 Worker/DB 배포와 입력 mount·보존·기준 시각 관리 | 운영 readiness + 입력 성공 + 실데이터 DB/조회 + 재실행/응답시간 확인 |

공개 품질 개선과 개인 추천 연결은 독립 진행할 수 있다. 충분한 실공고·실제 개인 Evidence 없이 합성 테스트만으로 서비스 MVP 완성을 선언하지 않는다.

## 6. 문서 갱신 검증

9/8 후속 문서 정리에서 변경 Markdown 8개의 로컬 링크 111개, PowerShell 예제 18개의
구문 및 코드 fence를 확인했다. 4절의 좁은 회귀 예제를 실제 문서에서 추출해 실행하여
56개 테스트 통과를 확인했다. `git diff --check`도 통과했다.
이 갱신은 문서만 변경했으며 전체 973개·DB·Docker·HDFS 검증을 새로 실행하지 않았다.
2~3절은 명시한 구현 커밋에서 확보한 기존 증거다.

## 7. MR !39 리뷰 보완 검증

2026-09-08, MR 제출 기준 `b605385`의 리뷰 4건을 재현한 뒤 보완했다. 이 절만 후속
보완 코드의 새 검증 결과이며 위의 실데이터 수치·컨테이너 이미지를 새 버전 증거로 바꾸지 않는다.

- 완료 입력 교체: 실제 Saramin writer로 같은 run 경로에 2건→1건, 동일 건수의 다른 내용,
  manifest만 교체한 경우를 차단한다. 동일 bytes 재발행·원본 복구는 허용한다. 실제 격리
  PostgreSQL과 FastAPI TestClient로 Worker 재시작 후 교체 차단, 현재 resolve 404,
  과거 Snapshot 조회와 원본 복구 후 같은 Snapshot ID를 확인했다. DB 바인딩의 경합·트랜잭션
  롤백과 DB 실패 시 독립 공개 처리 유지도 회귀로 검증했다.
- 공고 조건: `등을`/`등의`를 필수 AND로 확정하지 않으며, 지원하는 작업 연결 표현과
  기술 간 연산자를 일관되게 구분한다. 원문 근거와 미등록 AND/OR 피연산자 검토 정책은 유지한다.
- 공개 의존성: VCS/URL 미지원 행의 앞뒤 정상 FastAPI 관측과 path/URI/hash 근거·분모를
  보존하고 부분 분석으로 표시한다. 주석·명시적 이름 URL·기존 Python 의존성 표기도 회귀로 확인했다.
- 계산 버전: `job-cohort-quality/v3`, `c-public-static-observations/v3`. v1/v2 공개 checkpoint의
  묵시 재사용을 거절한다. 기존 checkpoint/불변 Snapshot은 삭제하거나 변환하지 않는다.

보완 후 전체 AI 테스트는 **996 passed / 0 failed / 0 skipped**, 실제 격리 PostgreSQL 포함,
의존성 deprecation warning 2개다. 변경 Python 9개는 `AI/`에서 Ruff check/format check 통과.
추가 dependency·API·환경 변수·DB migration은 없다. `JOB_INPUT` 결합은 기존 event 테이블을 쓴다.
이번에는 Docker 재빌드·실제 HDFS 전체 분석·B/FE/운영 E2E를 재실행하지 않았다. 특히 위의
848/189/799/15 공개 분석 수치는 parser v2의 기존 결과이며 v3 결과는 재분석 후 확인해야 한다.

## 8. 추가 리뷰의 공고 해석·공개 파서 보완

같은 `b605385` 리뷰에서 추가된 결함 4건과 조건 해석 2개 사례를 `daada34`에서도
재현한 뒤 보완했다. 앞선 7절과 별도 후속 변경이며 기존 커밋/검증 기록을 덮어쓰지 않는다.

- 회사소개/기업소개는 담당업무 필수 범위를 종료한다. 실제 수집기 형식의 Java 담당업무와
  Python 회사소개를 함께 전달해 Java만 필수 요구절로 남는 것을 확인했다.
- `필수가 아닙니다`, `중 2가지 이상`은 검토 대상으로 남긴다. A가 전체 문장 또는 기술
  단어만 evidence_text로 전달하는 두 경우를 모두 검증했다.
- npm 별칭은 실제 대상 패키지를 매핑하며 원래 별칭/선언·path/URI/hash 근거를 보존한다.
  여러 줄 JS/TS 정적 import는 인식하고, 문자열·주석·template·정규식 예시는 제외한다.
  Java 텍스트 블록의 예시는 Spring Boot 근거가 아니며 실제 import 줄번호는 유지한다.
- 버전: classifier `job-requirement-rules/v5`, quality `job-cohort-quality/v4`,
  공개 parser `c-public-static-observations/v4`. 과거 공개 v1/v2/v3 checkpoint 재사용을 거절한다.

독립 검토에서 회사소개에 A의 REQUIRED 라벨이 남은 경우와 10/20개 이상 다자리 조건도
추가 재현하여 보완했다. 원본 A 라벨은 보존하면서 명시 회사소개는 SKILL로 확정하고,
숫자 조건은 전체 문장·단어 근거 두 경로 모두 검토한다. 보완 뒤 같은 재현을 다시 확인했다.

이 보완분의 전체 AI 테스트는 **1038 passed / 0 failed / 0 skipped**이며 실제 격리
PostgreSQL과 기존 Snapshot HTTP/목록 호환 회귀를 포함한다. 의존성 경고는 기존 2개다.
변경 Python 7개 Ruff check/format 및 diff check를 통과했다.
이후 월별 집계 정책을 위한 별도 미구현 테스트는 이 보완 커밋의 검증 대상에 포함하지 않았다.
새 dependency·API 경로·환경 변수·DB migration은 없다. 운영 배포·B/FE 인수 증거가 아니다.

### 동일 실데이터의 v3 → v4 비교

A의 같은 Top20k 완료 입력을 읽기 전용 WebHDFS로 다시 검증해 metadata/Artifact
2,112개를 로컬에 보존했다. GET 4,236회, 29,025,310 bytes, retry 0이었다. 그 뒤
수정 전 `daada34`와 수정본은 동일한 검증 bytes를 로컬에서 분석했으며 추가 수집·서버
쓰기·원본 교체는 없었다. 기본 Registry `registry-20260908.1`도 양쪽에 같은 bytes로 고정했다.

- Snapshot SHA-256: `97b6039f82391a957b99cb5710d9f42bfb9e3dbe0e46f84292619c870457c476`
- Registry 원본 LF bytes SHA-256: `5febf14f4063962107202dcd9a48df21112ec17ed393b50074d8e8b3a10194c5`
- 공개 v4 final SHA-256: `d3a8d96b86c7b9a63e2b168b547f0b4216da2a991f397c3aa3fe20e48a1bfa57`

| 지표 | parser v3 | parser v4 |
|---|---:|---:|
| COMPLETE/eligible | 13,101 | 13,101 |
| 실제 파싱한 Repository 분모 | 849 | 849 |
| 승인 기술 긍정 관측 Repository | 189 | 189 |
| 기술 관측 행 | 801 | 799 |
| 관측 기술 종류 | 15 | 15 |

`open-metadata/OpenMetadata`, `stablyai/orca`의 `vite: npm:rolldown-vite@7.3.1`
선언에서 잘못된 Vite 근거가 각각 한 행 제거됐다. 두 Repository에는 별도의 Vite 근거가
남아 기술별 Repository 분자/비율은 바뀌지 않았다. 결과는 여전히 INSUFFICIENT_DATA이며
Tree lineage 오류·빈 Artifact·표본 편향이 해소된 것은 아니다. SOURCE가 없는 실제 입력이므로
JS/TS와 Java source 경계의 검증은 합성 회귀이며 실데이터 관측 사례로 보고하지 않는다.

기존 실제 공고 14개도 같은 원본 hash·Registry·고정 as_of로 직접 분류/코호트/집계 비교했다.
지원 직무 5종, 입력 batch 3개에서 기술 분류·포함/제외/검토·수요 결과의 의미 변화는 없었다.
원본 manifest의 hash 결합 누락으로 자동 intake는 계속 BLOCKED이며, 이 비교는 원본 bytes를
직접 확인한 수동 로컬 계산이다. 등록/수정일 혼재 입력으로 월별 수요가 검증됐다는 뜻도 아니다.

## 9. 월별 게시 수요와 활성 공고 분리 검증

2026-09-08, 추가 리뷰 보완 `b30d757` 이후 별도 S15P21E102-31 변경이다.
기본 `ACTIVE_MATCHING`은 현재 추천·What-if에, 명시적 `MONTHLY_DEMAND`는
완료된 서울 달력 월의 게시 관측 수요에 사용한다. [공고 계약](c-job-demand.md),
[Trend 계약](c-public-trend.md), [Worker 호출](c-compute-runtime.md)에 선택 방법을 기록했다.

- 같은 검증 입력에서 마감 경과 후 활성 분모는 2→1, 월별 분모는 2→2로 유지됐다.
  월중 CLOSED 공고도 월별 수요에 남고 원본 상태·마감 시각·hash를 보존했다.
- 최신 CLOSED 관측은 월별에 포함하지만 최신 본문 누락·미확정 조건은 여전히 검토했다.
  원래 수집 기준 시각·게시일·품질 조건을 완화하거나 과거 정상 본문을 되살리지 않았다.
- 월 시작 포함/다음 월 시작 제외, 서울 시각·연도 경계·윤년, 부분 월/미완료 월 거절,
  누락 월의 `None`과 유효 분모 내 특정 기술의 실제 0을 검증했다.
- 실제 격리 PostgreSQL과 FastAPI TestClient로 완료 event→COHORT/DEMAND 저장→JOB Trend
  조회, writer 형식 자동 intake와 활성/월별 stream·현재 결과 pointer 분리를 확인했다.
  활성 DEMAND를 월별 Trend로 전달하면 FAILED, 월별 COHORT로 추천을 요청하면 422로 거절했다.
- 기존 활성 결과의 기본 purpose/빈 posting_status는 직렬화에서 생략한다. 과거 추천
  Snapshot hash·HTTP 조회·목록은 유지됐고, 정책 버전 변경 후 동일 event ID 재사용은
  409 `IDEMPOTENCY_CONFLICT`로 거절됐다. 과거 결과를 새 의미로 다시 계산하지 않았다.

회귀 코드: [월별 정책](../../AI/tests/test_monthly_demand_policy.py),
[Trend 범위](../../AI/tests/test_compute_scope.py),
[기존 추천 호환](../../AI/tests/test_recommendation_legacy.py).
최종 전체 AI 테스트는 **1060 passed / 0 failed / 0 skipped**, 실제 격리 PostgreSQL 포함,
기존 의존성 deprecation warning 2개다. 변경 Python 8개 Ruff check/format과 diff check를
통과했다. 독립 리뷰에서도 월별 품질 조건·결과 호환성·저장 범위의 미해결 결함은 없었다.

동일 실제 공고 14개/Registry/고정 as_of를 사용한 별도 비교에서는 기본 활성 결과의
기술 분류·포함/제외/검토·수요가 그대로였고 JSON 필드도 추가/누락되지 않았다.
quality version과 그에 따른 신규 cohort ID만 달라졌다. 이 비교는 보존 원본의 수동 계산이다.
기존 실공고 manifest는 여전히 hash 결합이 없어 자동 intake에 사용할 수 없고, 게시일 이력도
불충분하므로 실제 월별 수요 검증 완료로 보지 않는다. 위 월별 숫자는 합성 회귀 결과다.

계산 버전은 `job-cohort-quality/v5`, JOB Trend `c-job-monthly-demand/v1`이다.
새 dependency·DB migration·환경 변수·API 경로는 없다. Docker 재빌드·운영 배포·B/FE 인수는
실행하지 않았으며 8절의 공개 v4 결과는 재사용한 검증 기록이다.
