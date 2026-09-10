-- S15P21E102-121. Registry registry-20260910.2 발행: L2 규칙을 넣는다.
--
-- L2 는 "활용 -- 핵심 API 호출". 지금까지 규칙이 0개였으므로 어떤 저장소를
-- 분석해도 L2 가 나오지 않았다. import 만 보면 "이 기술을 안다"까지밖에 말할 수
-- 없고, 이 제품이 팔려는 것은 "잘 쓴다"의 구분이다.
--
-- ---------------------------------------------------------------------------
-- API_CALL fact 로 무엇을 말할 수 있나
--
-- 파서는 타입을 모른다. kafkaTemplate.send(...) 가 Kafka 인지 알려면 그 변수의
-- 타입을 알아야 하고, 그건 컴파일러의 일이다. 파서가 줄 수 있는 것은 적힌
-- 그대로의 텍스트뿐이다 -- 메서드 이름과, 그것을 호출한 표현식.
--
--   CALL     호출 대상 전체.  SpringApplication.run,  pd.read_csv,  useState
--   METHOD   마지막 조각.     run,  read_csv,  useState
--
-- 이름 자체가 고유하면 그것으로 충분하다. useState, opsForValue, read_csv,
-- backward, assertThrows 는 각각 한 라이브러리의 것이다. send, get, run 은
-- 아니므로 그런 것은 CALL 로 한정하고(SpringApplication.run), 변수 이름을
-- 다르게 지은 코드를 놓치는 것을 받아들인다.
--
-- **신호를 놓치는 것은 감수할 수 있는 오류이고, 코드가 뒷받침하지 않는 레벨을
-- 주장하는 것은 아니다.** 그래서 아래 규칙은 기술 23개에만 있다 -- 나머지는
-- 충분히 고유한 신호를 찾지 못했다. postgresql·mysql 같은 드라이버는 애초에
-- 의미 있는 L2 가 없다.
--
-- ---------------------------------------------------------------------------
-- 왜 새 버전인가
--
-- V5 가 "한 registry_version 의 내용은 불변"으로 정했고, registry-20260910.1 로 판정된
-- analysis_evidence 가 이미 존재한다. V6 가 썼던 "판정된 것이 없다"는 예외는
-- 더 이상 성립하지 않는다. 그래서 내용을 복사해 새 버전을 만들고 거기에
-- 규칙을 더한다. 이전 버전의 행은 그대로 남아 과거 분석을 되짚게 한다.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. fact_field 어휘 확장
--
-- API_CALL fact 가 들고 오는 필드다. CHECK 를 늘리지 않으면 아래 INSERT 가
-- 거절된다 -- 그것이 이 제약을 둔 이유이기도 하다.
-- ---------------------------------------------------------------------------
ALTER TABLE "evidence_rule_predicate"
    DROP CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD";
ALTER TABLE "evidence_rule_predicate"
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD"
        CHECK ("fact_field" IN ('MODULE', 'TECH_ID', 'COORDINATE', 'ECOSYSTEM',
                                'SCOPE', 'LANGUAGE', 'FILE_PATH',
                                'CALL', 'METHOD', 'RECEIVER'));

-- ---------------------------------------------------------------------------
-- 2. 새 버전을 DRAFT 로 열고 이전 버전의 내용을 복사한다
--
-- 손으로 다시 적지 않는다. 복사가 아니라 재작성이면 두 버전의 차이가 의도한
-- 것인지 오타인지 구분할 수 없다.
-- ---------------------------------------------------------------------------
INSERT INTO technology_registry (registry_version, schema_version, status, published_at)
SELECT 'registry-20260910.2', schema_version, 'DRAFT', NULL
FROM technology_registry WHERE registry_version = 'registry-20260910.1';

INSERT INTO technology (tech_id, registry_version, display_name, status)
SELECT tech_id, 'registry-20260910.2', display_name, status
FROM technology WHERE registry_version = 'registry-20260910.1';

INSERT INTO technology_category (job_domain, registry_version, tech_id)
SELECT job_domain, 'registry-20260910.2', tech_id
FROM technology_category WHERE registry_version = 'registry-20260910.1';

INSERT INTO technology_mapping
    (registry_version, tech_id, mapping_type, ecosystem, value, match_mode, status)
SELECT 'registry-20260910.2', tech_id, mapping_type, ecosystem, value, match_mode, status
FROM technology_mapping WHERE registry_version = 'registry-20260910.1';

INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description,
     evaluation_scope, priority, status)
