-- S15P21E102-121. Registry 버전 공존, 참조 무결성, 대리키 채번.
--
-- 세 가지를 함께 처리한다. 순서를 나누면 FK를 두 번 붙이게 되기 때문이다.
--
-- 1) 버전 공존: registry_version을 가진 테이블이 여섯인데 technology의 기본키가
--    tech_id 단독이라 같은 기술이 두 버전에 존재할 수 없었다. 분석 요청 이벤트가
--    registry_version을 박아 보내는 이유가 "그때 기준으로 재현"인데 스키마가 그걸
--    담지 못했다. evidence_rule도 같은 문제라 함께 고친다.
-- 2) 참조 무결성: V1에 FK가 하나도 없었다. ERDCloud는 관계선이 그려져 있으면 FK를
--    내보내므로(docs/be/analysis-outbox-erdcloud.sql이 그 예) ERD에 관계가 없었던 것이다.
--    지금 테이블이 거의 비어 있어 붙이는 비용이 가장 낮다.
-- 3) 채번: user_id만 IDENTITY이고 나머지 대리키는 전부 맨 BIGINT였다. 애플리케이션이
--    행을 만들 수단이 없어 Evidence 기록을 시작할 수 없다.

-- ---------------------------------------------------------------------------
-- 1. 버전 공존
-- ---------------------------------------------------------------------------

-- 다른 테이블이 버전을 참조하려면 registry_version 자체가 유일해야 한다.
ALTER TABLE "technology_registry"
    ADD CONSTRAINT "UQ_TECHNOLOGY_REGISTRY_VERSION" UNIQUE ("registry_version");

ALTER TABLE "technology" DROP CONSTRAINT "PK_TECHNOLOGY";
ALTER TABLE "technology"
    ADD CONSTRAINT "PK_TECHNOLOGY" PRIMARY KEY ("tech_id", "registry_version");

-- 규칙도 버전마다 달라질 수 있다. rule_id 단독 기본키는 같은 규칙을 두 버전에
-- 둘 수 없게 만든다.
ALTER TABLE "evidence_rule" DROP CONSTRAINT "PK_EVIDENCE_RULE";
ALTER TABLE "evidence_rule"
    ADD CONSTRAINT "PK_EVIDENCE_RULE" PRIMARY KEY ("rule_id", "registry_version");

-- 절은 부모가 복합키가 되면서 버전을 함께 들어야 한다. 부모에서 채워 넣는다.
ALTER TABLE "evidence_rule_clause" ADD COLUMN "registry_version" TEXT;
UPDATE "evidence_rule_clause" c
SET "registry_version" = r."registry_version"
FROM "evidence_rule" r
WHERE r."rule_id" = c."rule_id";
ALTER TABLE "evidence_rule_clause" ALTER COLUMN "registry_version" SET NOT NULL;

-- Evidence는 "어느 버전의 규칙이 맞았는지"를 남겨야 재현할 수 있다. 지금 비어 있어
-- 백필이 필요 없다.
ALTER TABLE "analysis_evidence" ADD COLUMN "registry_version" TEXT NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. 참조 무결성
--
-- ON DELETE는 붙이지 않는다. Registry 버전과 분석 결과는 지우는 것이 아니라 보존하는
-- 데이터이고, 지워야 할 때는 순서를 사람이 정하는 편이 낫다. 실수로 상위 행을 지웠을 때
-- 하위가 조용히 사라지는 쪽이 더 위험하다.
-- ---------------------------------------------------------------------------
ALTER TABLE "technology"
    ADD CONSTRAINT "FK_TECHNOLOGY_REGISTRY" FOREIGN KEY ("registry_version")
        REFERENCES "technology_registry" ("registry_version");

ALTER TABLE "technology_category"
    ADD CONSTRAINT "FK_TECHNOLOGY_CATEGORY_TECHNOLOGY" FOREIGN KEY ("tech_id", "registry_version")
        REFERENCES "technology" ("tech_id", "registry_version");

