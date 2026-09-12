# C 계산 실행·저장 계약

상태: 로컬 PostgreSQL·HTTP 왕복 구현 및 검증. B/FE·운영 연결은 미검증.
기준일: 2026-09-08. 이슈: S15P21E102-33.

2026-09-10 -199 후속: Registry 운영 기본은 PostgreSQL이다. B 기본 설정
`technology-registry/v1`을 유지하되 DB의 명시적 활성 버전을 해석한다.
[DB Registry 계약](../data/technology-registry-db.md)의 migration·import가 필요하며,
이 문서의 변경은 서버 배포 완료를 의미하지 않는다.

2026-09-09 -185 후속: 새 COHORT의 `matching_jobs`가 준비되어 있으면 분석 완료 시
`job-matching/v2`도 원자적 저장 대상으로 계산한다. RECOMMENDATION에는 작은 reference만,
공유 원본과 사용자별 평가는 002 projection에 분리한다. [부분 부합 계약](c-job-matching.md)에
bounded 목록/상세 경로, 구 결과 호환/409, 예산과 무결성 오류 정책을 정의했다.

## 책임과 실행

공고는 완료 manifest 자동 감시 또는 명시적 배치 완료 HTTP API로 입력한다.
B의 완료 Evidence 결과는 C 내부 HTTP API로 전달한다. C가 계산하고
PostgreSQL에 불변 결과 Snapshot을 저장한다. 별도의 사용자
승인 단계는 없다. B는 사용자 인증·소유권을 확인하고 C 결과를 서비스 API로
전달하며 계산을 다시 구현하지 않는다. 기존 개인 저장소 Facts/Rule 엔진은 변경하지 않는다.

이 API는 내부 서비스 전용이다. 모든 `/internal/v1/c/*` 요청은
`Authorization: Bearer <C_COMPUTE_TOKEN>`이 필요하다. 개인 결과는 추가로
`user_id`를 지정하며 DB 조회에도 같은 소유자 조건이 적용된다. 이 값은 B가
인증한 사용자로 설정해야 하며 브라우저가 직접 지정하는 인증 수단이 아니다.

`/health`는 기존 process liveness를 유지한다. 인증된 `/ready`는 DB migration 준비를
확인한다. 이 둘은 완료 입력 감시 성공·공고 준비·B 연결을 검증하지 않는다.
미설정 상태에서 실제 계산 API는 503이고 임시 메모리 결과로 대체하지 않는다.

## 요청과 응답

완료 event 공통 필드: `schema_version=c-compute-event/v1`, `event_id`, `trace_id`,
timezone이 있는 `occurred_at`. 요청/결과의 도메인 DTO는 아래 기능별 계약을 따른다.

| 내부 경로 | 입력 / 동작 |
|---|---|
| `POST /internal/v1/c/job-batches/completed` | -90 `batch` + `criteria`: 공고 품질·동일 cohort의 수요 계산 |
| `POST /internal/v1/c/job-cohorts/resolve` | `CohortCriteria`로 현재 준비된 cohort ID 조회. 미준비 404. 조회이며 새 계산을 시작하지 않음 |
| `POST /internal/v1/c/analyses/completed` | `user_id`, `analysis_id`, `cohort_snapshot_id`, `evidence`: 자동 Gap·추천·What-if·설명 |
| `POST /internal/v1/c/public-repositories/completed` | -157 `batch`, `include_partial=false`: COMPLETE/REUSED 우선 공개 기술 관측 |
| `POST /internal/v1/c/trends/completed` | `tech_id`, `source`, `periods`: JOB `demand_snapshot_ids` 또는 GITHUB 공식 형식 `csv_text`·`source_uri`·`source_version` |
| `POST /internal/v1/c/archive-trends/completed` | v1은 검증된 activity export와 저장된 PUBLIC_GITHUB ID로 current 관측을 유지한다. `archive_version=v2`는 같은 trusted root의 A 원본 snapshot path/URI/SHA-256을 추가로 받고 `C_ARCHIVE_A_SNAPSHOT_URI_ROOT`와 URI를 결속해 월별 commit lineage가 일치한 역사 관측만 저장한다. [Archive 계약](c-archive-trend.md) |
| `GET /internal/v1/c/snapshots/{snapshot_id}` | 불변 결과. 개인 결과는 `user_id` 필수, 타 사용자/없는 결과 모두 404 |
| `GET /internal/v1/c/recommendations/{snapshot_id}/job-postings` | `user_id`, `mode=CURRENT\|WHAT_IF`, `recommended_tech_id`, page/size. WHAT_IF는 **신규 증가 공고만** |
| `GET /internal/v1/c/recommendations/{snapshot_id}/matching-job-postings` | 공고별 부분 부합 목록. `user_id`, page/size, `include_conditional=false` |
| `GET /internal/v1/c/recommendations/{snapshot_id}/matching-job-posting` | 동일 저장 평가의 상세. `user_id`, `job_id` |
| `GET /internal/v1/c/registry` | 실행 중인 정확한 Registry Snapshot과 meta의 schema/content version·SHA-256 |
| `GET/POST /internal/v1/c/registry/reviews/...` | -88: 미해결 원문 조회·수동 결정·재처리. [검토 큐 요청·충돌 계약](c-registry-review.md) |
| `GET /internal/v1/c/contracts` | 실제 Pydantic 완료 event의 JSON Schema. 구현이 계약 원본 |
| `GET /internal/v1/c/intake/status` | 완료 입력 감시의 활성/실행 여부, 최근 poll의 완료·실패·보류 수, 공개 분할 진행 및 DB 결과 ID |