SELECT rule_id, tech_id, 'registry-20260910.2', rule_type, language, rule_name, description,
       evaluation_scope, priority, status
FROM evidence_rule WHERE registry_version = 'registry-20260910.1';

-- 절·술어·기대값은 id 가 IDENTITY 라 새로 발급된다. 부모-자식 관계는 자연키로
-- 다시 잇는다. INSERT ... RETURNING 의 반환 순서는 PostgreSQL 이 보장하지
-- 않으므로 순번 대조는 쓸 수 없다.
--
--   절   (rule_id, registry_version, group_no, clause_order)
--   술어 (clause_id, predicate_order)
--
-- 둘 다 실제 데이터에서 유일함을 확인했다.
INSERT INTO evidence_rule_clause
    (rule_id, group_no, clause_key, role, fact_type, min_match_count,
     clause_order, registry_version)
SELECT rule_id, group_no, clause_key, role, fact_type, min_match_count,
       clause_order, 'registry-20260910.2'
FROM evidence_rule_clause
WHERE registry_version = 'registry-20260910.1';

INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT new_clause.clause_id, p.fact_field, p.match_operator,
       p.segment_delimiter, p.predicate_order
FROM evidence_rule_predicate p
JOIN evidence_rule_clause old_clause ON old_clause.clause_id = p.clause_id
JOIN evidence_rule_clause new_clause
  ON new_clause.registry_version = 'registry-20260910.2'
 AND new_clause.rule_id = old_clause.rule_id
 AND new_clause.group_no = old_clause.group_no
 AND new_clause.clause_order = old_clause.clause_order
WHERE old_clause.registry_version = 'registry-20260910.1';

INSERT INTO evidence_rule_predicate_value
    (value_order, predicate_id, tech_id, registry_version, expected_value)
SELECT v.value_order, new_predicate.predicate_id, v.tech_id, 'registry-20260910.2', v.expected_value
FROM evidence_rule_predicate_value v
JOIN evidence_rule_predicate p ON p.predicate_id = v.predicate_id
JOIN evidence_rule_clause old_clause ON old_clause.clause_id = p.clause_id
JOIN evidence_rule_clause new_clause
  ON new_clause.registry_version = 'registry-20260910.2'
 AND new_clause.rule_id = old_clause.rule_id
 AND new_clause.group_no = old_clause.group_no
 AND new_clause.clause_order = old_clause.clause_order
JOIN evidence_rule_predicate new_predicate
  ON new_predicate.clause_id = new_clause.clause_id
 AND new_predicate.predicate_order = p.predicate_order
WHERE old_clause.registry_version = 'registry-20260910.1';

