-- S15P21E102-121. 규칙이 패턴을 다시 적지 않게 한다.
--
-- V3의 L1 규칙 세 개는 technology_mapping의 IMPORT_PATH 행을 그대로 옮겨 적은
-- 것이었다.
--
--   technology_mapping   org.apache.kafka  PREFIX(JAVA)  -> apache-kafka
--   evidence_rule_clause org.apache.kafka  PREFIX(.)     -> apache-kafka.l1.import
--
-- Redis 클라이언트를 하나 추가하려면 두 곳을 고쳐야 하고, 한쪽을 빠뜨려도 아무
-- 오류가 나지 않는다. 매핑만 고치면 후보에서는 사라지는데 L1은 안 붙고, 규칙만
-- 고치면 그 반대가 된다.
--
-- 역할을 가른다.
--
--   매핑   "무슨 기술인가"   prefix·좌표 목록의 유일한 원천
--   규칙   "어느 수준인가"   해석된 tech_id 위의 조건
--
-- 판정은 두 단계가 된다. 먼저 fact를 매핑으로 해석해 tech_id를 얻고, 그 다음
-- 규칙을 해석된 fact 위에서 평가한다. 그래서 L1 절은 "IMPORT fact 하나가
-- apache-kafka로 해석되면 성립"이라고만 말하면 되고, 언어별 group도 필요 없다 —
-- 언어 분기는 이미 매핑이 하고 있다.
--
-- L3 규칙은 건드리지 않는다. org.springframework.boot.actuate는 매핑보다 세밀해
-- 어디에도 중복되지 않는다. 규칙은 매핑이 표현할 수 없는 것만 표현하게 된다.

-- ---------------------------------------------------------------------------
-- 0. 이 마이그레이션이 성립하는 조건
--
-- V5가 "한 registry_version의 내용은 불변"으로 정했다. 아래는 그 원칙의 예외이고,
-- 예외인 이유는 registry-20260908.1로 판정된 분석이 아직 하나도 없기 때문이다.
-- 재현할 과거가 없으면 불변성이 보호할 것도 없다.
--
-- 이 전제가 깨졌다면 되돌릴 방법이 없으므로 여기서 멈춘다. 그때는 이 파일이
-- 아니라 새 버전을 발행해야 한다.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM analysis_evidence
               WHERE registry_version = 'registry-20260908.1') THEN
        RAISE EXCEPTION
            'registry-20260908.1로 판정된 Evidence가 있다. 이 버전을 고치는 대신 새 버전을 발행해야 한다';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. L1 규칙의 절을 해석된 tech_id 조건으로 바꾼다
--
-- 삭제는 FK 방향의 역순으로 한다. clause_id는 새로 만들지 않고 재사용한다 —
-- V4가 IDENTITY 시퀀스를 시드 최대값 바로 위로 맞춰 두었으므로, 그보다 큰 값을
-- 손으로 넣으면 나중에 자동 생성이 충돌한다.
-- ---------------------------------------------------------------------------
DELETE FROM evidence_rule_predicate_value
WHERE predicate_id IN (401, 421, 422, 423, 441, 442, 443);

DELETE FROM evidence_rule_predicate
WHERE predicate_id IN (401, 421, 422, 423, 441, 442, 443);

-- 언어별 group은 더 이상 필요 없다. 남길 절만 남기고 나머지를 지운다.
DELETE FROM evidence_rule_clause
WHERE clause_id IN (322, 323, 342, 343);

UPDATE evidence_rule_clause
SET clause_key = 'resolved-tech',
    group_no = 1,
    clause_order = 1
WHERE clause_id IN (301, 321, 341);

INSERT INTO evidence_rule_predicate
    (predicate_id, clause_id, fact_field, match_operator, segment_delimiter, predicate_order) VALUES
    -- TECH_ID는 원문 필드가 아니라 매핑이 붙여 준 값이다. 한 fact가 여러 기술로
    -- 해석될 수 있으므로(매핑이 겹치면) 하나라도 같으면 성립한다.
    (401, 301, 'TECH_ID', 'EXACT', NULL, 1),
    (421, 321, 'TECH_ID', 'EXACT', NULL, 1),
    (441, 341, 'TECH_ID', 'EXACT', NULL, 1);

INSERT INTO evidence_rule_predicate_value
    (predicate_value_id, value_order, predicate_id, tech_id, registry_version, expected_value) VALUES
    (501, 1, 401, 'spring-boot',  'registry-20260908.1', 'spring-boot'),
    (521, 1, 421, 'apache-kafka', 'registry-20260908.1', 'apache-kafka'),
    (561, 1, 441, 'redis',        'registry-20260908.1', 'redis');