공고 criteria의 선택 필드 `purpose`는 기본 `ACTIVE_MATCHING`이며 기존 활성 공고 추천
동작을 유지한다. 월별 수요는 `MONTHLY_DEMAND`와 서울 기준 한 달 전체 posted_from/to,
월 종료 이후 as_of를 명시한다. 월별 결과는 마감 여부만으로 제외하지 않으며 수집 기준 시각과
기존 품질 조건은 유지한다. 월별 COHORT는 추천·What-if에 사용하지 못하고, 기본 활성
DEMAND는 JOB Trend에 사용하지 못한다. [월별 계약](c-public-trend.md)에 분모·기간·상태를 정의한다.
기본 purpose는 저장 JSON에서 생략해 과거 추천 Snapshot hash/조회 형식을 보존한다.
MONTHLY_DEMAND는 criteria와 stream에 명시적으로 포함해 활성 결과 pointer와 섞이지 않는다.
DB migration·새 환경 변수·새 endpoint는 없으며 기존 완료 event/자동 intake 설정으로 선택한다.
JOB 집계 정책 버전은 Trend event의 계산 identity에도 포함하므로 구 event를 새 의미로 재사용하지 않는다.

응답은 `{message, data}`이고 오류는 `{code, message}`이다. 저장 응답은 event ID,
상태, 결과 snapshot reference들을 반환한다. `PREPARING`(202)은 동일 event의 기존
실행이 아직 살아 있는 경우이고 동일 ID로 재시도할 수 있다. 정상적인 대상 공고 0건과
입력 부족은 도메인 결과 상태이며 DB 장애(503)나 계산 실패(500)와 구분한다.

동일 event/내용의 재전달은 저장된 결과를 그대로 반환한다. 같은 event ID의 내용,
소유자 또는 종류가 바뀌면 409 `IDEMPOTENCY_CONFLICT`이다. 계산은 transaction 밖에서
진행하고 완료 시 lease token을 검증한 한 transaction으로 모든 결과와 event 상태를
확정한다. 만료된 실행의 늦은 완료는 새 실행을 덮어쓰지 못한다. 장애 후 동일 요청
재시도 또는 lease 만료 후 재수행이 가능하다. 큐나 확인되지 않은 백그라운드 작업을
완료했다고 응답하지 않는다.

살아 있는 계산은 `lease_seconds / 3` 간격으로 동일 token의 lease를 갱신한다.
만료/교체/완료된 token은 갱신할 수 없다. 계산 완료와 갱신의 경합에서 실제 완료된
결과를 실패로 바꾸지 않으며, 최종 DB transaction의 fencing 검증이 권위 있는 판정이다.
request hash에는 실제 Registry/parser/quality/집계/추천/설명 버전도 포함한다.
Registry의 canonical SHA-256도 함께 바인딩하여 동일 버전 문자열의 내용 변경을 구분한다.
배포로 버전이 바뀐 뒤 같은 event를 다시 계산하려 하면 409이므로 새 event ID를
사용해야 한다. 이미 저장된 Snapshot은 그대로 조회 가능하다. `trace_id`만 바뀐 재전달은 허용한다.