-- ---------------------------------------------------------------------------
-- 3. L2 규칙
--
-- 하나씩 손으로 쓴다. L0·L1 처럼 모양이 같지 않다 -- 기술마다 "실제로 쓴다"의
-- 신호가 다르고, 그 판단은 사람이 해야 한다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description,
     evaluation_scope, priority, status) VALUES
    ('spring-boot.l2.bootstrap', 'spring-boot', 'registry-20260910.2', 'L2', NULL,
     'Spring Boot 애플리케이션 부팅',
     'SpringApplication.run 을 직접 호출한다. 애플리케이션의 진입점을 스스로 구성했다는 뜻이다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('redis.l2.operations', 'redis', 'registry-20260910.2', 'L2', NULL,
     'Redis 자료구조 연산 호출',
     'opsForValue/opsForHash 계열은 Spring Data Redis 의 자료구조 접근자다. 설정만 한 것이 아니라 실제로 읽고 쓴다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('apache-kafka.l2.template-send', 'apache-kafka', 'registry-20260910.2', 'L2', NULL,
     'Kafka 프로듀서 전송',
     'kafkaTemplate.send 또는 producer.send 를 호출한다. 이름에 의존하므로 다르게 지은 변수는 놓친다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('spring-data-jpa.l2.query', 'spring-data-jpa', 'registry-20260910.2', 'L2', NULL,
     'JPA 쿼리 직접 작성',
     'createQuery/createNativeQuery 를 호출한다. 파생 쿼리 메서드만 쓰는 것보다 한 단계 깊다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('hibernate.l2.session', 'hibernate', 'registry-20260910.2', 'L2', NULL,
     'Hibernate 세션 직접 사용',
     'getCurrentSession/openSession 을 호출한다. JPA 추상화 아래의 Hibernate API 를 직접 쓴다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('junit.l2.structured-assertion', 'junit', 'registry-20260910.2', 'L2', NULL,
     'JUnit 5 구조적 단언',
     'assertThrows/assertAll/assertDoesNotThrow 는 JUnit 5 고유다. assertEquals 와 달리 다른 프레임워크와 겹치지 않는다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('mockito.l2.stubbing', 'mockito', 'registry-20260910.2', 'L2', NULL,
     'Mockito 스텁·검증',
     'verify/doReturn/doThrow 계열 호출. mock 객체를 만드는 데 그치지 않고 상호작용을 검증한다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('testcontainers.l2.lifecycle', 'testcontainers', 'registry-20260910.2', 'L2', NULL,
     '컨테이너 수명 주기 제어',
     'withReuse/getJdbcUrl/getMappedPort 를 호출한다. 컨테이너를 선언만 한 것이 아니라 테스트에서 다룬다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('mongodb.l2.aggregation', 'mongodb', 'registry-20260910.2', 'L2', NULL,
     'MongoDB 집계·벌크 연산',
     'aggregate/insertMany/findOneAndUpdate 는 단순 CRUD 를 넘어선 드라이버 API 다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('react.l2.hooks', 'react', 'registry-20260910.2', 'L2', NULL,
     'React 훅 사용',
     'useState/useEffect 계열 호출. 훅 이름은 React 고유라 수신자 없이도 명확하다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('vuejs.l2.composition-api', 'vuejs', 'registry-20260910.2', 'L2', NULL,
     'Vue Composition API 사용',
     'ref/reactive/computed/watch 호출. Options API 만 쓰는 것보다 한 단계 깊다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('nextjs.l2.routing', 'nextjs', 'registry-20260910.2', 'L2', NULL,
     'Next.js 라우팅·데이터 로딩',
     'useRouter/getServerSideProps/getStaticProps 를 쓴다. 프레임워크의 렌더링 모델을 직접 다룬다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('axios.l2.instance', 'axios', 'registry-20260910.2', 'L2', NULL,
     'Axios 인스턴스·인터셉터 구성',
     'axios.create 로 인스턴스를 만들거나 인터셉터를 붙인다. 단순 요청 호출보다 깊다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('fastapi.l2.dependency-injection', 'fastapi', 'registry-20260910.2', 'L2', NULL,
     'FastAPI 의존성 주입',
     'Depends 를 호출한다. 라우트만 붙이는 것이 아니라 프레임워크의 DI 를 쓴다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('django.l2.orm-shortcuts', 'django', 'registry-20260910.2', 'L2', NULL,
     'Django ORM·단축 함수',
     'get_object_or_404/select_related/prefetch_related 를 쓴다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('flask.l2.app-helpers', 'flask', 'registry-20260910.2', 'L2', NULL,
     'Flask 요청·응답 헬퍼',
     'url_for/jsonify/make_response 를 쓴다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('sqlalchemy.l2.engine', 'sqlalchemy', 'registry-20260910.2', 'L2', NULL,
     'SQLAlchemy 엔진·세션 구성',
     'create_engine/sessionmaker 를 호출한다. ORM 을 직접 배선한다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('pandas.l2.dataframe-ops', 'pandas', 'registry-20260910.2', 'L2', NULL,
     'pandas 입출력·변환',
     'read_csv/groupby/merge 계열 호출. import 만으로는 알 수 없는 실제 조작이다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('numpy.l2.array-ops', 'numpy', 'registry-20260910.2', 'L2', NULL,
     'NumPy 배열 생성·연산',
     'linspace/arange/reshape 계열. array 나 sum 처럼 다른 라이브러리와 겹치는 이름은 제외했다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('pytorch.l2.training-loop', 'pytorch', 'registry-20260910.2', 'L2', NULL,
     'PyTorch 학습 루프',
     'backward/zero_grad/no_grad 는 자동미분 루프를 직접 돌린다는 뜻이다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('scikit-learn.l2.model-fitting', 'scikit-learn', 'registry-20260910.2', 'L2', NULL,
     'scikit-learn 모델 학습',
     'fit_transform/train_test_split/cross_val_score 호출.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('elasticsearch.l2.search', 'elasticsearch', 'registry-20260910.2', 'L2', NULL,
     'Elasticsearch 검색·색인 호출',
     'search/index/bulk 를 클라이언트에서 직접 호출한다.',
     'REPOSITORY', 200, 'ACTIVE'),
    ('spring-security.l2.configuration', 'spring-security', 'registry-20260910.2', 'L2', NULL,
     'Spring Security 필터 체인 구성',
     'authorizeHttpRequests/securityFilterChain 등 설정 DSL 을 직접 작성한다.',
     'REPOSITORY', 200, 'ACTIVE');

