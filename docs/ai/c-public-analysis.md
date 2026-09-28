# 공개 Repository Artifact 분석 계약

상태: C6 로컬 구현 및 parser v4 리뷰 보완. 아래 전체 입력 소비·로컬 DB 게시 증거는 parser v2 기준이며 후속 버전 재실행과 구분한다. 원천 Tree 메타데이터 결함과 품질 한계 유지. 운영 서버/화면 통합 별도.
기준일: 2026-09-08. Jira: S15P21E102-160.

## 범위와 입력

`github.public_analysis.analyze_public_batch(batch, reader, mapper, *, include_partial=False)`는 기존
`github-repo-snapshot/v1`을 변경하지 않고 `c-public-repo-analysis/v1` 결과를 만든다.
호출자는 A의 공개 Repository 수집 배치만 전달한다. v1에는 visibility 필드가 없으므로
이 입력의 공개 여부를 개별 record로 증명할 수 없으며 개인 Repository 배치를 연결하지 않는다.
공개 표본의 기술 관측은 [출처별 JOB/GITHUB Trend](c-public-trend.md)의 월별 공고 수요 및
Innovation Graph 분기별 언어 지표와 별개이며, 이를 합쳐 종합 점수를 만들지 않는다.

`ArtifactReader.read(uri, *, max_bytes)`는 bytes를 반환한다. URI prefix와 로컬 root를
운영 설정으로 고정한 `LocalMirrorArtifactReader`를 사용하거나 같은 제한을 지키는
신뢰 가능한 reader를 주입한다. 요청 본문의 URI를 인터넷 URL로 자동 다운로드하지 않는다.
파일 크기와 SHA-256이 모두 일치한 Artifact만 파싱하고 Snapshot의 pinned commit,
Repository ID, 수집 상태, 원본 Artifact path/URI/hash, batch/run/collector/parser/Registry
버전을 결과에 보존한다. 반환값에는 원본 파일 내용이 없다.

지원 Manifest는 package.json의 선언된 직접 dependency 영역, requirements.txt,
pyproject.toml의 project.dependencies, Maven pom.xml의 직접 dependencies,
Gradle의 리터럴 dependency 선언이다. 동적 빌드 코드를 실행하지 않는다.
parser v3는 requirements.txt의 이름 없는 VCS/URL 의존성을 해석하지 못해도 같은 파일의
정상 패키지 관측을 유지한다. 미지원 부분은 `STATIC_PARSER_PARTIAL`/INSUFFICIENT_DATA로
남기며 VCS 코드 다운로드·실행이나 URL에서의 기술명 추정은 하지 않는다. 예를 들어
FastAPI 선언과 미지원 VCS 선언이 함께 있으면 FastAPI의 path/URI/hash/commit 근거와
지원 자료 분석 분모를 보존한다. 해시/크기 검증 실패와 손상된 파일의 실패 정책은 유지한다.
지원 source는 Python AST import 및 JS/TS/Java의 정적 import 문이다.
parser v4는 package.json의 `npm:` 별칭을 설치 이름이 아닌 실제 대상 패키지로
매핑한다. 예를 들어 `react18: npm:react@18.3.1`은 React 관측이며
`react: npm:preact@10.0.0`은 React 근거가 아니다. 원래 선언과 path/URI/hash 근거를
보존한다. JS/TS는 여러 줄 정적 import를 인식하고, Java 텍스트 블록 안의 import 예시는
실제 구문에서 제외한다. 주석·문자열의 예시와 실제 import를 분리하면서 줄번호는 유지한다.
JS/TS는 기존과 같이 줄 시작의 정적 선언을 지원한다. minified 중간행 선언이나 완전한
JS/JSX 문법 분석까지 보장하지 않으며, 정적 미관측을 해당 기술의 부재로 해석하지 않는다.
지원 source 확장자의 언어 관측과 package/import 후보를 기존 RegistryMapper로 매핑한다.
이 관측은 개인 Evidence level, 구현 깊이 또는 본인 기여 판정이 아니다.
공개 표본의 기술 관측에서 사용자 L3를 생성하지 않으며 본인 구현은 B의 귀속 결과를 소비한다.
Registry 버전과 후속 Snapshot 근거는 [Registry 후속 Snapshot](../data/2026-09-08-technology-registry-mvp.md)을 따른다.

## 상태·제외 정책과 분모

`observations`는 확인한 긍정 관측만 포함한다. UNKNOWN/AMBIGUOUS 후보와
미지원·파싱 실패 Artifact는 별도 항목으로 남는다. COMPLETE라도 관측되지 않은 기술을
미사용으로 단정하지 않는다. 기본 입력 정책은 COMPLETE 및 계약상 완전한 이전 Snapshot을
재사용한 REUSED다. FAILED는 Artifact가 있어도 읽지 않는다. PARTIAL은
`include_partial=True`일 때만 읽으며 `partial_included`와 원본 `collection_issues`를 남긴다.
제외 record도 commit/path/URI/hash/collection 상태와 제외 사유를 보존한다.
개별 C Artifact 읽기/파싱이 일부 실패해도 다른 검증된 Artifact의 긍정 관측은 유지하되
Repository 상태를 INSUFFICIENT_DATA로 기록한다. 모두 실패한 Repository는 분모에 넣지 않는다.
`tree_sha`가 `pinned_commit_sha`와 같으면 `quality_reasons`에
`TREE_SHA_EQUALS_COMMIT_SHA`를 남기고 READY로 표시하지 않는다. 원본 SHA와 검증된
Artifact 긍정 관측은 보존한다. 이것은 알려진 잘못된 lineage의 구조적 경고이며 함수가
GitHub API를 조회하거나 입력 Tree SHA를 교체한다는 뜻이 아니다.

