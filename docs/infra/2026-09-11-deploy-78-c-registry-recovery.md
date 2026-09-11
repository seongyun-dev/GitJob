# Jenkins Deploy #78 C Registry 복구 기록

> 상태: 복구 완료 / 기준일: 2026-09-11

## 1. 실패 판정

Jenkins #78은 build와 두 서버 배포를 완료했다. service 서버의 core/app readiness와
data 서버의 HDFS·Spark·Collector·Worker container health도 모두 통과했다. 마지막
`verify-deployment.sh`에서 data Worker가 아래 상태를 반환해 job이 실패했다.

```text
worker-ready  ACTION  Registry 미준비 — 승인 snapshot과 Worker 시작 로그 확인 필요
error: deployment finished but 1 host(s) are not ready
```

따라서 HDFS·Spark 2호스트 배포 실패가 아니라, 같은 deploy에 포함된 C Worker의
운영 DB 준비 누락을 사후 검사가 정확히 차단한 것이다.

## 2. 원인

운영 PostgreSQL에는 B Registry 세 버전이 있었지만 C 전용
`technology_registry_alias` 행은 없었다. Worker 로그와 인증된 `/ready`는
`RegistryVersionUnavailable` / `C_REGISTRY_UNAVAILABLE`을 반환했다.

기존 C JSON의 concrete version `registry-20260908.1`은 운영 DB의 B seed와 이미
같은 이름이었다. B row에는 C content hash와 source provenance가 없고 내용 범위도
다르므로 importer가 이 버전을 덮어쓰지 않는 것이 정상이다. 기존 문서의 “B와 겹치지
않는 별도 C version” 조건을 만족하는 실제 운영 artifact가 빠져 있었다.

## 3. 코드 보정

- 승인 C snapshot `technology_registry_20260911_1.json`
  (`registry-20260911.1`) 추가
- Worker image build에서 새 snapshot과 provenance를 검증
- file mode 기본값도 같은 immutable version으로 통일
- DB 비밀번호를 host 명령행에 노출하지 않는 `c-registry-import.sh` 추가
- 기존 `registry-20260908.1` snapshot은 B seed와 충돌하므로 수정·덮어쓰기 없이 보존

커밋:

```text
5ca8855 [S15P21E102-207] fix: C Registry 승인본 배포 복구
```

## 4. 운영 복구

data 서버에서 해당 커밋으로 Worker image만 다시 만들었다. Docker build의 Registry
contract/provenance 검증을 통과한 뒤 Worker만 재생성했다. Collector, HDFS, Spark와
service 서버 container는 재시작하지 않았다.

새 snapshot import와 family alias 활성화 결과:

```text
schema_version: technology-registry/v1
registry_version: registry-20260911.1
content_sha256: 5f54ecf1a6aa09817b0cc3c702daa991795d66daa94ceb262f1f3b7882efddbf
source_ref: AI/registry/data/technology_registry_20260911_1.json
```

그 다음 검사에서 별개 누락인 `c_compute 스키마 없음`이 확인돼 기존의 재실행 안전한
`c-compute-migrate.sh`를 적용하고 Worker를 재시작했다.

## 5. 최종 검증

```text
schema          SKIP  core 프로필이 이 호스트에 없다
cdc-objects     SKIP  core 프로필이 이 호스트에 없다
cdc-connector   SKIP  core 프로필이 이 호스트에 없다
entry-point     SKIP  app 프로필이 이 호스트에 없다
worker-ready    OK    C compute 준비됨
```

승인본과 기존 snapshot을 같은 Worker image에서 읽어 version만 다르고 기술 47개와
mapping 58개의 내용이 동일한 것도 확인했다. 운영 DB의 alias와 `c_compute` migration은
영속 상태이므로 #78과 같은 develop deploy를 다시 실행해도 이 준비 단계에서 실패하지
않는다.

## 6. 후속 서버 점검에서 발견한 repository analysis 누락

후속 develop 배포 뒤 HDFS·Spark와 C Worker는 정상이었지만 `analysis-worker`가
`repo_analysis.event_claim` 누락으로 재시작 중이었다. 이 SQL은 Python consumer가
소유해 Spring Flyway 대상이 아니지만, 기존 배포는 문서의 수동 선행 조건을 실행하지
않았고 두 health gate도 해당 컨테이너를 검사하지 않았다.

후속 수정은 service core 기동 직후 `repo-analysis-migrate.sh`를 재실행 안전하게
적용한 뒤 data 서비스를 기동하도록 순서를 고정했다. `healthcheck.sh`와
`verify-deployment.sh`에도 `analysis-worker`의 안정적인 `running` 상태를 추가해 같은
누락이 다시 생기면 배포가 즉시 실패하도록 했다.

migration 적용 뒤 consumer process는 실행됐지만, 자동 topic 생성이 꺼진 broker에
repository-analysis 요청·결과·DLQ topic이 하나도 없어 `topic not found`가 이어졌다.
세 topic을 각각 3 partition으로 `kafka-topics.sh`의 선언 대상에 넣고, deploy가
service core 직후 생성·검증하도록 보완했다. 최종 준비 검사는 topic 계약도 별도
항목으로 판정한다.