-- 절이 둘이고 같은 group 이라 AND 다: 이 API 를 호출하고, 그 기술을 import 한다.
--
-- 호출 이름만으로는 부족하다. `backward` 는 영어 단어이고, `verify` 나 `run` 도
-- 어느 코드에나 있다. 실측으로 확인했다 -- CPython 표준 라이브러리의
-- turtle.py 가 `backward()` 를, statistics.py 가 `groupby()` 를 호출한다.
-- import 를 함께 요구하면 그 부류가 통째로 사라진다. import 없이 그 라이브러리의
-- API 를 호출하는 코드는 없기 때문이다.
INSERT INTO evidence_rule_clause
    (rule_id, group_no, clause_key, role, fact_type, min_match_count, clause_order, registry_version)
SELECT rule_id, 1, 'api-call', 'REQUIRED', 'API_CALL', 1, 1, registry_version
FROM evidence_rule
WHERE registry_version = 'registry-20260910.2' AND rule_type = 'L2';

INSERT INTO evidence_rule_clause
    (rule_id, group_no, clause_key, role, fact_type, min_match_count, clause_order, registry_version)
SELECT rule_id, 1, 'import-present', 'REQUIRED', 'IMPORT', 1, 2, registry_version
FROM evidence_rule
WHERE registry_version = 'registry-20260910.2' AND rule_type = 'L2';

INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT c.clause_id, 'TECH_ID', 'EXACT', NULL, 1
FROM evidence_rule_clause c
WHERE c.registry_version = 'registry-20260910.2' AND c.clause_key = 'import-present';

INSERT INTO evidence_rule_predicate_value
    (value_order, predicate_id, tech_id, registry_version, expected_value)
SELECT 1, p.predicate_id, r.tech_id, r.registry_version, r.tech_id
FROM evidence_rule r
JOIN evidence_rule_clause c
  ON c.rule_id = r.rule_id AND c.registry_version = r.registry_version
JOIN evidence_rule_predicate p ON p.clause_id = c.clause_id
WHERE r.registry_version = 'registry-20260910.2' AND c.clause_key = 'import-present';

INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT c.clause_id, 'CALL', 'EXACT', NULL, 1
FROM evidence_rule_clause c
WHERE c.registry_version = 'registry-20260910.2' AND c.clause_key = 'api-call'
  AND c.rule_id IN ('spring-boot.l2.bootstrap', 'apache-kafka.l2.template-send', 'axios.l2.instance');

INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT c.clause_id, 'METHOD', 'EXACT', NULL, 1
FROM evidence_rule_clause c
WHERE c.registry_version = 'registry-20260910.2' AND c.clause_key = 'api-call'
  AND c.rule_id IN ('redis.l2.operations', 'spring-data-jpa.l2.query', 'hibernate.l2.session', 'junit.l2.structured-assertion', 'mockito.l2.stubbing', 'testcontainers.l2.lifecycle', 'mongodb.l2.aggregation', 'react.l2.hooks', 'vuejs.l2.composition-api', 'nextjs.l2.routing', 'fastapi.l2.dependency-injection', 'django.l2.orm-shortcuts', 'flask.l2.app-helpers', 'sqlalchemy.l2.engine', 'pandas.l2.dataframe-ops', 'numpy.l2.array-ops', 'pytorch.l2.training-loop', 'scikit-learn.l2.model-fitting', 'elasticsearch.l2.search', 'spring-security.l2.configuration');

-- 기대값. 한 술어에 값이 여럿이면 OR 다.
INSERT INTO evidence_rule_predicate_value
    (value_order, predicate_id, tech_id, registry_version, expected_value)
SELECT expected.ord, p.predicate_id, r.tech_id, r.registry_version, expected.value
FROM evidence_rule r
JOIN evidence_rule_clause c
  ON c.rule_id = r.rule_id AND c.registry_version = r.registry_version