현재 결과 pointer는 `(kind, owner, stream)`별 event 발생 시각·ID 순서로 갱신한다.
stream에는 조회 기준/입력 cohort를 포함하므로 직무나 기준이 다른 이전 결과를 새
결과처럼 재사용하지 않는다. 서비스는 응답 snapshot ID를 고정해 숫자와 목록을 읽는다.
오래된 event의 지연 도착은 최신 pointer를 역행시키지 않는다.
Trend pointer는 직무·출처·지역·경력·최소 표본과 계산 버전을 구분한다.
공개 분석 pointer는 수집 정책·parser/Registry 및 PARTIAL 포함 여부도 구분한다.
같은 범위의 새 관측은 기존 pointer를 갱신하지만 다른 조회 범위나 품질 정책의
결과를 덮어쓰지 않는다. 입력 내용 전체를 pointer 키로 사용하지 않는다.

요청 본문은 8 MiB로 제한하고 초과 시 413 `INPUT_TOO_LARGE`다. matching 결과는
50,000공고/논리 저장 64 MiB 및 행별 예산을 적용하고 초과 시 절단 없이 413
`RESULT_TOO_LARGE`로 전체 게시를 실패한다. 대형 Top20k Snapshot은 이 API에 한 요청으로
전달하지 않는다. collection/consumer read budget에 맞춘 명시적 partition과 원본
run lineage가 필요하며, 작은 표본 결과를 전체 완료로 표시하지 않는다.
목록은 0-based `page`, `size=1..50`이다. 조회 응답 `snapshot_id`는 DB 저장 ID,
`calculation_snapshot_id`는 설명을 붙이기 전 계산 ID로 구분한다.

## 완료 입력의 자동 실행

### Registry 실행 설정

- `C_REGISTRY_BACKEND=postgres`가 기본이다. `C_COMPUTE_DATABASE_URL` 또는 기존
  `POSTGRES_*` 연결 설정으로 public Registry 테이블을 읽는다.
- `C_REGISTRY_VERSION=technology-registry/v1`이 기본 선택값이며 실제 계산에는
  시작 시 해석한 불변 `registry-YYYYMMDD.N`과 내용 SHA-256을 고정한다.
- 파일은 `C_REGISTRY_BACKEND=file`을 명시한 테스트·로컬 모드에서만 사용한다.
  `C_REGISTRY_PATH`가 비어 있으면 기존 승인 seed 파일을 읽는다. DB 장애의 대체재가 아니다.
- DB/Registry가 준비되지 않아도 `/health`는 살아 있고 `/ready`와 계산은 503
  `C_REGISTRY_UNAVAILABLE`이다. DB 복구·import 이후 Worker를 재시작한다.
- B는 신규 요청 생성 시 같은 family를 불변 버전으로 바꾸어 기존 event 필드에 넣는다.
  요청 재전송과 기존 분석 재사용은 원래 버전을 유지한다. C의 현재 Registry와 다른
  cohort/Evidence를 섞어 계산하지 않는다. 활성 버전을 바꿀 때에는 진행 중 분석을
  먼저 마치거나 원 버전 Worker로 처리하고, 새 버전 cohort를 준비한 뒤 전환한다.
  미완료 요청을 단순히 새 버전으로 바꿔 재전송하지 않는다.

`C_INTAKE_CONFIG`가 가리키는 로컬 JSON 설정을 지정하면 기존 `python -m worker`의
lifespan이 입력 감시를 시작하고 종료 시 중단한다. 별도 수동 submit 명령은 필요 없다.
미설정은 기존 HTTP-only 동작이다. DB migration과 32자 이상 내부 token은 먼저 준비한다.
입력 디렉터리/설정은 read-only, 공개 checkpoint 디렉터리만 writable로 마운트한다.
환경 변수만 설정하고 파일을 마운트하지 않으면 시작 시 설정 오류로 실패한다.

### Compose에서 반드시 추가할 mount

기본 `Infra/compose/compose.yaml`은 `C_INTAKE_CONFIG` 환경 변수만 전달하며 Worker에
입력 volume을 선언하지 않는다. **아래 JSON을 작성하고 환경 변수만 넣는 것으로는 실행되지 않는다.**
운영자가 선택한 Compose override 또는 동등한 컨테이너 실행 설정에 bind mount를 추가한다.
실행 설정·입력 원본·비밀값은 Git에 넣지 않는다.

