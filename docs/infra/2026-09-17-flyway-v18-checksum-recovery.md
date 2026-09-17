# Flyway V18 체크섬 충돌 복구

## 장애

Jenkins `#182`는 빌드와 테스트를 통과했지만 서비스 서버의 Backend가 시작되지
않아 실패했다. Flyway가 운영 DB에 기록된 V18과 새 이미지의 V18을 서로 다른
마이그레이션으로 판단했다.

```text
Migration checksum mismatch for migration version 18
Applied to database : 1989791899
Resolved locally    : 2081033767
```

운영 DB에 적용된 V18은
`V18__technology_candidate_ecosystem_go_cargo_composer.sql`이었다. 다른 브랜치가
`V18__technology_summary_cache.sql`을 같은 번호로 추가했고, 병합 과정에서 생태계
마이그레이션만 V20으로 옮겨졌다. 결과적으로 운영 DB의 V18과 저장소의 V18이
서로 다른 작업을 가리켰다.

## 복구 결정

- 운영에 이미 적용된 생태계 마이그레이션을 원래 V18 이름과 내용으로 복원한다.
- 기술 요약 캐시 테이블은 아직 운영에 적용되지 않았으므로 V21로 옮긴다.
- 이미 공개된 V20은 삭제하거나 내용을 바꾸지 않는다. V18과 동일한 제약을 한 번
  더 교체하는 것은 안전하며, V20을 적용한 다른 환경도 Flyway 검증을 통과한다.
- 운영 DB의 실제 제약은 이미 `MAVEN`, `NPM`, `PYPI`, `NUGET`, `GO`, `CARGO`,
  `COMPOSER`를 허용한다. 따라서 체크섬을 강제로 덮는 `flyway repair`는 사용하지
  않는다.

재배포 시 Flyway는 운영 DB의 V18과 V19를 검증한 뒤 V20, V21을 순서대로
적용한다. V20은 기존 생태계 제약을 같은 정의로 다시 만들고, V21이
`technology_summary` 테이블을 생성한다.

## 재발 방지

`Infra/scripts/check-flyway-migrations.sh`를 Jenkins Validate 단계에 연결했다.

- 동일 버전 파일이 둘 이상이면 실패한다.
- 운영 적용 V18의 파일명과 SHA-256이 달라지면 실패한다.
- 호환성 V20이 V18과 달라지면 실패한다.
- 기술 요약 캐시가 V21 이외 번호로 돌아가면 실패한다.

앞으로 운영에 한 번이라도 적용된 `V*__*.sql`은 수정·삭제·번호 변경하지 않고,
모든 스키마 변경을 새 버전 파일로 추가한다.
