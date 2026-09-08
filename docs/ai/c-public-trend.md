# 출처별 JOB/GITHUB Trend 계약

상태: C6 로컬 구현·검증 완료, 서버/화면 통합 별도. 기준일: 2026-09-08.
Jira: S15P21E102-31.

## 범위와 출처 구분

JOB은 월별 게시 관측 코호트의 distinct 공고 수요, GITHUB는 공식 Innovation Graph의
대한민국 언어별 분기 `num_pushers`를 제공한다. 출처별 지표·분모·기간을 분리하고
합산 점수나 저장되지 않은 과거 이력을 만들지 않는다. Stack Overflow는 현재 입력에 없다.
[공개 Repository Artifact 분석](c-public-analysis.md)은 별도 S15P21E102-160 계약이다.
그 GH Archive TopN 표본의 Repository 기술 관측 비율을 이 문서의 GITHUB 언어 지표로 대체하지 않는다.
Top-20,000 인계 읽기·파일 범위·Tree 메타데이터 품질 검증도 공개 분석 문서에서 관리한다.

Python GITHUB_LANGUAGE 매핑은 별도 `registry-20260908.1` Snapshot에서 제공한다.
추가 근거와 과거 seed 보존은 [Registry 후속 Snapshot](../data/2026-09-08-technology-registry-mvp.md)을 따른다.

## Trend 공통 출력

`TrendResult`는 `source`, `tech_id`, `metric`, `unit`, `granularity`,
`status`, `reasons`, `points`, `registry_version`, `algorithm_version`을 포함한다.
point는 period/value/denominator/ratio, 입력 run/source version/source URI를 보존한다.
변화량은 바로 이전 연속 기간이 있을 때 계산한다. 이전 값 0이면 절대 변화량만 제공하고
상대 변화율은 null 및 `PREVIOUS_ZERO`로 표시한다. 누락 기간을 보간하지 않는다.

상태: `READY`(요청한 데이터 및 비교 기간 있음), `PREPARING`(입력 미도착),
`INSUFFICIENT_DATA`(기간/비교 기준/유효 분모 부족), `NOT_SUPPORTED`(기술-출처 매핑 없음),
`FAILED`(입력 손상/일관성 위반). 실제 0은 유효한 분모/원천 행이 있을 때만 반환한다.
잘못된 기간/값 및 동일 키의 충돌·중복 행을 거부한다. 명시적 요청 periods는 중복 없는
오름차순이어야 한다. source/period별 수치를 합쳐 종합 점수를 생성하지 않는다.

## GITHUB: Innovation Graph

`trend.github.parse_innovation_graph_csv(text, *, source_version, source_uri)`는 공식
`num_pushers,language,language_type,iso2_code,year,quarter` CSV를 검증한다.
`github_trend(tech_id, dataset, registry, *, periods)`는 KR의 `YYYY-Qn` 행만 사용한다.
source_version은 다운로드한 자료의 Git commit SHA 또는 관리된 불변 버전이며 출력에
입력 CSV SHA-256도 남긴다. 동일 CSV의 다른 국가 행은 입력 검증 후 제외한다.
Registry에 유효하고 유일한 GITHUB_LANGUAGE 매핑이 있는 기술만 지원한다.
Kafka 등 라이브러리를 Java 같은 언어로 대체하지 않는다.
단위는 `UNIQUE_PUSHERS`, 분모·비율은 null이다. 언어마다 같은 개발자가 중복될 수 있어
언어 수치를 합산해 전체 개발자 수나 비율을 생성하지 않는다.
공식 공개 기준 때문에 행이 없을 수 있으므로 누락은 0이 아니다.

## JOB: 월별 게시 공고의 관측 수요

JOB point는 `criteria.purpose=MONTHLY_DEMAND`인 C1/C2 수요 결과에서 overall distinct 공고 수,
전체 포함 공고 분모, 비율을 소비한다. 기술 언급 요구유형별 수를 합산하지 않는다.
같은 직무·출처·지역·경력 필터와 Registry/분류/집계 정책을 가진 월별 결과만 비교한다.
동일 월 중복 입력, 부분 월 또는 필터/버전 불일치는 실패로 반환한다.
현재 저장된 최신 공고만으로 과거 월별 표본을 만들지 않는다.
호출은 `trend.job.job_trend(tech_id, snapshots, registry, *, periods)`이다.
`snapshots`는 C2 `DemandSnapshot` 목록이고 `periods`는 `YYYY-MM`이다.
월 경계는 Asia/Seoul의 `[월 시작, 다음 월 시작)`이며 `as_of`는 월 종료 이후여야 한다.
`as_of`는 수집 관측의 포함 마감 시각이지 공고가 아직 활성인지 검사하는 날짜가 아니다.
같은 검증 입력에서 deadline이 지났다는 이유만으로 과거 월 수요를 줄이지 않는다.
해당 월에 게시된 유효 공고는 CLOSED/마감 경과여도 포함한다. 본문 미확보, UNKNOWN 상태,
게시일 미확정, 미해결 기술/조건, 미래 수집 등 기존 품질 제한은 유지하고 제외·검토 건수를 남긴다.
새로운 원본 관측/정정이나 규칙 변경은 새 Snapshot이며 이전 결과를 수정하지 않는다.
월별 COHORT의 포함 공고에는 원본 `posting_status`도 보존한다. 기존 활성/구 Snapshot에는
이 필드를 추가 직렬화하지 않으므로 과거 추천 hash와 목록 형식은 유지한다.