| 호스트에서 준비할 것 | 컨테이너 경로 예 | 권한·설정 일치 |
|---|---|---|
| `c-intake.json` 파일 | `/config/c-intake.json` | read-only, `C_INTAKE_CONFIG`도 이 컨테이너 경로 |
| 보존된 완료 공고 root | `/input/jobs/saramin`, `/input/jobs/worknet` | read-only, JSON `job_roots`와 일치 |
| 공개 분석 checkpoint 전용 디렉터리 | `/state/c-public` | read-write, 공개 입력을 사용할 때만 필요 |
| 공고 HDFS staging 디렉터리 | `/state/c-jobs` | read-write, `job_hdfs_sources[].staging_dir`와 일치. 기본 Compose의 `c-job-staging` 볼륨이 이 경로다 |

컨테이너 JSON에 Windows 호스트 경로를 쓰지 않는다. 아래 HDFS 주소는 컨테이너에서
접근 가능한 이름의 예시이며 실제 허용 NameNode/DataNode route를 확인해야 한다.
기본 Compose는 Worker 8080을 내부 expose만 하므로 호스트에서 직접 호출할 URL이나
개발용 loopback port도 별도 실행 설정으로 준비한다. 이 문서 갱신은 해당 배포를 수행하지 않는다.

corrected Top1,000 canary에서 NameNode redirect는 DataNode의 9864, 9874, 9884와
service-node DN4의 9864 origin을 사용했다. 운영 적용 전 각 advertised origin을 worker가
접근 가능한 내부 origin으로 명시적으로 매핑하고, allowlist에 없는 redirect는 계속
거절해야 한다. 아래 JSON은 형식 예시이며 실제 host 이름과 route는 배포 환경에서
확인한 뒤 operator가 채운다.

### 입력 설정 예

```json
{
  "schema_version": "c-intake-config/v1",
  "poll_seconds": 30,
  "max_manifests": 1000,
  "job_roots": ["/input/jobs/saramin", "/input/jobs/worknet"],
  "job_hdfs_sources": [{
    "root_uri": "hdfs:///gitjob/analysis_input/jobs",
    "namenode_base_url": "http://hdfs-namenode:9870/webhdfs/v1",
    "datanode_routes": {"http://hdfs-datanode:9864": "http://hdfs-datanode:9864"},
    "staging_dir": "/state/c-jobs",
    "sources": ["worknet", "saramin", "career", "gamejob"],
    "max_runs_per_source": 200
  }],
  "criteria": [{
    "target_role": "BACKEND",
    "as_of": "2026-09-08T02:00:00Z",
    "min_jobs": 20
  }],
  "public_sources": [{
    "root_uri": "hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=REPLACE_WITH_PUBLISHED_ID",
    "namenode_base_url": "http://hdfs-namenode:9870/webhdfs/v1",
    "datanode_routes": {"http://hdfs-datanode:9864": "http://hdfs-datanode:9864"},
    "checkpoint_dir": "/state/c-public/REPLACE_WITH_PUBLISHED_ID",
    "include_partial": false,
    "max_records": 500,
    "max_declared_bytes": 50000000,
    "max_requests": 8000
  }]
}
```

`job_hdfs_sources`는 A조가 게시한 공고 회차(S15P21E102-220)를 읽는 방법이다. `job_roots`와
같은 입력이며 판정도 같다 — 차이는 파일이 어디서 오는지뿐이다. 각 poll 시작 시 아직 받지 않은
회차만 `staging_dir/<source>/<RUN_ID>/`로 내려받고, 그 디렉터리들이 `job_roots`에 더해져 기존
`load_job_output`·`build_input_union`이 그대로 처리한다. manifest가 있는 회차만 소비하며,
manifest가 batch 바이트를 묶지 못하면 받지 않는다. 이미 받은 회차는 다시 읽지 않으므로 반복
poll이 비용을 만들지 않는다. WebHDFS 장애는 이미 staging된 회차에 영향을 주지 않는다.
읽기 전용이며 C는 HDFS에 쓰지 않는다. 둘 중 하나만 써도 되고 둘 다 비우면 공고 입력이 없다.

