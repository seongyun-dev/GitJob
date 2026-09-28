# 공개 Snapshot 분할·재개·최종 합산 계약

상태: 분할/loader/CLI 및 최종 DB 게시 구현·로컬 통합 검증 완료. 기존 Top20k와 월별 SHA Top1k 실제 HDFS 소비 완료, 원천 품질 한계는 유지.
기준일: 2026-09-12. Jira: S15P21E102-160, S15P21E102-214.

## 호출 경계

기존 [공개 Artifact 분석](c-public-analysis.md)과
[A→C Snapshot v1](../data/2026-09-02-a-to-c-github-repo-snapshot-contract.md)을 변경하지 않는다.
`github.public_pipeline.plan_public_pipeline(batch, mapper, *, include_partial=False,
max_records=500, max_declared_bytes=50_000_000, source_sha256=None,
manifest_sha256=None, registry_sha256=None)`는
읽기 없이 결정적 분할 계획을 반환한다.
`run_public_pipeline(batch, reader, mapper, checkpoint_dir, *, 동일 계획 옵션,
max_new_partitions=None)`는 `PipelineProgress`를 반환한다. 실행 상태는 IN_PROGRESS 또는
COMPLETED이며, 전체 완료일 때만 `result: PublicBatchResult`와 `final_path`를 제공한다.
`max_new_partitions=0`은 계획·기존 완료 결과만 검증하고 신규 Artifact를 읽지 않는다.
양수는 이번 호출에서 실행할 신규 파티션 수의 상한이다. 이어서 같은 호출을 반복하면 재개한다.

호출자는 공개 자료의 고정 URI namespace·접근 경계를 검증한 `ArtifactReader`와
변경 불가능한 승인 RegistryMapper를 제공한다. 이 모듈은 원격 URI를 직접 fetch하지 않는다.
Registry 버전은 변경 불가능한 Snapshot 식별자이며 같은 버전의 매핑 내용을 교체하면 안 된다.
원본 파일의 정확한 byte hash가 있으면 `source_sha256`, `manifest_sha256`, `registry_sha256`도 전달한다.
선택 hash는 호출자가 원본 파일에서 검증한 SHA-256이다. Batch/Mapper만으로 원본 파일의
공백·인코딩까지 복원할 수 없으므로 모듈은 이를 계산했다고 주장하지 않는다.

## 결정적 분할과 바인딩

입력 Batch를 다시 strict 검증하고 `activity_rank` 오름차순의 연속 record를 greedy 분할한다.
원래 rank·ID·집계 기간과 수집 정책을 재번호화하거나 축소하지 않는다.
각 파티션은 record 수 및 소비 대상 record의 선언 Artifact bytes 상한을 모두 지킨다.
소비 대상은 COMPLETE/REUSED와 opt-in PARTIAL이다. 제외된 record는 0 readable bytes로
계산하되 원본 선언 bytes와 제외 record 자체를 계획/결과에 보존한다.
`max_declared_bytes`는 기존 분석기의 100,000,000 bytes 이하이어야 하며, 단일 소비 대상
Repository가 설정 상한을 넘으면 계획 단계에서 실패한다. Repository 내부 Artifact를 나누어
부분 Repository를 완성된 결과로 만들지 않는다. Artifact별 2,000,000 bytes 제한은 기존
분석기가 그대로 적용하고 한도 초과 품질 결과를 보존한다.

계획은 전체 Batch canonical JSON SHA-256, dataset/run/collector/generated_at,
전체 collection_policy와 그 hash, parser/Registry version, 선택 원본 byte hash,
include_partial, 분할 설정 및 pipeline algorithm version을 포함한다.
`pipeline_id`는 이 전체 계획의 canonical hash다. 입력·정책·버전·옵션이 달라지면 같은
checkpoint 디렉터리를 재사용하지 못하며 새 디렉터리를 명시해야 한다.

## 로컬 체크포인트·중단·동시 실행

체크포인트 디렉터리는 운영자가 지정한 전용 로컬 파일시스템 경로다.
`checkpoint.json`은 계획과 완료 파티션별 SHA-256을, `partition-NNNNNN.json`은
해당 `PublicBatchResult`를 보존한다. 완료 결과는 hash·schema·입력 provenance를
모두 재검증한 후에만 재사용한다. 누락/손상/다른 계획의 checkpoint는 자동 초기화나
무검증 복구 없이 실패한다. 성공 기록에 없는 orphan 결과는 완료로 인정하지 않는다.