추천·What-if에 사용하는 기본 `ACTIVE_MATCHING` 코호트는 그대로 활성 공고만 포함한다.
이 기본값은 과거 JSON/hash 호환을 위해 직렬화에서 생략한다. 구 DemandSnapshot을 월별
수요로 다시 이름 붙이지 않으며 JOB Trend에 전달하면 `MONTHLY_DEMAND_COHORT_REQUIRED`로
FAILED 처리한다. 반대로 월별 코호트를 추천/What-if에 전달하면 거부한다.

출력 schema는 `c-source-trend/v1`을 유지하고 JOB `algorithm_version`은
`c-job-monthly-demand/v1`이다. `filters.purpose=MONTHLY_DEMAND`,
`filters.posting_status_policy=INCLUDE_CLOSED`와 원래 직무·출처·기간·품질 버전을 보존한다.
분모는 수집·검증된 해당 월의 유효 공고 표본이지 전체 채용 시장의 공고 수가 아니다.
비교 가능한 월이나 충분한 표본이 없으면 PREPARING/INSUFFICIENT_DATA로 남긴다.
빈 분모·누락 월은 0 수요가 아니며, 유효 분모가 있을 때 특정 기술의 관측 0만 실제 0이다.

완료된 월의 보존 입력으로 기존 `/job-batches/completed` 또는 자동 intake의 criteria를
지정해 COHORT/DEMAND를 저장하고, 반환된 DEMAND ID를 기존 `/trends/completed`에 전달한다.
별도 DB 테이블·API 경로는 추가하지 않는다. 등록일/수정일이 혼재한 원천 입력을 게시일
월별 집계로 승격하지 않으며 월말 이전 기준 시각·부분 월은 criteria 검증 단계에서 거절한다.

## 로컬 검증 결과

공식 languages.csv를 commit `054c7dbc527518fa2ecfd316efe2aa01f3986c39`에 고정하여
2026-09-08 로컬에서 파싱했다. 5,832,978 bytes, 180,338행 중 KR 2,879행이며 입력
SHA-256은 `795f7b9da010161544ed50359e2bce9a9c8757831c25f4cb939dbf0569215dc2`다.
Java는 2025-Q4 `32342`, 2026-Q1 `29166`, 절대 변화 `-3176`으로 계산되었다.
원본 데이터는 저장소 밖 검증 폴더에 두었으며 제품 저장소에 포함하지 않았다.

`AI/tests/test_trend_github.py`는 공식 형식 행, Registry 언어 매핑, 누락 기간·이전 값 0,
잘못된 값/기간·중복 행과 source version/hash 보존을 fixture로 검증한다.
`AI/tests/test_trend_job.py`의 월별 fixture는 중복 월, 같은 필터/정책, 실제 0,
빈 분모, 누락 월, 부분 월을 검증한다. 새 Python 언어 매핑과 기존 seed 보존은
`AI/tests/test_registry_mvp_snapshot.py` 및 기존 Registry 회귀에서도 검증했다.
관련 테스트와 변경 Python 파일의 Ruff check 및 format check는 AI 디렉터리 기준으로
통과했으며 별도 type checker는 설정되어 있지 않다.

## 연결과 검증 한계

내부 실행/DB 저장/B 조회는 C7에서 이 모델의 JSON을 사용한다.
Fixture 검증과 실제 공식 CSV 로컬 실행은 분리해 보고한다. JOB 월별 fixture가
실제 과거 공고 코호트의 확보·자동 수집·운영 저장을 증명하지 않는다.
이 계약의 로컬 계산 검증은 운영 서버/API/DB·화면 통합 완료를 뜻하지 않는다.
공개 Repository 표본 및 사용자 Evidence와의 경계는 [공개 분석 계약](c-public-analysis.md)을 따른다.

## 출처

- [공개 Repository Artifact 분석 계약](c-public-analysis.md)
- [기술 추세 명세](https://app.notion.com/p/0dc15fc50ec78279ba070187702fab7a)
- [Innovation Graph datasheet](https://github.com/github/innovationgraph/blob/main/docs/datasheet.md)
- [검증에 사용한 공식 언어 데이터](https://github.com/github/innovationgraph/blob/054c7dbc527518fa2ecfd316efe2aa01f3986c39/data/languages.csv)
- [프로그래밍 언어 지표 설명](https://innovationgraph.github.com/global-metrics/programming-languages)