JOIN evidence_rule_predicate p ON p.clause_id = c.clause_id
JOIN (VALUES
    ('spring-boot.l2.bootstrap', 1, 'SpringApplication.run'),
    ('redis.l2.operations', 1, 'opsForValue'),
    ('redis.l2.operations', 2, 'opsForHash'),
    ('redis.l2.operations', 3, 'opsForList'),
    ('redis.l2.operations', 4, 'opsForSet'),
    ('redis.l2.operations', 5, 'opsForZSet'),
    ('apache-kafka.l2.template-send', 1, 'kafkaTemplate.send'),
    ('apache-kafka.l2.template-send', 2, 'producer.send'),
    ('apache-kafka.l2.template-send', 3, 'kafkaProducer.send'),
    ('spring-data-jpa.l2.query', 1, 'createQuery'),
    ('spring-data-jpa.l2.query', 2, 'createNativeQuery'),
    ('spring-data-jpa.l2.query', 3, 'createNamedQuery'),
    ('hibernate.l2.session', 1, 'getCurrentSession'),
    ('hibernate.l2.session', 2, 'openSession'),
    ('junit.l2.structured-assertion', 1, 'assertThrows'),
    ('junit.l2.structured-assertion', 2, 'assertAll'),
    ('junit.l2.structured-assertion', 3, 'assertDoesNotThrow'),
    ('junit.l2.structured-assertion', 4, 'assertTimeout'),
    ('mockito.l2.stubbing', 1, 'verify'),
    ('mockito.l2.stubbing', 2, 'doReturn'),
    ('mockito.l2.stubbing', 3, 'doThrow'),
    ('mockito.l2.stubbing', 4, 'doAnswer'),
    ('mockito.l2.stubbing', 5, 'thenAnswer'),
    ('mockito.l2.stubbing', 6, 'verifyNoMoreInteractions'),
    ('testcontainers.l2.lifecycle', 1, 'getJdbcUrl'),
    ('testcontainers.l2.lifecycle', 2, 'getMappedPort'),
    ('testcontainers.l2.lifecycle', 3, 'withReuse'),
    ('testcontainers.l2.lifecycle', 4, 'getBootstrapServers'),
    ('mongodb.l2.aggregation', 1, 'aggregate'),
    ('mongodb.l2.aggregation', 2, 'insertMany'),
    ('mongodb.l2.aggregation', 3, 'findOneAndUpdate'),
    ('mongodb.l2.aggregation', 4, 'bulkWrite'),
    ('react.l2.hooks', 1, 'useState'),
    ('react.l2.hooks', 2, 'useEffect'),
    ('react.l2.hooks', 3, 'useMemo'),
    ('react.l2.hooks', 4, 'useCallback'),
    ('react.l2.hooks', 5, 'useReducer'),
    ('react.l2.hooks', 6, 'useRef'),
    ('react.l2.hooks', 7, 'useContext'),
    ('vuejs.l2.composition-api', 1, 'reactive'),
    ('vuejs.l2.composition-api', 2, 'computed'),
    ('vuejs.l2.composition-api', 3, 'watchEffect'),
    ('vuejs.l2.composition-api', 4, 'defineProps'),
    ('vuejs.l2.composition-api', 5, 'defineEmits'),
    ('nextjs.l2.routing', 1, 'useRouter'),
    ('nextjs.l2.routing', 2, 'getServerSideProps'),
    ('nextjs.l2.routing', 3, 'getStaticProps'),
    ('nextjs.l2.routing', 4, 'getStaticPaths'),
    ('axios.l2.instance', 1, 'axios.create'),
    ('fastapi.l2.dependency-injection', 1, 'Depends'),
    ('django.l2.orm-shortcuts', 1, 'get_object_or_404'),
    ('django.l2.orm-shortcuts', 2, 'select_related'),
    ('django.l2.orm-shortcuts', 3, 'prefetch_related'),
    ('django.l2.orm-shortcuts', 4, 'get_list_or_404'),
    ('flask.l2.app-helpers', 1, 'url_for'),
    ('flask.l2.app-helpers', 2, 'jsonify'),
    ('flask.l2.app-helpers', 3, 'make_response'),
    ('sqlalchemy.l2.engine', 1, 'create_engine'),
    ('sqlalchemy.l2.engine', 2, 'sessionmaker'),
    ('sqlalchemy.l2.engine', 3, 'scoped_session'),
    ('pandas.l2.dataframe-ops', 1, 'read_csv'),
    ('pandas.l2.dataframe-ops', 2, 'read_parquet'),
    ('pandas.l2.dataframe-ops', 3, 'read_sql'),
    ('pandas.l2.dataframe-ops', 4, 'groupby'),
    ('pandas.l2.dataframe-ops', 5, 'pivot_table'),
    ('pandas.l2.dataframe-ops', 6, 'to_datetime'),
    ('numpy.l2.array-ops', 1, 'linspace'),
    ('numpy.l2.array-ops', 2, 'arange'),
    ('numpy.l2.array-ops', 3, 'meshgrid'),
    ('numpy.l2.array-ops', 4, 'einsum'),
    ('numpy.l2.array-ops', 5, 'argsort'),
    ('pytorch.l2.training-loop', 1, 'backward'),
    ('pytorch.l2.training-loop', 2, 'zero_grad'),
    ('pytorch.l2.training-loop', 3, 'no_grad'),
    ('pytorch.l2.training-loop', 4, 'state_dict'),
    ('pytorch.l2.training-loop', 5, 'load_state_dict'),
    ('scikit-learn.l2.model-fitting', 1, 'fit_transform'),
    ('scikit-learn.l2.model-fitting', 2, 'train_test_split'),
    ('scikit-learn.l2.model-fitting', 3, 'cross_val_score'),
    ('scikit-learn.l2.model-fitting', 4, 'GridSearchCV'),
    ('elasticsearch.l2.search', 1, 'bulk'),
    ('elasticsearch.l2.search', 2, 'msearch'),
    ('elasticsearch.l2.search', 3, 'reindex'),
    ('spring-security.l2.configuration', 1, 'authorizeHttpRequests'),
    ('spring-security.l2.configuration', 2, 'securityFilterChain'),
    ('spring-security.l2.configuration', 3, 'httpBasic'),
    ('spring-security.l2.configuration', 4, 'sessionManagement')
) AS expected(rule_id, ord, value) ON expected.rule_id = r.rule_id
-- clause_key 로 좁히지 않으면 같은 규칙의 import-present 술어에도 붙는다.
WHERE r.registry_version = 'registry-20260910.2' AND r.rule_type = 'L2'
  AND c.clause_key = 'api-call';