동일 디렉터리는 Windows byte-range lock 또는 POSIX flock으로 배타 실행한다.
다른 실행이 lock을 보유하면 즉시 `PipelineBusyError`가 발생한다. 프로세스 종료 시
OS가 lock을 해제하므로 stale PID 추측이나 lock 파일 삭제가 필요하지 않다.
파일은 같은 디렉터리의 고유 임시 파일에 작성·flush/fsync한 후 atomic replace한다.
Windows replace의 WinError 5/32/33만 최대 3회(대기 합계 0.15초) 재시도한다.
다른 OS/오류는 즉시 실패하며 재시도 소진 시에도 이전 checkpoint를 보존한다.
결과 파일을 먼저 쓰고 checkpoint를 갱신하므로 중간 종료 시 미기록 결과는 재실행된다.
공유 NFS/HDFS의 분산 lock 또는 다중 노드 실행을 보장하는 계약이 아니다.

Artifact의 ARTIFACT_UNAVAILABLE/HASH_MISMATCH/SIZE_MISMATCH 또는 실행 예외는
해당 파티션을 미완료로 남기고 `PipelineExecutionError`를 반환한다. 앞서 완료한 파티션은
유지한다. 같은 입력으로 다시 호출하면 실패 파티션을 다시 실행한다. 원천 FAILED 제외,
PARTIAL·Tree 경고·정적 미지원·파싱 실패 등의 품질 상태는 기존 분석 의미를 유지한다.
품질 INSUFFICIENT_DATA와 실행 IN_PROGRESS는 서로 다른 상태다.

현재 분석 버전은 `c-public-static-observations/v6`, 출력은
`c-public-repo-analysis/v2`다. v1은 reader의 namespace/config
ValueError를 검증된 파싱 실패와 같은 READ_OR_PARSE_FAILED로 기록할 수 있었다.
v2는 reader 단계 예외를 ARTIFACT_UNAVAILABLE로 분리하고, hash/size 검증 뒤의 파싱 실패만
기존 READ_OR_PARSE_FAILED로 유지한다. v3는 requirements.txt의 미지원 VCS/URL 항목을
부분 분석으로 남겨 다른 정상 의존성의 관측을 보존한다. 파티션 계획의 parser version도
바뀌므로 과거 checkpoint는 자동 재사용/변환하지 않는다. v4는 npm 별칭의 실제 대상,
여러 줄 JS/TS 정적 import와 Java 텍스트 블록 경계를 보완한다. v5는 requirements 연속행·hash,
UTF-16, Poetry와 유효 선언 부분 복구를 추가한다. v6는 공통 Manifest parser v2와 A의
`language_metadata`를 source-specific Registry 매핑으로 소비하고, 월별 SHA lineage를 출력에
보존한다. 언어와 지원 Artifact 중 하나라도 검증된 기술 입력을 제공하면 분모에 포함한다.
과거 checkpoint는 원래 버전으로 보존하고 v6는 새 checkpoint 디렉터리에서 실행한다.
v1 출력은 읽기 호환만 유지하며 새 결과는 parser·Manifest parser·Registry version을 함께
기록한다. 아래 실제 Top20k 수치는 v2의 기존 실행 결과이며 v6의 전체 분석 결과로 인용하지 않는다.

## 최종 발행

모든 파티션이 검증되기 전에는 `final.json`과 `_SUCCESS.json`을 발행하지 않는다.
`merge_public_partitions(batch, results, mapper, *, include_partial=False)`는 전체 입력의
Repository ID/이름/Snapshot ID/rank 중복·누락 및 각 원본 provenance를 확인한다.
원본 전체 범위의 rank 순서를 복원하고 관측 가능한 고유 Repository 분모와 기술별
distinct Repository 수를 다시 집계한다. 파티션 비율의 평균을 사용하지 않는다.
출력은 기존 `PublicBatchResult`와 의미가 같고, NOT_FOUND 가짜 record를 만들지 않는다.
완료 실행은 `final.json`을 atomic write한 후 pipeline/input hash 및 최종 byte hash를
가진 `_SUCCESS.json`을 마지막에 기록한다. 전체 완료 재호출도 결과와 marker를 검증한다.

## 검증 범위

분할·중단 재개·실패 재시도·손상·입력 변경·동시 실행·원본 범위 복원 및 distinct 합산을
fixture로 검증한다. 저장소 밖 실제 Top-20,000 전달 Snapshot의 전체 metadata를 이용한
분할 계획 검증은 Artifact 원격 읽기나 전체 소비 완료와 구분한다.
실제 입력과 Tree/Manifest 범위는 [공개 분석 검증](c-public-analysis.md)을 따른다.
2026-09-08 parser v2로 A의 `s15p21e102-114-phase1-20260907-fix-001` 전체 입력을
27개 파티션으로 소비했다. WebHDFS GET 4,236회, 재시도 0회로 완료했고, 같은 입력 재실행은
27개 파티션을 모두 재사용했다(metadata GET 20회, Artifact 재읽기 0회).
전체 결과를 격리 로컬 PostgreSQL에 게시하고 재시작 시 동일 Snapshot을 반환함을 확인했다.
운영 DB 배포나 실제 B/FE 연결을 검증한 것은 아니다.