ALTER TABLE "technology_mapping"
    ADD CONSTRAINT "FK_TECHNOLOGY_MAPPING_TECHNOLOGY" FOREIGN KEY ("tech_id", "registry_version")
        REFERENCES "technology" ("tech_id", "registry_version");

ALTER TABLE "evidence_rule"
    ADD CONSTRAINT "FK_EVIDENCE_RULE_TECHNOLOGY" FOREIGN KEY ("tech_id", "registry_version")
        REFERENCES "technology" ("tech_id", "registry_version");

ALTER TABLE "evidence_rule_clause"
    ADD CONSTRAINT "FK_EVIDENCE_RULE_CLAUSE_RULE" FOREIGN KEY ("rule_id", "registry_version")
        REFERENCES "evidence_rule" ("rule_id", "registry_version");

-- clause_id와 predicate_id는 버전과 무관하게 유일한 대리키라 단일 컬럼으로 충분하다.
ALTER TABLE "evidence_rule_predicate"
    ADD CONSTRAINT "FK_EVIDENCE_RULE_PREDICATE_CLAUSE" FOREIGN KEY ("clause_id")
        REFERENCES "evidence_rule_clause" ("clause_id");

ALTER TABLE "evidence_rule_predicate_value"
    ADD CONSTRAINT "FK_PREDICATE_VALUE_PREDICATE" FOREIGN KEY ("predicate_id")
        REFERENCES "evidence_rule_predicate" ("predicate_id");

-- 기대값이 tech_id/registry_version을 따로 들고 있는 것은 비정규화다. FK를 붙여
-- 상위 규칙과 다른 기술을 가리키는 일이 없게 한다.
ALTER TABLE "evidence_rule_predicate_value"
    ADD CONSTRAINT "FK_PREDICATE_VALUE_TECHNOLOGY" FOREIGN KEY ("tech_id", "registry_version")
        REFERENCES "technology" ("tech_id", "registry_version");

ALTER TABLE "analysis_job"
    ADD CONSTRAINT "FK_ANALYSIS_JOB_USER" FOREIGN KEY ("user_id")
        REFERENCES "user" ("user_id");

ALTER TABLE "analysis_evidence"
    ADD CONSTRAINT "FK_ANALYSIS_EVIDENCE_JOB" FOREIGN KEY ("analysis_id")
        REFERENCES "analysis_job" ("analysis_id");
ALTER TABLE "analysis_evidence"
    ADD CONSTRAINT "FK_ANALYSIS_EVIDENCE_USER" FOREIGN KEY ("user_id")
        REFERENCES "user" ("user_id");
ALTER TABLE "analysis_evidence"
    ADD CONSTRAINT "FK_ANALYSIS_EVIDENCE_RULE" FOREIGN KEY ("rule_id", "registry_version")
        REFERENCES "evidence_rule" ("rule_id", "registry_version");

ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "FK_EVIDENCE_COMMIT_EVIDENCE" FOREIGN KEY ("analysis_evidence_id")
        REFERENCES "analysis_evidence" ("analysis_evidence_id");
ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "FK_EVIDENCE_COMMIT_JOB" FOREIGN KEY ("analysis_id")
        REFERENCES "analysis_job" ("analysis_id");
ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "FK_EVIDENCE_COMMIT_USER" FOREIGN KEY ("user_id")
        REFERENCES "user" ("user_id");

-- repository_commit.repository_id는 GitHub 숫자 ID를 문자열로 담은 값이고 대응하는
-- 테이블이 없다. analysis_job.repository_id도 같아서 둘 다 FK를 붙이지 않는다.