공고만 사용할 때는 `public_sources`를 생략한다. 공개 입력만 사용할 때는 `job_roots`와
`criteria`를 함께 생략한다. 공개 입력은 명시한 불변 Snapshot만 읽으며 다른 root나
Top50k를 자동 탐색하지 않는다. `as_of`와 기간/직무는 재현 가능한 계산 입력이며 시계에
따라 몰래 바뀌지 않는다. 새 기준/새 Snapshot은 새 설정과 해당 checkpoint 경로로 실행한다.

- 공고는 지정 root 또는 바로 아래 run 디렉터리의 `manifest.json`을 완료 신호로 사용한다.
  현재 Saramin/Worknet/JobKorea writer는 batch/CSV 다음에 manifest를 원자적으로 쓴다.
  C는 고정 sibling(Saramin/Worknet `job_analysis_input.json`, JobKorea `job_analysis_input_v1.json`), manifest의 source/run/version/count/timestamp,
  `output_sha256[고정 파일명]`, read 전후 파일 identity와 manifest 재읽기를 검증한다.
  세 writer는 직렬화한 batch bytes의 SHA-256을 마지막 manifest에 포함한다. 같은 run 재작성 중
  old manifest + new batch 조합은 해시 불일치로 거부한다. 링크·경로 이탈·크기 초과도 거부한다.
  해시 없는 기존 완료 파일은 `UNBOUND_LEGACY_MANIFEST`로 자동 게시를 보류한다. 원본을 임의로
  새 완료 파일로 승격하지 않는다. 이미 저장된 과거 입력은 명시적인 수동 품질 검증/기존 HTTP
  계약으로 분석할 수 있지만, 이를 자동 producer 연결 검증으로 보고하지 않는다.
- 수집 중단/무효 기록/상세 수집 오류가 manifest에 있으면 자동 게시를 보류한다. 수정일이
  섞인 입력에 게시일 기간 필터를 적용하는 것도 보류한다. 원본을 고치거나 지우지 않는다.
- 자동 실행은 지정된 roots의 **검증된 완료 입력 관측 합집합**을 C에서 만든다. A에 새로운
  통합 batch를 요구하지 않는다. 출처/공고 ID별 `as_of` 이전 최신 관측을 선택한 뒤 기존
  품질·직무·기간·지역·경력 조건으로 같은 공고 집합을 확정하고 수요를 계산한다.
  서로 다른 수집 기간/검색 범위는 site별 최신 batch 하나로 대체하지 않는다.
  기준 시각 이후 관측은 과거 결과에 섞지 않고, 동일 최신 시각의 상충 기록은 검토 대상이다.
  CLOSED/본문 미확보 최신 기록을 과거 ACTIVE/정상 본문으로 되돌리지 않는다.
- 여러 출처의 같은 raw ID는 `job_id`만 `SOURCE_SITE:source_posting_id`로 구분하고 원본
  `source_record_id`는 보존한다. `canonical_job_id` 일치만으로 사이트 간 공고를 삭제하지 않는다.
  cohort의 `input_union`은 원본 batch/run/collector/hash, record별 선택·중복·대체·미래·충돌
  내역을 담는다. 수요는 동일 `cohort_id`에 연결되어 이 출처 정보를 재조회할 수 있다.
  이는 확보된 관측의 합집합이며 전체 시장을 빠짐없이 수집했다는 뜻이 아니다. 새 batch에서
  안 보이는 공고를 삭제/마감으로 추론하지 않는다. 운영자는 완료 입력을 보존된 전용 root에 공급한다.
- 한 poll은 총 50,000개 원본 record와 batch bytes 128MiB 이내다. 초과나 발견/검증 실패,
  불완전 manifest가 있으면 축소된 입력을 완성 모집단으로 게시하지 않는다. 현재 resolve는
  COHORT_NOT_PREPARED이고 기존 불변 Snapshot ID 조회는 유지한다. 독립 공개 입력 처리는 계속한다.
  실행 중 한 번 검증한 manifest가 발견 목록에서 사라져도 축소 집합을 게시하지 않는다.
  자동 합집합 입력은 최초 검증된 manifest 절대 경로와 batch/manifest SHA-256의 결합을
  DB `event`의 내부 `JOB_INPUT` 검증 이벤트로 고정한 뒤 계산한다. 경로는 정규화 후 해시에
  포함하며 원문 경로·본문을 이 이벤트에 저장하지 않는다. 동일 bytes 재발행은 허용하지만
  같은 경로에 내용/건수/manifest를 바꾸어 재발행하면 현재 resolve를 막는다. DB의 결합 기록은
  재시작·계산 버전 변경 후에도 유지되며 새 관측은 새 run 경로로 발행한다.
  DB 결합 저장 실패 시에도 계산하지 않는다. 이미 저장된 불변 결과는 지우지 않는다.
  이 기록은 이전 버전에 소급 생성되지 않는다. 기존 입력이 사라진 뒤 재시작하는 경우의
  누락 경로 복원 기능도 아니므로, 운영에서 완료 입력과 고정 mount 경로를 보존해야 한다.
  필터 밖 출처는 합집합 결과 identity에서 제외되므로 나중에 온 다른 출처가 정상 결과를
  EMPTY로 가리지 않는다. 명시한 날짜 필터에 수정일 혼재가 있으면 해당 계산을 보류한다.
