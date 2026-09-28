# 최신 DB 덤프

기준일: 2026-09-28

DBMS: PostgreSQL 16.4

형식: PostgreSQL custom format (`pg_dump -Fc`), gzip 레벨 9, owner/ACL 제외

생성 시점 운영 DB 논리 크기: 약 2.5GB

압축 덤프 크기: 675,500,051 bytes

## 파일

- `gitjob_20260928.dump`: 최신 운영 DB 전체 덤프
- `gitjob_20260928.dump.sha256`: 무결성 확인값

덤프에는 사용자 및 운영 데이터가 포함될 수 있다. 공개 저장소나 공개 링크로 배포하지 않는다.

## 무결성 확인

```bash
sha256sum -c gitjob_20260928.dump.sha256
pg_restore --list gitjob_20260928.dump >/dev/null
```

## 새 PostgreSQL에 복구

대상 DB를 미리 만들고 PostgreSQL 16 계열의 `pg_restore`를 사용한다.

```bash
createdb -h <DB_HOST> -p 5432 -U <DB_ADMIN_USER> <NEW_DB_NAME>
pg_restore \
  --host <DB_HOST> \
  --port 5432 \
  --username <DB_ADMIN_USER> \
  --dbname <NEW_DB_NAME> \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  gitjob_20260928.dump
```

운영 DB에 덮어쓰지 말고 빈 검증용 DB에서 먼저 복구 시험을 한다. Backend를 연결하기 전 Flyway history와 스키마를 확인한다.

## 덤프 재생성

서비스 EC2의 PostgreSQL 컨테이너에서 읽기 전용 dump를 생성한다.

```bash
docker exec gitjob-service-postgres-1 \
  pg_dump -U <POSTGRES_USER> -d <POSTGRES_DB> \
  -Fc -Z9 --no-owner --no-privileges \
  > gitjob_YYYYMMDD.dump
```

`POSTGRES_USER`, `POSTGRES_DB`는 서비스 EC2의 `.env.service` 값을 사용한다. 비밀번호나 실제 값을 문서/명령 기록에 남기지 않는다.