-- 규칙 설명도 실제 조건을 말하게 고친다. 언어 목록은 이제 매핑에 있다.
UPDATE evidence_rule
SET description = 'spring-boot로 해석되는 import가 있으면 이 저장소가 Spring Boot 위에서 동작한다고 본다. '
                  'import 경로 목록은 technology_mapping이 갖는다.'
WHERE rule_id = 'spring-boot.l1.java-import';

UPDATE evidence_rule
SET description = 'apache-kafka로 해석되는 import가 있으면 성립한다. Java·Python·JS 클라이언트 구분은 '
                  'technology_mapping의 IMPORT_PATH 행이 한다.'
WHERE rule_id = 'apache-kafka.l1.import';

UPDATE evidence_rule
SET description = 'redis로 해석되는 import가 있으면 성립한다. Spring Data Redis·Jedis·Lettuce·redis-py·'
                  'ioredis 구분은 technology_mapping의 IMPORT_PATH 행이 한다.'
WHERE rule_id = 'redis.l1.client-import';

-- ---------------------------------------------------------------------------
-- 2. 같은 뜻을 다르게 부르던 것을 맞춘다
--
-- technology_mapping.match_mode는 EXACT|PREFIX이고, 이것은 공유 계약
-- technology-registry-v1.schema.json의 MatchMode enum이라 우리 쪽에서 바꿀 수
-- 없다. 규칙 쪽 EQUALS를 EXACT로 맞추는 편이 범위가 작고, 평가기가 어휘를 두 벌
-- 들지 않아도 된다.
--
-- EQUALS를 쓰던 두 술어(423·443)는 위에서 이미 지워졌으므로 이 UPDATE는 지금
-- 0행을 고친다. 그래도 남겨 둔다: 아래 CHECK가 EQUALS를 거절하므로, 이 파일이
-- 적용되기 전에 손으로 넣은 행이 있었다면 여기서 살아남아야 한다.
-- ---------------------------------------------------------------------------
UPDATE evidence_rule_predicate
SET match_operator = 'EXACT'
WHERE match_operator = 'EQUALS';

-- ---------------------------------------------------------------------------
-- 3. 어휘를 주석이 아니라 제약으로 못박는다
--
-- 지금까지 이 값들은 varchar이고 규정은 V3 주석뿐이었다. 오타는 INSERT를 통과한
-- 뒤 "매칭되지 않는 규칙"으로만 나타나는데, 그건 기술을 쓰지 않는 저장소와
-- 구분되지 않는다.
-- ---------------------------------------------------------------------------
ALTER TABLE "evidence_rule"
    ADD CONSTRAINT "CK_EVIDENCE_RULE_TYPE"
        CHECK ("rule_type" IN ('L0', 'L1', 'L2', 'L3')),
    ADD CONSTRAINT "CK_EVIDENCE_RULE_SCOPE"
        CHECK ("evaluation_scope" IN ('REPOSITORY', 'PERSONAL'));

ALTER TABLE "evidence_rule_clause"
    ADD CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_ROLE"
        CHECK ("role" IN ('REQUIRED', 'OPTIONAL')),
    ADD CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_FACT_TYPE"
        CHECK ("fact_type" IN ('IMPORT', 'DEPENDENCY', 'ANNOTATION', 'CONFIG_KEY', 'API_CALL')),
    ADD CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_MIN_MATCH"
        CHECK ("min_match_count" >= 1);

-- TECH_ID는 매핑이 붙여 주는 파생 필드이고, COORDINATE·ECOSYSTEM·SCOPE는
-- DEPENDENCY fact가 들고 오는 필드다.
ALTER TABLE "evidence_rule_predicate"
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD"
        CHECK ("fact_field" IN ('MODULE', 'TECH_ID', 'COORDINATE', 'ECOSYSTEM',
                                'SCOPE', 'LANGUAGE', 'FILE_PATH')),
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_OPERATOR"
        CHECK ("match_operator" IN ('EXACT', 'PREFIX', 'SUFFIX', 'CONTAINS')),
    -- 구분자는 PREFIX·SUFFIX에서만 뜻이 있다. EXACT에 붙어 있으면 경계 검사를
    -- 하는 것처럼 읽히지만 아무 효과가 없다.
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_DELIMITER"
        CHECK ("segment_delimiter" IS NULL
               OR "match_operator" IN ('PREFIX', 'SUFFIX'));