- 합집합 identity·criteria·계산 버전으로 event를 고정하고 cohort/수요를 같은 transaction으로
  저장한다. 재시작/DB 응답 유실도 동일 결과를 재사용한다. cache는 입력 hash 집합에 결박한다.
  자동 실행의 resolve는 현재 검증된 입력집합의 완료 ref만 반환하며, 단순 max collected_at
  최신 pointer를 사용하지 않는다. 늦게 발견한 과거 batch도 합집합에 반영된다.
  B는 resolve ID를 분석 완료 요청에 고정한다. 자동 입력이 설정되지 않은 기존 HTTP 완료
  API 모드는 호출자가 전달한 한 batch 범위를 그대로 계산한다.
  JOB_BATCH의 계산 버전에는 `input_union=c-job-input-union/v1`을 포함한다. 이전 이벤트를
  새로운 계산 버전으로 다시 처리하려면 새 event ID를 사용하며 과거 Snapshot 조회는 유지한다.
- 공개 입력은 publish manifest·hash·summary/failures를 검증한 뒤 poll마다 최대 한 partition을
  처리한다. 전체 완료 전에는 DB에 완성 Snapshot을 게시하지 않는다. 최종 provenance/20k 품질
  대조까지 저장하는 계약은 [공개 pipeline](c-public-pipeline.md)을 따른다.
- Worker 자동 공개 실행은 실행 Registry의 canonical hash를 checkpoint에 바인딩한다.
  CLI는 Registry 파일 raw hash를 쓰므로 CLI checkpoint와 자동 실행 checkpoint는 구분한다.

개인 분석은 B가 `POST /analyses/completed`를 호출하는 즉시 추천까지 자동 실행된다. C가
사용자 버튼이나 별도 수동 계산을 기다리지는 않는다. 아직 없는 B의 실제 callback·인증/화면을
C의 파일 감시가 대신 구현하지는 않는다. B 실제 event로 end-to-end 검증은 공동 통합 인수다.

### 상태 확인과 복구 순서

아래는 접근 가능한 서비스 origin과 내부 token이 환경 변수에 설정된 경우의 읽기 요청이다.
token을 출력하거나 브라우저에 전달하지 않는다.

```powershell
$headers = @{ Authorization = "Bearer $env:C_COMPUTE_TOKEN" }
Invoke-RestMethod "$env:C_COMPUTE_URL/ready" -Headers $headers
Invoke-RestMethod "$env:C_COMPUTE_URL/internal/v1/c/intake/status" -Headers $headers
```

| 관찰 | 의미와 다음 확인 |
|---|---|
| 서비스 시작 자체 실패 | 설정 파일/mount/DB·token 설정/Registry를 확인. 이 경우 status API도 없을 수 있음 |
| 인증 후 `C_REGISTRY_UNAVAILABLE` 503 | Registry 미준비로 intake도 시작하지 못함. `configured=false` 응답이 아니다. 승인/무결성/migration 문제를 해결한 뒤 Worker를 재시작 |
| `configured=false` | 자동 intake 미설정, HTTP-only 모드. 자동화를 원하면 파일 mount와 `C_INTAKE_CONFIG`를 설정하고 재시작 |
| `configured=true`, `running=false` | 감시 thread가 실행 중이 아님. 시작/종료 상태와 Worker 로그 확인 |
| `last_poll.failed > 0` | 원본/manifest hash·경로·수량·크기·DB 등 입력/실행 오류 가능. 입력과 checkpoint를 보존한 채 검증 조건과 로그의 error type 확인 |
| `last_poll.blocked > 0` | 수집 중단/무효 기록/상세 오류 또는 게시일 필터와 수정일 혼재 등. 수집 실패 원인·날짜 근거를 해결하고 검증 가능한 새 완료 산출물 발행. 기존 원본은 보존 |
| `last_poll.pending > 0` | 관련 완료 입력 미도착 또는 계산/lease 대기 가능. 기준·출처·입력 및 다음 poll 확인 |
| resolve가 `COHORT_NOT_PREPARED` | 해당 criteria의 현재 검증 입력 집합 결과가 없음. 설정 criteria와 요청이 같은지, 입력 failed/blocked 여부를 먼저 확인 |
| `public_sources[].status=FAILED` | 해당 공개 입력의 reader·원본·checkpoint·DB 경계를 확인. 같은 입력이면 성공 partition은 보존하고 다음 poll 재시도 |