| 필드 | 의미 |
|---|---|
| total_repo_count | 실제 snapshot.records 수. 외부 failures.json의 NOT_FOUND를 합성하지 않음 |
| eligible_repo_count | COMPLETE/REUSED 및 명시적으로 허용한 PARTIAL 수 |
| analyzed_repo_count | eligible 중 hash/size 검증 후 지원 Artifact를 하나 이상 파싱한 Repository 수 |
| excluded_repo_count | total_repo_count - analyzed_repo_count. 정책 제외 및 지원 자료 확보 실패 포함 |
| sample_repo_count | analyzed_repo_count와 같은 관측 비율 분모 |

record의 `eligible`, `included_in_denominator`, `exclusion_reasons`로 정책 제외와
분석 가능한 자료가 없는 경우를 구분한다. `denominator_basis`는
`ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT`다. 기술별 `observed_repo_count`는 이 분모에
포함된 고유 Repository의 긍정 관측 수이며 항상 분자<=분모이다. 비율은 지원 범위의
관측 하한이며 미관측 기술 부재나 시장 점유율을 뜻하지 않는다.

## Top-20,000 최초 인계·표본 읽기 검증

2026-09-08 사용자 전달 A 인계 root:
`hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-114-phase1-20260907-fix-001/`

인계 파일은 `snapshot.json`, `failures.json`, `run-summary.json`, `_SUCCESS.json`,
`artifacts/`이며 schema는 기존 `github-repo-snapshot/v1`이다.
확정 근거는 저장소 밖 실행 workspace `C:/workspace/pj2`의
`validation/c-top20k-consumer-20260908/consumer-read-summary.md` 및 같은 이름의 JSON이다.
이 최초 기록은 전체 metadata의 GET 읽기와 다운로드한 두 표본의 로컬 C 소비 결과다.
후속 parser v2 전체 입력 소비 및 로컬 DB 게시 검증은 아래 별도 절에 기록한다.

전체 건수와 상태 대조는 완료했다. summary의 실제 20,000행은 A 보고와 같은
COMPLETE 13,101 / PARTIAL 291 / NOT_FOUND 6,579 / FAILED 29다.
snapshot.records 13,410건은 COMPLETE 13,101 + PARTIAL 291 + FAILED 18이다.
Snapshot에 없는 6,590건은 NOT_FOUND 6,579 + FAILED 11이며,
failures.json 6,608건은 NOT_FOUND 6,579 + FAILED 29로 정확히 대조되었다.
따라서 20,000 후보 수와 Snapshot record 수는 서로 다른 모집단이며 둘 다 자동으로 관측 비율의 분모가 되지 않는다.

COMPLETE 13,101건 중 Artifact가 없는 Repository는 12,235건, 있는 Repository는 866건이다.
전체 Snapshot의 선언 Artifact 4,876개는 모두 MANIFEST이며 SOURCE는 0개다.
COMPLETE는 수집 정책의 완료 상태이지 구현 코드 확인이나 사용자 Evidence L2/L3 완료가 아니다.
PARTIAL의 TREE_TRUNCATED/FILE_LIMIT_REACHED/BYTE_LIMIT_REACHED 등 원본 사유를 보존한다.
NOT_FOUND는 Repository API 조회 불가이며 기술 부재가 아니다. 기존 Snapshot enum은
COMPLETE/PARTIAL/FAILED/REUSED만 허용하므로 NOT_FOUND를 새 enum이나 가짜 record로 넣지 않고
외부 failures.json 인계 품질로 구분한다. FAILED 및 Artifact가 없는 Repository도 기술 미사용으로 환산하지 않는다.

8개 읽기 검증은 **7 PASS / 1 FAIL**이다.

| 확인 | 결과 |
|---|---|
| root 상태·완료 파일·artifacts 디렉터리 | PASS |
| 성공 manifest의 3개 JSON URI·SHA-256 | PASS |
| 전체 Snapshot schema·dataset 식별자 | PASS |
| 전체 20,000건 상태·실패 건수 대조 | PASS |
| ID/rank 중복 및 summary와 Snapshot의 상태·rank 일치 | PASS |
| COMPLETE 표본 2건의 Artifact 4개 실제 읽기·크기·SHA-256 | PASS |
| Repository/commit URI 및 실제 GitHub commit→tree 연결 | FAIL: 표본 2/2의 Tree SHA 불일치 |
| 다운로드한 표본 2건의 로컬 C 공개 분석 실행 | PASS: 두 결과의 품질 상태는 INSUFFICIENT_DATA |

