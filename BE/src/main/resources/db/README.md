# db 디렉터리

네 개의 하위 디렉터리가 있고 **적용 주체가 서로 다르다.** 새 SQL을 추가하기 전에
어디에 넣어야 하는지 확인한다.

| 디렉터리 | 적용 주체 | 시점 |
| --- | --- | --- |
| `migration/` | **Flyway** (Spring Boot 자동설정) | backend 기동 시 자동 |
| `cdc/` | 사람 | Debezium을 쓸 때 1회 수동 |
| `c-compute/` | **C조 자체 러너** (`python -m worker.migrate`) | 수동 |
| `migrations/` | **저장소 분석 Worker 운영자** (`psql -f`) | analysis-worker 기동 전 수동 |

## `migration/` 과 `c-compute/` 를 합치지 않는 이유

Flyway로 통합하면 세 가지가 깨진다.

1. `docs/ai/c-compute-runtime.md`가 "API가 시작하면서 DDL을 자동 실행하지 않는다"고
   명시한다. Flyway는 기동 시 자동 실행이 본질이라 이 원칙과 정면으로 어긋난다.
2. `c_compute.schema_version`은 이력 테이블이 아니라 런타임 계약이다. `AI/worker/store.py`의
   `ready()`가 이 테이블에서 버전 행을 찾아 `/ready` 응답을 결정한다. Flyway가 소유하면
   기록이 `flyway_schema_history`로 가므로 `/ready`가 영원히 준비되지 않은 것으로 보인다.
3. worker는 데이터 호스트, backend는 서비스 호스트에 있다. 합치면 서비스 호스트의
   backend가 기동하면서 다른 호스트 서비스의 스키마를 만들게 된다.

기능적으로 겹치지도 않는다. Flyway는 `public`만, C 러너는 `c_compute`만 만든다.

`c-compute/`는 한때 `migrations/`(복수)였다. 현재 복수형 디렉터리는
`repo_analysis` 스키마를 위한 별도 수동 SQL만 둔다. `migration/`과 s 한 글자 차이라,
새 Flyway 마이그레이션을 복수 쪽에 넣으면 여전히 **에러 없이 조용히 무시된다.**

- `migration/`: Flyway가 읽는다. `V<번호>__<설명>.sql` 규칙을 지켜야 하고, 이름이 어긋나면
  무시된다. 적용 이력은 `flyway_schema_history`에 남는다.
- `c-compute/`: `AI/worker/store.py`가 경로를 하드코딩해 읽고, 이력은
  `c_compute.schema_version`에 남긴다. Flyway는 이 디렉터리를 보지 않는다.
- `migrations/`: 저장소 checkout에서 운영자가 `psql -f`로 적용한다. 현재
  `002_repo_analysis.sql`만 있으며 `repo_analysis` 스키마를 만든다. Flyway와 C조 러너는
  이 디렉터리를 읽지 않고, Worker 이미지에도 자동으로 포함하거나 적용하지 않는다.

`c_compute`는 대응하는 JPA 엔티티가 없어 Hibernate `validate` 대상이 아니다. 그래서
적용하지 않아도 backend는 정상 기동하고, worker 컨테이너도 healthy로 뜬다. 준비가 안 된
것은 `GET /ready`가 `C_MIGRATION_REQUIRED`로만 알려주는데, 이 엔드포인트를 자동으로
호출하는 곳이 없다. **배포 후 `python -m worker.migrate`를 실행했는지 직접 확인해야 한다.**

## `cdc/` 를 Flyway로 옮기지 않은 이유

`cdc_prerequisites.sql`은 세 가지 이유로 마이그레이션이 될 수 없다.

1. 비밀번호를 치환해 넣어야 한다. 마이그레이션에 넣으면 그 값이 애플리케이션 설정으로
   들어가야 하고, 지금은 kafka-connect만 알면 되는 비밀이 backend까지 퍼진다.
2. `CREATE ROLE`은 스키마 변경이 아니라 클러스터 레벨 객체다. 애플리케이션 DB 유저에게
   `CREATEROLE` 권한을 줄 이유가 없다.
3. `CREATE ROLE`과 `CREATE PUBLICATION`은 재실행할 수 없다. 마이그레이션이 한 번
   실패하면 그 뒤로 애플리케이션이 아예 기동하지 못한다.

절차는 `docs/be/analysis-outbox.md`를 따른다.

## 새 스키마 변경을 추가할 때

`migration/`에 다음 번호로 파일을 만든다. 기존 파일은 **수정하지 않는다** — Flyway가
체크섬을 비교해 이미 적용된 파일이 바뀌면 기동을 거부한다.

```
V3__<설명>.sql
```