`last_poll`은 최근 poll 통계이지 누적 성공 수가 아니다. 이미 계산한 입력은 cache를 사용하므로
`completed=0` 자체는 실패가 아니다. 공개 진행은 별도 `public_sources`에서 확인한다.
status는 모든 개별 manifest 오류의 상세 사유를 반환하는 진단 API가 아니며 로그도 안전한
error type 위주다. 원본과 loader의 검증 조건을 함께 대조해야 한다.

설정 파일은 시작 시 읽으므로 기준/경로/설정을 바꾸면 Worker를 재시작한다. 입력만 정상적으로
발행한 경우 다음 poll이 다시 검증한다. 새 정상 run을 추가해도 같은 root에 기존 불량 manifest가
남아 있으면 전체 입력 검증 실패는 해소되지 않는다. hash를 수작업으로 맞추지 않으며 불량 입력의
보존·격리와 대체 입력 범위는 운영자가 명시적으로 결정해야 한다. 삭제된 기존 입력을 복원하지 않고 Worker를 재시작해
축소 집합을 승인하는 방식으로 우회하지 않는다. 손상 checkpoint는 지우지 않고 조사하며,
원천/정책 버전이 바뀐 정상 새 분석에는 새 checkpoint 디렉터리를 지정한다.
코호트 준비 전 B 개인 완료 이벤트를 반복 전송하는 것으로 공고 문제를 해결할 수 없다.

## 저장과 migration

현재 `db/migration/V1__baseline_schema.sql`의 13개 Registry/Evidence 테이블과 적용된
`db/c-compute/001_c_compute.sql`은 수정하지 않는다. 001은 `c_compute` schema의 event 실행,
불변 결과, 현재 pointer 및 migration checksum을 만든다. 새
`002_job_matching_projection.sql`은 shared `matching_source`, 계산 metadata,
compact 사용자 평가 행만 추가하고 source/assessment UPDATE·DELETE를 trigger로 막는다.
런타임 role은 두 projection table에 SELECT/INSERT만 부여한다. 공고 cohort는 원본 수집
본문이 아닌 분석된 기술 조건·출처·품질·버전을 한 번 저장한다. 수요/개인 추천/공개
분석/Trend는 버전이 있는 결과 JSONB를 저장한다. 개인 원본 코드·토큰은 받거나 저장하지 않는다.
다른 추천/설명 계산마다 테이블을 만들지 않는다. 결과의 owner는 기존 B 사용자 ID이며 C가
별도의 사용자 테이블을 만들지 않는다. 스키마 생성 권한은 migration 실행자에게만 주고
런타임에는 C 테이블 SELECT/INSERT/UPDATE 권한만 주면 된다.
`JOB_INPUT`은 동일 경로의 입력 교체를 차단하는 내부 완료 검증 이벤트이며 결과 Snapshot이나
현재 head를 만들지 않는다. 기존 event 테이블에 저장하므로 추가 migration/테이블은 없다.

DB URI는 `C_COMPUTE_DATABASE_URL` 또는 기존 `POSTGRES_*` 설정으로 구성한다.
API가 시작하면서 DDL을 자동 실행하지 않는다. 적용/롤백/권한 부여는 배포 단계에서
승인 후 별도로 실행해야 하며 이번 작업은 로컬 테스트 DB에만 적용한다.