-- ---------------------------------------------------------------------------
-- 4. 발행
-- ---------------------------------------------------------------------------
UPDATE technology_registry SET status = 'RETIRED' WHERE registry_version = 'registry-20260910.1';
UPDATE technology_registry SET status = 'CURRENT', published_at = now()
WHERE registry_version = 'registry-20260910.2';

-- 복사가 온전한지 확인한다. 한 테이블이라도 빠지면 새 버전은 조용히 덜 판정한다.
DO $$
DECLARE
    old_counts record;
    new_counts record;
BEGIN
    SELECT
        (SELECT count(*) FROM technology WHERE registry_version = 'registry-20260910.1') AS techs,
        (SELECT count(*) FROM technology_mapping WHERE registry_version = 'registry-20260910.1') AS maps,
        (SELECT count(*) FROM evidence_rule WHERE registry_version = 'registry-20260910.1') AS rules,
        (SELECT count(*) FROM evidence_rule_clause WHERE registry_version = 'registry-20260910.1') AS clauses,
        (SELECT count(*) FROM evidence_rule_predicate_value WHERE registry_version = 'registry-20260910.1') AS vals
    INTO old_counts;
    SELECT
        (SELECT count(*) FROM technology WHERE registry_version = 'registry-20260910.2') AS techs,
        (SELECT count(*) FROM technology_mapping WHERE registry_version = 'registry-20260910.2') AS maps,
        (SELECT count(*) FROM evidence_rule WHERE registry_version = 'registry-20260910.2') AS rules,
        (SELECT count(*) FROM evidence_rule_clause WHERE registry_version = 'registry-20260910.2') AS clauses,
        (SELECT count(*) FROM evidence_rule_predicate_value WHERE registry_version = 'registry-20260910.2') AS vals
    INTO new_counts;

    IF new_counts.techs <> old_counts.techs
       OR new_counts.maps <> old_counts.maps THEN
        RAISE EXCEPTION '복사가 불완전하다: 기술 %/%, 매핑 %/%',
            new_counts.techs, old_counts.techs, new_counts.maps, old_counts.maps;
    END IF;
    IF new_counts.rules <> old_counts.rules + 23 THEN
        RAISE EXCEPTION '규칙 수가 맞지 않는다: % (기대 %)',
            new_counts.rules, old_counts.rules + 23;
    END IF;
    IF new_counts.clauses <> old_counts.clauses + 46 THEN
        RAISE EXCEPTION '절 수가 맞지 않는다: % (기대 %)',
            new_counts.clauses, old_counts.clauses + 46;
    END IF;
    IF new_counts.vals <> old_counts.vals + 110 THEN
        RAISE EXCEPTION '기대값 수가 맞지 않는다: % (기대 %)',
            new_counts.vals, old_counts.vals + 110;
    END IF;
END $$;