후보 20,000개 중 COMPLETE 13,101개, PARTIAL 291개, NOT_FOUND 6,579개, FAILED 29개다.
Snapshot record는 13,410개이고, COMPLETE 중 12,235개에는 Artifact가 없다.
소비 대상 COMPLETE Artifact 2,108개를 읽어 크기/hash를 검증했다. 지원 parser 분석 분모
(`analyzed_repo_count`와 `sample_repo_count`)는 848개 Repository다. 이 중 승인 Registry 기술의
긍정 관측이 있는 고유 Repository는 189개, 긍정 관측 행은 799개, 고유 기술은 15개다.
미해결 관측이 있는 Repository는 736개이며 긍정 관측 Repository와 중복될 수 있다.
분석 분모 848개가 모두 승인 기술 긍정 관측을 얻었다는 뜻은 아니다.
최종 품질은 INSUFFICIENT_DATA이며 NOT_FOUND/FAILED/빈 Artifact·미해결 매핑·미관측을
기술 미사용으로 바꾸지 않는다. 전체 원천 Artifact는 MANIFEST뿐이며 SOURCE는 없다.
수집 결과의 tree SHA와 commit SHA 동일 경고도 보존하므로 개인 구현/기여 수준이나
A의 pinned tree lineage 검증 완료를 이 실행만으로 주장하지 않는다.

2026-09-12에는 A의 corrected Top1k
`s15p21e102-198-202607-top1000-canary-20260911-fix-004e`를 진단 shim 없이 제품 HDFS CLI로
소비했다. 입력 hash와 publish manifest hash는 각각
`1d7aa53f8901468d54cf1f9ed5a9d7885e0cd1795fc7cef277c38b7cc80a7a04`,
`c4b43abbebac9706874f670ca3ea20c7243c4f07532a1919bb9b98cb42e7af07`이다. 발행 687건은
모두 `MONTH_EVENT_SHA` lineage이고 COMPLETE 629건, PARTIAL 58건이다. NOT_FOUND 291건,
HISTORICAL_HEAD_UNAVAILABLE 17건, FAILED 5건은 기술 미사용으로 바꾸지 않았다.

parser v6와 `registry-20260911.4` 기본 정책 실행은 2개 파티션을 완료했고 분석 분모 309개,
관측 기술 24개, 고유 repo-tech pair 676개를 만들었다. 첫 호출에서 1개 파티션만 실행한 뒤
재개 호출이 이를 검증·재사용하고 나머지를 완료했으며, 완료 재호출은 2개를 모두 재사용했다.
총 WebHDFS retry는 0회이고 Artifact 실행 실패는 0건이다. PARTIAL 포함 별도 실행은 분모
346개·기술 30개·repo-tech pair 936개였지만 미해결 행이 1,691개에서 6,378개로 증가했다.
따라서 기본 공개 Trend는 COMPLETE를 유지하고 PARTIAL은 품질 플래그가 있는 보조 집계로 둔다.
두 실행의 품질은 미지원 Artifact와 미해결 매핑 때문에 `INSUFFICIENT_DATA`이며 실행 실패를
뜻하지 않는다. Worker PostgreSQL 게시, 운영 image, B/FE 연결, 3~8월 Top10k는 별도 인수다.

## 완료 입력 loader와 CLI

`github.snapshot_input.load_published_snapshot(root_uri, reader)`는 운영자가 고정한 HDFS
root의 `_SUCCESS.json`과 Snapshot/summary/failures JSON 세 개만 읽는다.
reader는 `read(uri, *, max_bytes)`와 `stat(uri)`를 제공한다. publish manifest v1의
필수 세 객체 URI는 각각 같은 root의 `snapshot.json`, `run-summary.json`, `failures.json`과
정확히 일치해야 한다. 모든 원문 SHA-256과 각 파일의 읽기 전후 length/modificationTime/fileId를
검증하고 마지막에 marker bytes 및 identity를 다시 읽어 일치시킨다. 기본 상한은 marker 1MiB,
각 JSON 64MiB, 두 번의 marker 읽기를 포함한 전체 200MiB다. 실패 시 부분 Batch를 반환하지 않는다.

