-- S15P21E102-121. Spring Boot / Apache Kafka / Redis 세 기술의 Registry·Evidence 시드.
--
-- tech_id와 display_name, 직무 도메인, 그리고 아래 "기존" 표시가 붙은 매핑은
-- AI/registry/data/technology_registry_20260908_1.json에서 그대로 가져왔다. 새로 짓지
-- 않은 이유는 RegistryMapper가 그 JSON을 읽기 때문이다. 여기서 다른 id를 쓰면 같은
-- 기술이 DB와 매퍼에서 서로 다른 것이 된다.
--
-- 이 스키마에는 FK가 없다. 참조 무결성은 이 파일의 INSERT 순서로만 지켜지므로
-- registry -> technology -> category/mapping -> rule -> clause -> predicate -> value
-- 순서를 바꾸지 않는다. BIGINT 기본키에도 시퀀스가 없어 id를 직접 부여한다
-- (애플리케이션이 행을 추가하려면 시퀀스를 먼저 만들어야 한다).

-- ---------------------------------------------------------------------------
-- 1. Registry 버전
-- ---------------------------------------------------------------------------
INSERT INTO technology_registry (technology_registry_id, registry_version, schema_version)
VALUES (1, 'registry-20260908.1', 'technology-registry/v1');

-- ---------------------------------------------------------------------------
-- 2. 기술
-- ---------------------------------------------------------------------------
INSERT INTO technology (tech_id, registry_version, display_name, status) VALUES
    ('spring-boot',  'registry-20260908.1', 'Spring Boot',  'ACTIVE'),
    ('apache-kafka', 'registry-20260908.1', 'Apache Kafka', 'ACTIVE'),
    ('redis',        'registry-20260908.1', 'Redis',        'ACTIVE');

-- ---------------------------------------------------------------------------
-- 3. 직무 도메인
-- ---------------------------------------------------------------------------
INSERT INTO technology_category (technology_category_id, job_domain, registry_version, tech_id) VALUES
    (101, 'BACKEND',        'registry-20260908.1', 'spring-boot'),
    (102, 'BACKEND',        'registry-20260908.1', 'apache-kafka'),
    (103, 'AI_DATA',        'registry-20260908.1', 'apache-kafka'),
    (104, 'INFRASTRUCTURE', 'registry-20260908.1', 'apache-kafka'),
    (105, 'BACKEND',        'registry-20260908.1', 'redis'),
    (106, 'INFRASTRUCTURE', 'registry-20260908.1', 'redis');

-- ---------------------------------------------------------------------------
-- 4. 매핑
--
-- IMPORT_PATH가 대부분인 이유는 저장소 분석 Worker가 내놓는 것이 import이기 때문이다
-- (AI/analysis/parse.py). ecosystem 값은 그 파서가 붙이는 값과 같은 어휘다.
--
-- PREFIX는 생태계별 구분자 경계에서만 맞는다(registry/normalization.py의
-- import_path_has_prefix). 그래서 org.springframework는 org.springframeworkfoo에
-- 걸리지 않는다. EXACT는 구분자가 없는 npm 패키지 이름처럼 하위 경로가 없을 때 쓴다.
-- ---------------------------------------------------------------------------
INSERT INTO technology_mapping
    (mapping_id, registry_version, tech_id, mapping_type, ecosystem, value, match_mode, status) VALUES
    -- Spring Boot
    (201, 'registry-20260908.1', 'spring-boot', 'PACKAGE',           'MAVEN',      'org.springframework.boot:spring-boot-starter-webmvc', 'EXACT',  'ACTIVE'), -- 기존
    (202, 'registry-20260908.1', 'spring-boot', 'IMPORT_PATH',       'JAVA',       'org.springframework.boot',                            'PREFIX', 'ACTIVE'), -- 기존
    (203, 'registry-20260908.1', 'spring-boot', 'ALIAS',             NULL,         'Spring Boot',                                         'EXACT',  'ACTIVE'),
    (204, 'registry-20260908.1', 'spring-boot', 'STACKOVERFLOW_TAG', NULL,         'spring-boot',                                         'EXACT',  'ACTIVE'),
    -- Apache Kafka. spring-kafka는 Kafka를 쓴다는 신호이므로 같은 tech_id로 모은다.
    (211, 'registry-20260908.1', 'apache-kafka', 'ALIAS',             NULL,        'Kafka',                                               'EXACT',  'ACTIVE'), -- 기존
    (212, 'registry-20260908.1', 'apache-kafka', 'STACKOVERFLOW_TAG', NULL,        'apache-kafka',                                        'EXACT',  'ACTIVE'), -- 기존
    (213, 'registry-20260908.1', 'apache-kafka', 'IMPORT_PATH',       'JAVA',      'org.apache.kafka',                                    'PREFIX', 'ACTIVE'),
    (214, 'registry-20260908.1', 'apache-kafka', 'IMPORT_PATH',       'JAVA',      'org.springframework.kafka',                           'PREFIX', 'ACTIVE'),
    (215, 'registry-20260908.1', 'apache-kafka', 'IMPORT_PATH',       'PYTHON',    'kafka',                                               'PREFIX', 'ACTIVE'),
    (216, 'registry-20260908.1', 'apache-kafka', 'IMPORT_PATH',       'JAVASCRIPT','kafkajs',                                             'EXACT',  'ACTIVE'),
    (217, 'registry-20260908.1', 'apache-kafka', 'PACKAGE',           'MAVEN',     'org.apache.kafka:kafka-clients',                      'EXACT',  'ACTIVE'),
    -- Redis. 클라이언트 라이브러리가 여럿이라 각각 매핑한다.
    (221, 'registry-20260908.1', 'redis', 'STACKOVERFLOW_TAG', NULL,         'redis',                             'EXACT',  'ACTIVE'), -- 기존
    (222, 'registry-20260908.1', 'redis', 'ALIAS',             NULL,         'Redis',                             'EXACT',  'ACTIVE'),
    (223, 'registry-20260908.1', 'redis', 'IMPORT_PATH',       'JAVA',       'org.springframework.data.redis',    'PREFIX', 'ACTIVE'),
    (224, 'registry-20260908.1', 'redis', 'IMPORT_PATH',       'JAVA',       'redis.clients.jedis',               'PREFIX', 'ACTIVE'),
    (225, 'registry-20260908.1', 'redis', 'IMPORT_PATH',       'JAVA',       'io.lettuce.core',                   'PREFIX', 'ACTIVE'),
    (226, 'registry-20260908.1', 'redis', 'IMPORT_PATH',       'PYTHON',     'redis',                             'PREFIX', 'ACTIVE'),
    (227, 'registry-20260908.1', 'redis', 'IMPORT_PATH',       'JAVASCRIPT', 'ioredis',                           'EXACT',  'ACTIVE'),
    (228, 'registry-20260908.1', 'redis', 'PACKAGE',           'MAVEN',      'org.springframework.boot:spring-boot-starter-data-redis', 'EXACT', 'ACTIVE');