-- PostgreSQL은 FK 자식 컬럼을 자동으로 인덱싱하지 않는다. 상위 행을 지우거나 조인할
-- 때마다 전체 스캔이 된다.
CREATE INDEX "idx_technology_registry_version" ON "technology" ("registry_version");
CREATE INDEX "idx_technology_category_tech" ON "technology_category" ("tech_id", "registry_version");
CREATE INDEX "idx_technology_mapping_tech" ON "technology_mapping" ("tech_id", "registry_version");
CREATE INDEX "idx_evidence_rule_tech" ON "evidence_rule" ("tech_id", "registry_version");
CREATE INDEX "idx_evidence_rule_clause_rule" ON "evidence_rule_clause" ("rule_id", "registry_version");
CREATE INDEX "idx_evidence_rule_predicate_clause" ON "evidence_rule_predicate" ("clause_id");
CREATE INDEX "idx_predicate_value_predicate" ON "evidence_rule_predicate_value" ("predicate_id");
CREATE INDEX "idx_predicate_value_tech" ON "evidence_rule_predicate_value" ("tech_id", "registry_version");
CREATE INDEX "idx_analysis_job_user" ON "analysis_job" ("user_id");
CREATE INDEX "idx_analysis_evidence_job" ON "analysis_evidence" ("analysis_id");
CREATE INDEX "idx_analysis_evidence_user" ON "analysis_evidence" ("user_id");
CREATE INDEX "idx_analysis_evidence_rule" ON "analysis_evidence" ("rule_id", "registry_version");
CREATE INDEX "idx_evidence_commit_evidence" ON "analysis_evidence_commit" ("analysis_evidence_id");
CREATE INDEX "idx_evidence_commit_job" ON "analysis_evidence_commit" ("analysis_id");
CREATE INDEX "idx_evidence_commit_user" ON "analysis_evidence_commit" ("user_id");

-- 기술 조회에서 가장 잦은 접근은 "이 import가 어느 기술인가"다.
CREATE INDEX "idx_technology_mapping_lookup"
    ON "technology_mapping" ("mapping_type", "ecosystem", "value")
    WHERE "status" = 'ACTIVE';

-- ---------------------------------------------------------------------------
-- 3. 대리키 채번
--
-- BY DEFAULT이지 ALWAYS가 아니다. V3 시드처럼 id를 직접 지정하는 삽입이 계속 가능해야
-- 한다. 대신 시퀀스 시작값을 기존 최댓값 위로 올려 두지 않으면 애플리케이션의 첫 삽입이
-- 시드와 충돌한다.
-- ---------------------------------------------------------------------------
ALTER TABLE "technology_registry" ALTER COLUMN "technology_registry_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "technology_category" ALTER COLUMN "technology_category_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "technology_mapping" ALTER COLUMN "mapping_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "evidence_rule_clause" ALTER COLUMN "clause_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "evidence_rule_predicate" ALTER COLUMN "predicate_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "evidence_rule_predicate_value" ALTER COLUMN "predicate_value_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "analysis_evidence" ALTER COLUMN "analysis_evidence_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "analysis_evidence_commit" ALTER COLUMN "analysis_evidence_commit_id" ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE "repository_commit" ALTER COLUMN "repository_commit_id" ADD GENERATED BY DEFAULT AS IDENTITY;

-- V3이 넣어 둔 id 위에서 시작하게 한다. 빈 테이블은 coalesce가 1을 준다.
SELECT setval(pg_get_serial_sequence('technology_registry', 'technology_registry_id'),
              coalesce((SELECT max(technology_registry_id) FROM technology_registry), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('technology_category', 'technology_category_id'),
              coalesce((SELECT max(technology_category_id) FROM technology_category), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('technology_mapping', 'mapping_id'),
              coalesce((SELECT max(mapping_id) FROM technology_mapping), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('evidence_rule_clause', 'clause_id'),
              coalesce((SELECT max(clause_id) FROM evidence_rule_clause), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('evidence_rule_predicate', 'predicate_id'),
              coalesce((SELECT max(predicate_id) FROM evidence_rule_predicate), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('evidence_rule_predicate_value', 'predicate_value_id'),
              coalesce((SELECT max(predicate_value_id) FROM evidence_rule_predicate_value), 0) + 1, false);