개발 PC에서는 `AI/`에서 `python -m worker.migrate`를 명시적으로 실행한다. runner는
001부터 002까지 checksum을 확인하여 순서대로 적용하고 `/ready`는 두 버전을 모두 요구한다.
빌드 이미지에는 `/app/migrations/001_c_compute.sql`과
`/app/migrations/002_job_matching_projection.sql`을 포함하며 같은 명령을 쓴다.
`C_COMPUTE_DATABASE_URL`은 migration에서 반드시 명시한다. 런타임 token과 DDL 권한은
별개이며 실행에 필요한 테이블 권한만 별도로 부여한다. Worker image는 기존 `/app`
모듈 위치를 유지하고 Registry provenance 파일을 `/opt/gitjob-provenance`에
포함해 빌드 및 시작 때 검증한다. Python venv/cache는 이미지에서 제외한다.

## 인수 경계

로컬 PostgreSQL + C 내부 HTTP API로 배치→수요→Evidence→추천→저장→목록,
중복/실패 재시도/lease/사용자 격리를 검증했다. 실제 빌드 Worker 컨테이너에도
완료 전송기로 합성 공고·Evidence를 보내 수요 분모 4, 현재 부합 1, Docker 추가
신규 부합 1과 목록 ID 일치를 확인했다. 같은 event 재전달은 같은 Snapshot을
반환하고 다른 사용자 조회는 404다. 공식 Innovation Graph CSV의 Java 두 분기
값 32,342 → 29,166도 HTTP 계산·DB 저장·조회로 확인했다. 별도 새 로컬 DB에
기존 베이스라인을 적용하고 C migration을 두 번 실행해 public 13개 테이블의 열 정의가
유지되고 c_compute의 4개 테이블만 추가됨을 검증했다.

A Top20k 인계는 표본 read 이후 read-only WebHDFS와 parser v2로 전체 27개 파티션을
처리했다. 실제 COMPLETE Artifact 2,108개 read·size/hash를 확인했고, 최종 결과를
격리 PostgreSQL에 게시한 뒤 빌드 Worker HTTP 조회 결과가 final JSON과 같은지 검증했다.
실행은 완료됐지만 analyzed 848개이며 파일 없는 COMPLETE 12,235개·Tree 경고·SOURCE 0을
보존하여 품질은 INSUFFICIENT_DATA다. 상세 실행/재사용 범위는 [공개 pipeline](c-public-pipeline.md)을 따른다.

완료 입력 자동화도 합성 공고 4개를 실제 Saramin writer로 발행하여 검증했다. 별도 공고 완료
HTTP 호출 없이 Worker lifespan이 manifest를 감지하고 cohort를 저장했다. criteria resolve와
컨테이너 재시작 후 동일 cohort 및 개인 결과 유지가 확인됐다. 개인 HTTP 검증 7개 경우는
유효 L1/L2/L3, source-only L0, proofless L3, 접근권한만 보유, 모순 관측이다. 앞의 네 경우는
같은 공고 매칭을 제공하고 뒤 세 경우는 UNKNOWN으로 유지한다. L0~L3와 보유 판단은 분리된다.

후속 다중 출처 검증은 같은 Worker 실행 중 사람인 합성 4개에 워크넷의 더 오래된 관측을
추가하여 5개로 갱신하고, 그 워크넷 공고의 최신 CLOSED 관측을 추가하여 4개로 갱신했다.
다른 사이트의 같은 원본 ID도 고유 공고로 보존했고, 마감 관측 이후 과거 ACTIVE를 부활시키지
않았다. 두 통합 cohort에 같은 합성 Evidence를 계산했을 때 현재 부합 수는 각각 2/1,
Docker 추가 후 부합 수는 3/2, 신규 공고는 각각 1개로 실제 목록과 일치했다.
이전 5개 Snapshot 조회와 재시작 후 최종 4개 Snapshot ID도 그대로 유지됐다.

공고·개인 Evidence의 컨테이너 검증 입력은 합성이며 실제 B 분석 결과가 아니다.
B의 실제 분석 완료 호출과 서비스
인증 API, FE, 운영 데이터/서버 연결은 별도 통합 인수이며 로컬 검증으로 대체하지 않는다.

출처: [추천·What-if](https://app.notion.com/p/15615fc50ec78365b73401c62b4fab33),
[관련 공고 목록](https://app.notion.com/p/06f15fc50ec783e198ba01dfd32dce7d),
[Evidence 정책 v2](https://app.notion.com/p/78215fc50ec7823d81e481e5ce71e50e),
[기존 A→C 계약](../data/2026-09-01-a-to-c-job-analysis-input-contract.md).