-- ---------------------------------------------------------------------------
-- 5. Evidence 규칙
--
-- 이 아래의 어휘(rule_type, evaluation_scope, role, fact_type, fact_field,
-- match_operator)는 ERD에 컬럼만 있고 값이 정해진 적이 없다. 여기서 처음 정한다.
--
--   rule_type        L0|L1|L2|L3   docs/be/README.md 8절의 레벨. Evidence 응답의 level
--                                  L0 발견(의존성 선언) / L1 적용(import·설정·annotation)
--                                  L2 활용(핵심 API 호출·본인 기여) / L3 심화(운영 성숙도)
--   evaluation_scope REPOSITORY    저장소에 그 기술이 쓰였는지
--                    PERSONAL      본인 기여까지 확인됐는지
--   language         파서의 언어 어휘. NULL이면 언어 무관
--   role             REQUIRED      같은 group_no 안에서 모두 만족해야 한다(AND)
--                    OPTIONAL      가산 신호. 없어도 규칙은 성립한다
--   fact_type        IMPORT | DEPENDENCY | ANNOTATION | CONFIG_KEY | API_CALL
--   fact_field       MODULE | FILE_PATH | LANGUAGE
--   match_operator   EQUALS | PREFIX | SUFFIX | CONTAINS
--
-- group_no는 대안을 가른다. 같은 번호끼리 AND, 다른 번호끼리 OR다. 그래서 Redis처럼
-- 클라이언트가 여럿인 기술은 group을 나눠 "Jedis만 써도 성립"을 표현한다.
--
-- 지금 Worker가 만들어 내는 fact는 IMPORT 하나뿐이다(AI/analysis/parse.py). DEPENDENCY는
-- 매니페스트 파싱, API_CALL은 호출부 추적이 붙어야 채워지므로 그 fact_type을 쓰는 규칙은
-- 아직 넣지 않았다. 없는 fact를 기다리는 규칙은 영원히 매칭되지 않는다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description, evaluation_scope, priority, status) VALUES
    ('spring-boot.l1.java-import', 'spring-boot', 'registry-20260908.1', 'L1', 'JAVA',
     'Spring Boot 패키지 import',
     'org.springframework.boot 패키지를 import하면 이 저장소가 Spring Boot 위에서 동작한다고 본다.',
     'REPOSITORY', 100, 'ACTIVE'),

    -- Actuator는 넣기만 해도 헬스·메트릭 엔드포인트가 열린다. 운영을 염두에 뒀다는
    -- 신호라 L3으로 둔다. L1 규칙과 별개로 함께 매칭된다.
    ('spring-boot.l3.actuator', 'spring-boot', 'registry-20260908.1', 'L3', 'JAVA',
     'Actuator로 운영 관측 노출',
     'org.springframework.boot.actuate를 쓰면 헬스·메트릭을 외부에 노출하도록 구성한 것이다.',
     'REPOSITORY', 300, 'ACTIVE'),

    ('apache-kafka.l1.import', 'apache-kafka', 'registry-20260908.1', 'L1', NULL,
     'Kafka 클라이언트 import',
     'Java의 org.apache.kafka/org.springframework.kafka, Python의 kafka, JS의 kafkajs 중 하나를 쓴다.',
     'REPOSITORY', 100, 'ACTIVE'),

    -- DLQ는 docs/be/README.md 8절이 L3 예시로 직접 든 항목이다. 실패한 메시지를 어디로
    -- 보낼지 정해 뒀다는 것은 실패를 겪어 봤다는 뜻이다.
    ('apache-kafka.l3.dead-letter', 'apache-kafka', 'registry-20260908.1', 'L3', 'JAVA',
     'Dead Letter 처리 구성',
     'DeadLetterPublishingRecoverer를 쓰면 소비 실패 메시지의 행선지를 정해 둔 것이다.',
     'REPOSITORY', 300, 'ACTIVE'),

    ('redis.l1.client-import', 'redis', 'registry-20260908.1', 'L1', NULL,
     'Redis 클라이언트 import',
     'Spring Data Redis, Jedis, Lettuce, redis-py, ioredis 중 하나를 쓴다.',
     'REPOSITORY', 100, 'ACTIVE');