반환 `PublishedSnapshot`은 batch, source_root, source_sha256, manifest_sha256,
summary_sha256, failures_sha256 및 quality를 포함한다. quality는 후보/실제 Snapshot/실패 수,
상태별 수, Snapshot 밖 NOT_FOUND/FAILED 수, COMPLETE Artifact 유무, Artifact 종류·수,
tree==commit 관측 수를 구분한다. summary의 부가 운영 필드를 필수로 가정하지 않으며
bootstrap-summary/v1과 repo-fetch-run-summary/v1의 dataset/run/record_count/status_counts/repos,
failures/v1의 dataset/failure_count/repos를 대조한다. ID/rank 중복·상태·집계 불일치는 거부한다.
bootstrap-summary/v1은 A bootstrap CLI와 같이 `1..top_n_limit` 후보 rank 전체를 요구하며,
`snapshot_published=true` 및 `stopped_reason=null`이어야 한다. summary/failures에서 같은
후보를 함께 제거해 내부 건수만 맞춘 입력이나 조기 중단 입력을 완료로 소비하지 않는다.
일반 repo-fetch-run-summary/v1은 이 전체 Top-N 조건을 강제하지 않고 유효한 부분 후보
범위와 원본 상태를 유지한다.
Snapshot에 없는 것은 NOT_FOUND 또는 FAILED만 허용하며 가짜 Snapshot record를 생성하지 않는다.
Tree 구조 경고는 품질 정보이고 외부 GitHub tree를 검증했다는 뜻이 아니다.

`python -m github.public_run --mode mirror`는 로컬 Snapshot 및 고정 Artifact mirror를 사용한다.
`--mode hdfs`는 고정 `--root-uri`, `--namenode-base-url`과 운영자가 환경 변수
`C_PUBLIC_DATANODE_ROUTES_JSON`에 지정한 origin→origin JSON 매핑을 사용한다.
정정 Snapshot이 이전 불변 Snapshot의 Artifact를 그대로 참조하면 반복 가능한
`--artifact-root-uri`로 그 Artifact namespace만 추가 허용한다. 이 값은 Snapshot
원문에서 자동 추론하지 않으며 기본 metadata root와 같은 HDFS authority여야 한다.
reader는 metadata root와 운영자가 명시한 Artifact root 밖 URI를 계속 거절한다.
`--registry`, `--checkpoint-dir`와 분할 옵션으로 실행하며 `--plan-only`는 Artifact 본문을
읽지 않는다. HDFS 모드의 plan-only도 완료 입력 JSON을 읽고, 모든 Artifact URI가 metadata
root 또는 명시한 Artifact root 안인지 먼저 검증한다.
로컬 전체 결과가 완료된 경우에만 최종 파일 경로를 알린다. CLI 자체는 API/DB에 저장하지 않는다.

## 최종 단일 DB 게시

`worker.public_intake.PublicPipelineConsumer(published, reader, registry, checkpoint_dir,
registry_sha256, store, *, include_partial=False, max_records=500,
max_declared_bytes=50_000_000)`는 검증된 `PublishedSnapshot`과 승인 `TechnologyRegistry`를
주입받는다. 원격 loader 호출과 주기 실행은 운영 factory가 담당한다.
`poll_once(max_new_partitions=1)`은 진행 중 IN_PROGRESS를 반환하고 DB event claim이나
PUBLIC_GITHUB Snapshot 게시를 하지 않는다. 전체 완료 후에만 생성 시각
`batch.generated_at`으로 PUBLIC_REPO event를 claim하고 LeaseHeartbeat 아래에서 단일 결과를
원자적으로 저장한다. 다른 실행이 DB lease를 보유하면 PREPARING, 이미 게시했으면 기존
결과 참조와 COMPLETED를 반환한다. 재시작 시 DB 상태와 검증된 로컬 파티션을 재사용한다.

event ID는 source/manifest/Registry/parser/policy/partition에 바인딩된 pipeline_id와
게시 출처 metadata에 대해 결정적이다. request hash에는 최종 result hash도 포함하여
같은 event에 다른 결과를 덮어쓰지 않는다. DB commit 뒤 응답 유실 시에도 같은 event ID를
다시 조회한다. 게시 실패는 lease-fenced 실패 기록을 시도하고 다음 poll에서 재시도한다.
로컬 _SUCCESS는 로컬 계산 완료이고 DB 게시 완료를 대신하지 않는다.

DB payload는 `schema_version="c-public-published-result/v1"`, `result=PublicBatchResult`,
`publication={source_root, source_sha256, manifest_sha256, summary_sha256, failures_sha256,
quality, pipeline_id}`다. 후보 20,000개와 Snapshot/분모 차이 및 원본 경고를 보존한다.
stream도 이 게시 schema와 source/pipeline identity로 고정하여 기존 bare PublicBatchResult
API 결과와 섞이지 않는다. 품질 INSUFFICIENT_DATA라도 전체 처리가 끝났으면 실행/게시
COMPLETED일 수 있으며, 품질 경고를 READY로 바꾸지 않는다.
