# db 디렉터리

네 개의 하위 디렉터리가 있고 **적용 주체가 서로 다르다.** 새 SQL을 추가하기 전에
어디에 넣어야 하는지 확인한다.

| 디렉터리 | 적용 주체 | 시점 |
| --- | --- | --- |
| `migration/` | **Flyway** (Spring Boot 자동설정) | backend 기동 시 자동 |
| `cdc/` | 사람 | Debezium을 쓸 때 1회 수동 |
| `migrations/` | **C조 자체 러너** (`python -m worker.migrate`) | 수동 |

## `migration/` 과 `migrations/` 는 다른 것이다

s 한 글자 차이인데 완전히 다른 시스템이다. 헷갈리기 쉬우므로 주의한다.

- `migration/` (단수): Flyway가 읽는 위치다. `V<번호>__<설명>.sql` 규칙을 지켜야 하고,
  이름이 어긋나면 Flyway가 **조용히 무시한다**. 적용 이력은 `flyway_schema_history`에 남는다.
- `migrations/` (복수): C조의 `c_compute` 스키마용이다. `AI/worker/store.py`가 이 경로를
  하드코딩해서 읽고, 적용 이력은 `c_compute.schema_version`에 따로 남긴다. Flyway는 이
  디렉터리를 보지 않는다.

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