-- ---------------------------------------------------------------------------
-- 6. 절(clause)
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule_clause
    (clause_id, rule_id, group_no, clause_key, role, fact_type, min_match_count, clause_order) VALUES
    (301, 'spring-boot.l1.java-import',   1, 'boot-package',   'REQUIRED', 'IMPORT', 1, 1),
    (311, 'spring-boot.l3.actuator',      1, 'actuate-package','REQUIRED', 'IMPORT', 1, 1),
    -- Kafka는 언어마다 import 이름이 달라 group을 나눈다. 하나만 맞아도 성립한다.
    (321, 'apache-kafka.l1.import',       1, 'java-client',    'REQUIRED', 'IMPORT', 1, 1),
    (322, 'apache-kafka.l1.import',       2, 'python-client',  'REQUIRED', 'IMPORT', 1, 1),
    (323, 'apache-kafka.l1.import',       3, 'node-client',    'REQUIRED', 'IMPORT', 1, 1),
    (331, 'apache-kafka.l3.dead-letter',  1, 'dlq-recoverer',  'REQUIRED', 'IMPORT', 1, 1),
    (341, 'redis.l1.client-import',       1, 'java-client',    'REQUIRED', 'IMPORT', 1, 1),
    (342, 'redis.l1.client-import',       2, 'python-client',  'REQUIRED', 'IMPORT', 1, 1),
    (343, 'redis.l1.client-import',       3, 'node-client',    'REQUIRED', 'IMPORT', 1, 1);

-- ---------------------------------------------------------------------------
-- 7. 술어(predicate)
--
-- segment_delimiter가 있으면 PREFIX가 그 구분자 경계에서만 맞는다. 없으면
-- org.springframework가 org.springframeworkfoo에도 걸린다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule_predicate
    (predicate_id, clause_id, fact_field, match_operator, segment_delimiter, predicate_order) VALUES
    (401, 301, 'MODULE', 'PREFIX', '.',  1),
    (411, 311, 'MODULE', 'PREFIX', '.',  1),
    (421, 321, 'MODULE', 'PREFIX', '.',  1),
    (422, 322, 'MODULE', 'PREFIX', '.',  1),
    (423, 323, 'MODULE', 'EQUALS', NULL, 1),
    (431, 331, 'MODULE', 'PREFIX', '.',  1),
    (441, 341, 'MODULE', 'PREFIX', '.',  1),
    (442, 342, 'MODULE', 'PREFIX', '.',  1),
    (443, 343, 'MODULE', 'EQUALS', NULL, 1);

-- ---------------------------------------------------------------------------
-- 8. 기대값
--
-- 한 술어에 값이 여럿이면 OR다. value_order는 표시·재현 순서일 뿐 우선순위가 아니다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule_predicate_value
    (predicate_value_id, value_order, predicate_id, tech_id, registry_version, expected_value) VALUES
    (501, 1, 401, 'spring-boot',  'registry-20260908.1', 'org.springframework.boot'),
    (511, 1, 411, 'spring-boot',  'registry-20260908.1', 'org.springframework.boot.actuate'),
    (521, 1, 421, 'apache-kafka', 'registry-20260908.1', 'org.apache.kafka'),
    (522, 2, 421, 'apache-kafka', 'registry-20260908.1', 'org.springframework.kafka'),
    (531, 1, 422, 'apache-kafka', 'registry-20260908.1', 'kafka'),
    (541, 1, 423, 'apache-kafka', 'registry-20260908.1', 'kafkajs'),
    (551, 1, 431, 'apache-kafka', 'registry-20260908.1',
                  'org.springframework.kafka.listener.DeadLetterPublishingRecoverer'),
    (561, 1, 441, 'redis', 'registry-20260908.1', 'org.springframework.data.redis'),
    (562, 2, 441, 'redis', 'registry-20260908.1', 'redis.clients.jedis'),
    (563, 3, 441, 'redis', 'registry-20260908.1', 'io.lettuce.core'),
    (571, 1, 442, 'redis', 'registry-20260908.1', 'redis'),
    (581, 1, 443, 'redis', 'registry-20260908.1', 'ioredis');