전체 선언 Artifact의 URI `repo_id=.../commit=...` lineage 불일치는 **0건**이다.
확정된 결함은 파일 URI나 바이트 손상이 아닌 Tree 메타데이터다.
Artifact가 있는 COMPLETE 중 rank 2와 4를 표본으로 택했고, 4개 파일 총 1,722바이트의
크기·SHA-256이 일치했다. 두 표본은 같은 `ugmoddev` 소유자의 Manifest이며,
인증 없는 공개 GitHub commit metadata 조회에서 두 pinned commit은 일치했지만
A의 `tree_sha`는 실제 `tree.sha`와 **2/2건 불일치**했다.
전체 COMPLETE+PARTIAL 13,392건에서도 `tree_sha == pinned_commit_sha`를 확인했지만,
실제 GitHub tree와 외부 대조하여 결함을 확정한 범위는 두 표본이다.
입력 Tree SHA를 임의 교체하거나 Artifact 재수집을 자동 요구하지 않는다.

두 표본의 로컬 소비는 `registry-20260908.1`, `c-public-static-observations/v1`로 실행되어
canonical 기술 `pydantic`과 미해결 관측을 보존했다. 입력 subset의 관측 분모는 2이며
두 Repository의 결과 품질은 INSUFFICIENT_DATA다. 이는 소비 실행 성공과 데이터 품질을
분리한 판정이며, 이 최초 표본 검증만으로 전체 Top-20,000 분석 완료나 시장 대표성을 주장하지 않았다.

## 후속 parser v2 전체 입력 소비 검증

같은 A 입력을 `c-public-static-observations/v2`로 27개 파티션 모두 처리했다.
기본 COMPLETE 정책으로 Artifact 2,108개를 실제 읽어 크기·SHA-256을 검증했고,
PARTIAL/FAILED record는 원본 사유와 함께 제외했다. 지원 parser 분석 분모는 848개 Repository다.
승인 Registry 기술의 긍정 관측은 고유 Repository 189개, 관측 행 799개, 고유 기술 15개다.
미해결 관측이 있는 Repository는 736개이며 긍정 관측 Repository와 중복될 수 있다.
분모에 포함되었다는 사실과 승인 기술 긍정 관측이 있다는 사실은 서로 다르다.
전체 실행은 COMPLETED, 결과 품질은 INSUFFICIENT_DATA이며 원본 Tree 경고를 보존했다.
재실행 시 27개 파티션 재사용·Artifact 재읽기 0회 및 격리 로컬 PostgreSQL 게시 후
재시작 시 동일 Snapshot 반환도 확인했다. 상세 실행 계약은 [분할·재개·최종 합산](c-public-pipeline.md)을 따른다.

확정 근거는 저장소 밖 `C:/workspace/pj2/validation/c-top20k-full-analysis-v2-20260908/`의
`final.json`, `execution-summary.json`, `replay-summary.json`, `postgres-verification.json`이다.
전체 입력 처리는 정책상 제외된 PARTIAL까지 포함한 선언 Artifact 4,876개 전체 읽기를 뜻하지 않는다.
수집 상태·빈 Artifact·SOURCE 부재·미해결 매핑·미관측으로 기술 미사용을 추론하지 않는다.

## 회귀 검증과 연결 한계

`AI/tests/test_public_analysis.py` 및 기존 `AI/tests/test_github_repo_contracts.py` 회귀로
SHA-256/size 실패, Manifest 선언·source import, 미지원/미확정,
로컬 `FileArtifactStore`→별도 consumer를 검증했다. FAILED 무조회,
PARTIAL 기본 제외/명시적 포함, REUSED, C 부분 읽기 실패 시 긍정 관측 유지,
분자·분모·제외 수 JSON 정합성 및 Tree SHA 품질 경고도 fixture로 검증했다.
변경 Python 파일의 Ruff check 및 format check는 AI 디렉터리 기준으로 통과했다.
별도 type checker는 설정되어 있지 않다.

내부 실행/DB 저장/B 조회는 C7에서 이 모델의 JSON을 사용한다.
Fixture의 SOURCE 파서 검증, 최초 Manifest 두 표본 검증, 후속 v2 전체 입력 소비는 별개다.
후속 실행으로 전체 입력 처리와 로컬 DB 게시는 검증했지만, 선언 Artifact 4,876개 전체
다운로드·SOURCE 실자료 파싱·사용자별 Evidence·운영 서버/API/DB·실제 B/FE 연결·
성능·rate-limit 복구를 검증한 것은 아니다.
현재 Top-50,000 확장은 HOLD다.

## 출처

- [Repo Snapshot 계약](../data/2026-09-02-a-to-c-github-repo-snapshot-contract.md)
- [출처별 JOB/GITHUB Trend 계약](c-public-trend.md)
- [Registry 후속 Snapshot](../data/2026-09-08-technology-registry-mvp.md)
