-- S15P21E102-121. Registry registry-20260910.1 발행.
--
-- 두 가지를 한 번에 한다.
--
-- 1. PACKAGE 매핑이 실제로 맞게 고친다. registry-20260908.1은 기술마다 PACKAGE 매핑이
--    하나뿐이었고 전부 EXACT였다. spring-boot는
--    'org.springframework.boot:spring-boot-starter-webmvc' 한 줄이었다.
--
--    spring-petclinic으로 재보면 MAVEN 의존성 31개 중 spring-boot로 해석되는
--    것이 EXACT로는 1개, PREFIX로는 14개다. L0 판정 자체는 1개로도 서지만
--    Evidence는 build.gradle 한 줄뿐이고, webmvc를 쓰지 않는 저장소는 0개가
--    된다. artifact마다 행을 하나씩 두는 것은 유지될 수 없다 — starter는
--    수십 개이고 계속 늘어난다.
--
-- 2. 기술을 3개에서 29개로 늘린다. 3개로는 어떤 저장소도 제대로 판정할 수 없다.
--
-- V5의 수명 주기를 처음으로 실제로 쓴다. DRAFT로 넣고, 내용이 다 들어간 뒤
-- 이전 버전을 RETIRED로 내리고 이것을 CURRENT로 올린다. registry-20260908.1의 행은
-- 지우지 않는다 — 그 버전으로 판정한 분석을 나중에 되짚을 수 있어야 한다.
--
-- ---------------------------------------------------------------------------
-- PREFIX가 생태계마다 다른 뜻인 이유
--
-- 좌표 구조가 다르다. Maven과 NuGet은 계층적이라 PREFIX가 자연스럽지만, npm과
-- PyPI의 이름은 평평하다. 'react'가 '-' 경계로 매칭하면 react-dom, react-router를
-- 전부 삼킨다. 'kafka'는 kafka-python을, 'python'은 python-dateutil을 삼킨다.
--
--   MAVEN   group:artifact   경계 '.' ':' '-'   PREFIX 사용
--   NUGET   dotted id        경계 '.'           PREFIX 사용
--   NPM     스코프만 계층     경계 '/'           스코프에만 PREFIX
--   PYPI    평평             (없음)             EXACT 만
--
-- 그래서 아래 PyPI·npm 행은 전부 EXACT이고, 이름이 다른 배포는 각각 적었다.
-- 경계 규칙 자체는 registry.normalization.package_has_prefix가 구현하고,
-- AI/tests/test_registry_package_prefix.py가 평평한 생태계의 PREFIX를 거절하는
-- 것까지 확인한다.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. 새 버전을 DRAFT로 연다
-- ---------------------------------------------------------------------------
INSERT INTO technology_registry (registry_version, schema_version, status, published_at)
VALUES ('registry-20260910.1', 'technology-registry/v1', 'DRAFT', NULL);

-- ---------------------------------------------------------------------------
-- 2. 기술
-- ---------------------------------------------------------------------------
INSERT INTO technology (tech_id, registry_version, display_name, status) VALUES
    ('spring-boot', 'registry-20260910.1', 'Spring Boot', 'ACTIVE'),
    ('spring-data-jpa', 'registry-20260910.1', 'Spring Data JPA', 'ACTIVE'),
    ('spring-security', 'registry-20260910.1', 'Spring Security', 'ACTIVE'),
    ('hibernate', 'registry-20260910.1', 'Hibernate ORM', 'ACTIVE'),
    ('lombok', 'registry-20260910.1', 'Project Lombok', 'ACTIVE'),
    ('junit', 'registry-20260910.1', 'JUnit', 'ACTIVE'),
    ('mockito', 'registry-20260910.1', 'Mockito', 'ACTIVE'),
    ('apache-kafka', 'registry-20260910.1', 'Apache Kafka', 'ACTIVE'),
    ('redis', 'registry-20260910.1', 'Redis', 'ACTIVE'),
    ('postgresql', 'registry-20260910.1', 'PostgreSQL', 'ACTIVE'),
    ('mysql', 'registry-20260910.1', 'MySQL', 'ACTIVE'),
    ('mongodb', 'registry-20260910.1', 'MongoDB', 'ACTIVE'),
    ('elasticsearch', 'registry-20260910.1', 'Elasticsearch', 'ACTIVE'),
    ('fastapi', 'registry-20260910.1', 'FastAPI', 'ACTIVE'),
    ('django', 'registry-20260910.1', 'Django', 'ACTIVE'),
    ('flask', 'registry-20260910.1', 'Flask', 'ACTIVE'),
    ('sqlalchemy', 'registry-20260910.1', 'SQLAlchemy', 'ACTIVE'),
    ('pydantic', 'registry-20260910.1', 'Pydantic', 'ACTIVE'),
    ('pandas', 'registry-20260910.1', 'pandas', 'ACTIVE'),
    ('numpy', 'registry-20260910.1', 'NumPy', 'ACTIVE'),
    ('pytorch', 'registry-20260910.1', 'PyTorch', 'ACTIVE'),
    ('scikit-learn', 'registry-20260910.1', 'scikit-learn', 'ACTIVE'),
    ('react', 'registry-20260910.1', 'React', 'ACTIVE'),
    ('vuejs', 'registry-20260910.1', 'Vue.js', 'ACTIVE'),
    ('nextjs', 'registry-20260910.1', 'Next.js', 'ACTIVE'),
    ('tailwindcss', 'registry-20260910.1', 'Tailwind CSS', 'ACTIVE'),
    ('axios', 'registry-20260910.1', 'Axios', 'ACTIVE'),
    ('vite', 'registry-20260910.1', 'Vite', 'ACTIVE'),
    ('testcontainers', 'registry-20260910.1', 'Testcontainers', 'ACTIVE');

-- ---------------------------------------------------------------------------
-- 3. 직무 도메인
-- ---------------------------------------------------------------------------
INSERT INTO technology_category (job_domain, registry_version, tech_id) VALUES
    ('BACKEND', 'registry-20260910.1', 'spring-boot'),
    ('BACKEND', 'registry-20260910.1', 'spring-data-jpa'),
    ('BACKEND', 'registry-20260910.1', 'spring-security'),
    ('BACKEND', 'registry-20260910.1', 'hibernate'),
    ('BACKEND', 'registry-20260910.1', 'lombok'),
    ('BACKEND', 'registry-20260910.1', 'junit'),
    ('BACKEND', 'registry-20260910.1', 'mockito'),
    ('BACKEND', 'registry-20260910.1', 'apache-kafka'),
    ('AI_DATA', 'registry-20260910.1', 'apache-kafka'),
    ('INFRASTRUCTURE', 'registry-20260910.1', 'apache-kafka'),
    ('BACKEND', 'registry-20260910.1', 'redis'),
    ('INFRASTRUCTURE', 'registry-20260910.1', 'redis'),
    ('BACKEND', 'registry-20260910.1', 'postgresql'),
    ('AI_DATA', 'registry-20260910.1', 'postgresql'),
    ('INFRASTRUCTURE', 'registry-20260910.1', 'postgresql'),
    ('BACKEND', 'registry-20260910.1', 'mysql'),
    ('AI_DATA', 'registry-20260910.1', 'mysql'),
    ('BACKEND', 'registry-20260910.1', 'mongodb'),
    ('AI_DATA', 'registry-20260910.1', 'mongodb'),
    ('BACKEND', 'registry-20260910.1', 'elasticsearch'),
    ('AI_DATA', 'registry-20260910.1', 'elasticsearch'),
    ('INFRASTRUCTURE', 'registry-20260910.1', 'elasticsearch'),
    ('BACKEND', 'registry-20260910.1', 'fastapi'),
    ('AI_DATA', 'registry-20260910.1', 'fastapi'),
    ('BACKEND', 'registry-20260910.1', 'django'),
    ('BACKEND', 'registry-20260910.1', 'flask'),
    ('BACKEND', 'registry-20260910.1', 'sqlalchemy'),
    ('AI_DATA', 'registry-20260910.1', 'sqlalchemy'),
    ('BACKEND', 'registry-20260910.1', 'pydantic'),
    ('AI_DATA', 'registry-20260910.1', 'pydantic'),
    ('AI_DATA', 'registry-20260910.1', 'pandas'),
    ('AI_DATA', 'registry-20260910.1', 'numpy'),
    ('AI_DATA', 'registry-20260910.1', 'pytorch'),
    ('AI_DATA', 'registry-20260910.1', 'scikit-learn'),
    ('FRONTEND', 'registry-20260910.1', 'react'),
    ('FRONTEND', 'registry-20260910.1', 'vuejs'),
    ('FRONTEND', 'registry-20260910.1', 'nextjs'),
    ('BACKEND', 'registry-20260910.1', 'nextjs'),
    ('FRONTEND', 'registry-20260910.1', 'tailwindcss'),
    ('FRONTEND', 'registry-20260910.1', 'axios'),
    ('BACKEND', 'registry-20260910.1', 'axios'),
    ('FRONTEND', 'registry-20260910.1', 'vite'),
    ('BACKEND', 'registry-20260910.1', 'testcontainers'),
    ('INFRASTRUCTURE', 'registry-20260910.1', 'testcontainers');

-- ---------------------------------------------------------------------------
-- 4. 매핑
--
-- IMPORT_PATH는 파싱이 뽑은 모듈 경로에, PACKAGE는 매니페스트가 뽑은 좌표에
-- 대조된다. 한 fact가 여러 기술로 해석될 수 있고, 그것은 대개 사실이다 —
-- spring-boot-starter-data-jpa는 Spring Boot를 쓴다는 증거이자 Spring Data JPA를
-- 쓴다는 증거다. 그래서 우선순위를 두지 않는다.
-- ---------------------------------------------------------------------------
INSERT INTO technology_mapping
    (registry_version, tech_id, mapping_type, ecosystem, value, match_mode, status) VALUES
    -- spring-boot. starter는 수십 개다. EXACT 한 줄(webmvc)로는 petclinic의 14개 중 1개만 잡혔다.
    ('registry-20260910.1', 'spring-boot', 'IMPORT_PATH', 'JAVA', 'org.springframework.boot', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'spring-boot', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'spring-boot', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot', 'PREFIX', 'ACTIVE'),
    -- spring-data-jpa. spring-boot의 PREFIX에도 걸린다. 둘 다 참이므로 우선순위를 두지 않는다.
    ('registry-20260910.1', 'spring-data-jpa', 'IMPORT_PATH', 'JAVA', 'org.springframework.data.jpa', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'spring-data-jpa', 'IMPORT_PATH', 'JAVA', 'org.springframework.data.repository', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'spring-data-jpa', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-data-jpa', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'spring-data-jpa', 'PACKAGE', 'MAVEN', 'org.springframework.data:spring-data-jpa', 'EXACT', 'ACTIVE'),
    -- spring-security
    ('registry-20260910.1', 'spring-security', 'IMPORT_PATH', 'JAVA', 'org.springframework.security', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'spring-security', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-security', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'spring-security', 'PACKAGE', 'MAVEN', 'org.springframework.security:spring-security', 'PREFIX', 'ACTIVE'),
    -- hibernate. jakarta.persistence는 넣지 않는다. JPA 명세라 구현이 Hibernate라는 증거가 아니다.
    ('registry-20260910.1', 'hibernate', 'IMPORT_PATH', 'JAVA', 'org.hibernate', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'hibernate', 'PACKAGE', 'MAVEN', 'org.hibernate.orm:hibernate', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'hibernate', 'PACKAGE', 'MAVEN', 'org.hibernate:hibernate-core', 'EXACT', 'ACTIVE'),
    -- lombok
    ('registry-20260910.1', 'lombok', 'IMPORT_PATH', 'JAVA', 'lombok', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'lombok', 'PACKAGE', 'MAVEN', 'org.projectlombok:lombok', 'EXACT', 'ACTIVE'),
    -- junit
    ('registry-20260910.1', 'junit', 'IMPORT_PATH', 'JAVA', 'org.junit', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'junit', 'PACKAGE', 'MAVEN', 'org.junit.jupiter:junit-jupiter', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'junit', 'PACKAGE', 'MAVEN', 'org.junit.platform:junit-platform', 'PREFIX', 'ACTIVE'),
    -- mockito
    ('registry-20260910.1', 'mockito', 'IMPORT_PATH', 'JAVA', 'org.mockito', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mockito', 'PACKAGE', 'MAVEN', 'org.mockito:mockito', 'PREFIX', 'ACTIVE'),
    -- apache-kafka. spring-kafka는 Kafka를 쓴다는 신호이므로 같은 tech_id로 모은다.
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'JAVA', 'org.apache.kafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'JAVA', 'org.springframework.kafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'PYTHON', 'kafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'PYTHON', 'aiokafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'PYTHON', 'confluent_kafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'IMPORT_PATH', 'JAVASCRIPT', 'kafkajs', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'MAVEN', 'org.apache.kafka:kafka', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'MAVEN', 'org.springframework.kafka:spring-kafka', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-kafka', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'PYPI', 'kafka-python', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'PYPI', 'aiokafka', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'PYPI', 'confluent-kafka', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'apache-kafka', 'PACKAGE', 'NPM', 'kafkajs', 'EXACT', 'ACTIVE'),
    -- redis. 클라이언트 라이브러리가 여럿이라 각각 매핑한다.
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'JAVA', 'org.springframework.data.redis', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'JAVA', 'redis.clients.jedis', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'JAVA', 'io.lettuce.core', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'PYTHON', 'redis', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'JAVASCRIPT', 'ioredis', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'IMPORT_PATH', 'JAVASCRIPT', 'redis', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-data-redis', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'MAVEN', 'redis.clients:jedis', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'MAVEN', 'io.lettuce:lettuce-core', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'PYPI', 'redis', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'NPM', 'ioredis', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'redis', 'PACKAGE', 'NPM', 'redis', 'EXACT', 'ACTIVE'),
    -- postgresql. psycopg2는 psycopg의 PREFIX에 걸리지 않는다. '.' 경계 뒤가 '2'라서 별도 행이 필요하다.
    ('registry-20260910.1', 'postgresql', 'IMPORT_PATH', 'JAVA', 'org.postgresql', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'IMPORT_PATH', 'PYTHON', 'psycopg', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'IMPORT_PATH', 'PYTHON', 'psycopg2', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'PACKAGE', 'MAVEN', 'org.postgresql:postgresql', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'PACKAGE', 'PYPI', 'psycopg', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'PACKAGE', 'PYPI', 'psycopg2', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'PACKAGE', 'PYPI', 'psycopg2-binary', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'postgresql', 'PACKAGE', 'NPM', 'pg', 'EXACT', 'ACTIVE'),
    -- mysql
    ('registry-20260910.1', 'mysql', 'IMPORT_PATH', 'JAVA', 'com.mysql', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mysql', 'PACKAGE', 'MAVEN', 'com.mysql:mysql-connector-j', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mysql', 'PACKAGE', 'MAVEN', 'mysql:mysql-connector-java', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mysql', 'PACKAGE', 'PYPI', 'pymysql', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mysql', 'PACKAGE', 'PYPI', 'mysqlclient', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mysql', 'PACKAGE', 'NPM', 'mysql2', 'EXACT', 'ACTIVE'),
    -- mongodb
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'JAVA', 'com.mongodb', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'JAVA', 'org.springframework.data.mongodb', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'PYTHON', 'pymongo', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'PYTHON', 'motor', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'JAVASCRIPT', 'mongodb', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'IMPORT_PATH', 'JAVASCRIPT', 'mongoose', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-data-mongodb', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'PACKAGE', 'MAVEN', 'org.mongodb:mongodb-driver', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'PACKAGE', 'PYPI', 'pymongo', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'PACKAGE', 'NPM', 'mongodb', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'mongodb', 'PACKAGE', 'NPM', 'mongoose', 'EXACT', 'ACTIVE'),
    -- elasticsearch
    ('registry-20260910.1', 'elasticsearch', 'IMPORT_PATH', 'JAVA', 'co.elastic.clients', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'IMPORT_PATH', 'JAVA', 'org.elasticsearch', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'IMPORT_PATH', 'PYTHON', 'elasticsearch', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'PACKAGE', 'MAVEN', 'co.elastic.clients:elasticsearch-java', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'PACKAGE', 'MAVEN', 'org.springframework.boot:spring-boot-starter-data-elasticsearch', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'PACKAGE', 'PYPI', 'elasticsearch', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'elasticsearch', 'PACKAGE', 'NPM', '@elastic/elasticsearch', 'EXACT', 'ACTIVE'),
    -- fastapi
    ('registry-20260910.1', 'fastapi', 'IMPORT_PATH', 'PYTHON', 'fastapi', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'fastapi', 'PACKAGE', 'PYPI', 'fastapi', 'EXACT', 'ACTIVE'),
    -- django
    ('registry-20260910.1', 'django', 'IMPORT_PATH', 'PYTHON', 'django', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'django', 'IMPORT_PATH', 'PYTHON', 'rest_framework', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'django', 'PACKAGE', 'PYPI', 'django', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'django', 'PACKAGE', 'PYPI', 'djangorestframework', 'EXACT', 'ACTIVE'),
    -- flask
    ('registry-20260910.1', 'flask', 'IMPORT_PATH', 'PYTHON', 'flask', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'flask', 'PACKAGE', 'PYPI', 'flask', 'EXACT', 'ACTIVE'),
    -- sqlalchemy
    ('registry-20260910.1', 'sqlalchemy', 'IMPORT_PATH', 'PYTHON', 'sqlalchemy', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'sqlalchemy', 'PACKAGE', 'PYPI', 'sqlalchemy', 'EXACT', 'ACTIVE'),
    -- pydantic
    ('registry-20260910.1', 'pydantic', 'IMPORT_PATH', 'PYTHON', 'pydantic', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'pydantic', 'PACKAGE', 'PYPI', 'pydantic', 'EXACT', 'ACTIVE'),
    -- pandas
    ('registry-20260910.1', 'pandas', 'IMPORT_PATH', 'PYTHON', 'pandas', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'pandas', 'PACKAGE', 'PYPI', 'pandas', 'EXACT', 'ACTIVE'),
    -- numpy
    ('registry-20260910.1', 'numpy', 'IMPORT_PATH', 'PYTHON', 'numpy', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'numpy', 'PACKAGE', 'PYPI', 'numpy', 'EXACT', 'ACTIVE'),
    -- pytorch. import 이름은 torch, 배포 이름도 torch다. PyPI 이름과 import 이름이 다른 경우가 흔해 둘 다 적는다.
    ('registry-20260910.1', 'pytorch', 'IMPORT_PATH', 'PYTHON', 'torch', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'pytorch', 'PACKAGE', 'PYPI', 'torch', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'pytorch', 'PACKAGE', 'PYPI', 'torchvision', 'EXACT', 'ACTIVE'),
    -- scikit-learn. import는 sklearn, 배포 이름은 scikit-learn이다.
    ('registry-20260910.1', 'scikit-learn', 'IMPORT_PATH', 'PYTHON', 'sklearn', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'scikit-learn', 'PACKAGE', 'PYPI', 'scikit-learn', 'EXACT', 'ACTIVE'),
    -- react. JS의 PREFIX 경계는 '/'다. react가 react-dom을 삼키지 않으므로 별도 행이 필요하다.
    ('registry-20260910.1', 'react', 'IMPORT_PATH', 'JAVASCRIPT', 'react', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'react', 'IMPORT_PATH', 'JAVASCRIPT', 'react-dom', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'react', 'PACKAGE', 'NPM', 'react', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'react', 'PACKAGE', 'NPM', 'react-dom', 'EXACT', 'ACTIVE'),
    -- vuejs
    ('registry-20260910.1', 'vuejs', 'IMPORT_PATH', 'JAVASCRIPT', 'vue', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'vuejs', 'PACKAGE', 'NPM', 'vue', 'EXACT', 'ACTIVE'),
    -- nextjs
    ('registry-20260910.1', 'nextjs', 'IMPORT_PATH', 'JAVASCRIPT', 'next', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'nextjs', 'PACKAGE', 'NPM', 'next', 'EXACT', 'ACTIVE'),
    -- tailwindcss
    ('registry-20260910.1', 'tailwindcss', 'IMPORT_PATH', 'JAVASCRIPT', 'tailwindcss', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'tailwindcss', 'PACKAGE', 'NPM', 'tailwindcss', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'tailwindcss', 'PACKAGE', 'NPM', '@tailwindcss/vite', 'EXACT', 'ACTIVE'),
    -- axios
    ('registry-20260910.1', 'axios', 'IMPORT_PATH', 'JAVASCRIPT', 'axios', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'axios', 'PACKAGE', 'NPM', 'axios', 'EXACT', 'ACTIVE'),
    -- vite
    ('registry-20260910.1', 'vite', 'IMPORT_PATH', 'JAVASCRIPT', 'vite', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'vite', 'PACKAGE', 'NPM', 'vite', 'EXACT', 'ACTIVE'),
    ('registry-20260910.1', 'vite', 'PACKAGE', 'NPM', '@vitejs/plugin-react', 'EXACT', 'ACTIVE'),
    -- testcontainers
    ('registry-20260910.1', 'testcontainers', 'IMPORT_PATH', 'JAVA', 'org.testcontainers', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'testcontainers', 'PACKAGE', 'MAVEN', 'org.testcontainers:testcontainers', 'PREFIX', 'ACTIVE'),
    ('registry-20260910.1', 'testcontainers', 'PACKAGE', 'PYPI', 'testcontainers', 'EXACT', 'ACTIVE');

-- ---------------------------------------------------------------------------
-- 5. L0·L1 규칙은 매핑에서 생성한다
--
-- V6이 정한 대로 규칙은 패턴을 다시 적지 않는다. 모든 기술의 L0·L1은 모양이
-- 같다 — "이 fact가 이 기술로 해석되면 성립". 손으로 58개를 적으면 오타가 나고,
-- 매핑을 추가할 때 규칙을 빠뜨리게 된다.
--
-- 매핑이 없는 종류의 규칙은 만들지 않는다. 없는 fact를 기다리는 규칙은 영원히
-- 매칭되지 않으면서 "이 기술을 안 쓴다"처럼 보인다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description,
     evaluation_scope, priority, status)
SELECT DISTINCT
       m.tech_id || '.l0.dependency',
       m.tech_id,
       m.registry_version,
       'L0',
       NULL,
       t.display_name || ' 의존성 선언',
       t.display_name || '을(를) 매니페스트에 선언했다. 실제로 쓰는지는 L1 이상이 말한다.',
       'REPOSITORY',
       50,
       'ACTIVE'
FROM technology_mapping m
JOIN technology t ON t.tech_id = m.tech_id AND t.registry_version = m.registry_version
WHERE m.registry_version = 'registry-20260910.1' AND m.mapping_type = 'PACKAGE';

INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description,
     evaluation_scope, priority, status)
SELECT DISTINCT
       m.tech_id || '.l1.import',
       m.tech_id,
       m.registry_version,
       'L1',
       NULL,
       t.display_name || ' import',
       t.display_name || '(으)로 해석되는 import가 있다. 경로 목록은 technology_mapping이 갖는다.',
       'REPOSITORY',
       100,
       'ACTIVE'
FROM technology_mapping m
JOIN technology t ON t.tech_id = m.tech_id AND t.registry_version = m.registry_version
WHERE m.registry_version = 'registry-20260910.1' AND m.mapping_type = 'IMPORT_PATH';

-- 절: 규칙 하나에 하나. fact_type만 L0/L1을 가른다.
INSERT INTO evidence_rule_clause
    (rule_id, group_no, clause_key, role, fact_type, min_match_count, clause_order, registry_version)
SELECT r.rule_id, 1, 'resolved-tech', 'REQUIRED',
       CASE r.rule_type WHEN 'L0' THEN 'DEPENDENCY' ELSE 'IMPORT' END,
       1, 1, r.registry_version
FROM evidence_rule r
WHERE r.registry_version = 'registry-20260910.1' AND r.rule_type IN ('L0', 'L1');

INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT c.clause_id, 'TECH_ID', 'EXACT', NULL, 1
FROM evidence_rule_clause c
WHERE c.registry_version = 'registry-20260910.1';

INSERT INTO evidence_rule_predicate_value
    (value_order, predicate_id, tech_id, registry_version, expected_value)
SELECT 1, p.predicate_id, r.tech_id, r.registry_version, r.tech_id
FROM evidence_rule_predicate p
JOIN evidence_rule_clause c ON c.clause_id = p.clause_id
JOIN evidence_rule r ON r.rule_id = c.rule_id AND r.registry_version = c.registry_version
WHERE r.registry_version = 'registry-20260910.1' AND r.rule_type IN ('L0', 'L1');

-- ---------------------------------------------------------------------------
-- 6. L3 규칙은 손으로 쓴다
--
-- 이것들은 매핑보다 세밀하다. org.springframework.boot.actuate는 spring-boot로
-- 해석되는 import 중 특정 하위 경로이고, 그 구분은 매핑이 표현할 수 없다.
-- 규칙은 매핑이 못 하는 것만 표현한다.
-- ---------------------------------------------------------------------------
INSERT INTO evidence_rule
    (rule_id, tech_id, registry_version, rule_type, language, rule_name, description,
     evaluation_scope, priority, status) VALUES
    ('spring-boot.l3.actuator', 'spring-boot', 'registry-20260910.1', 'L3', 'JAVA',
     'Actuator로 운영 관측 노출',
     'org.springframework.boot.actuate를 쓰면 헬스·메트릭을 외부에 노출하도록 구성한 것이다.',
     'REPOSITORY', 300, 'ACTIVE'),
    ('apache-kafka.l3.dead-letter', 'apache-kafka', 'registry-20260910.1', 'L3', 'JAVA',
     'Dead Letter 처리 구성',
     'DeadLetterPublishingRecoverer를 쓰면 소비 실패 메시지의 행선지를 정해 둔 것이다.',
     'REPOSITORY', 300, 'ACTIVE');

INSERT INTO evidence_rule_clause
    (rule_id, group_no, clause_key, role, fact_type, min_match_count, clause_order, registry_version)
VALUES
    ('spring-boot.l3.actuator', 1, 'module-prefix', 'REQUIRED', 'IMPORT', 1, 1, 'registry-20260910.1'),
    ('apache-kafka.l3.dead-letter', 1, 'module-prefix', 'REQUIRED', 'IMPORT', 1, 1, 'registry-20260910.1');

-- segment_delimiter가 있어야 org.springframework.bootcamp가 걸리지 않는다.
INSERT INTO evidence_rule_predicate
    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
SELECT c.clause_id, 'MODULE', 'PREFIX', '.', 1
FROM evidence_rule_clause c
WHERE c.registry_version = 'registry-20260910.1' AND c.clause_key = 'module-prefix';

INSERT INTO evidence_rule_predicate_value
    (value_order, predicate_id, tech_id, registry_version, expected_value)
SELECT 1, p.predicate_id, r.tech_id, r.registry_version,
       CASE r.rule_id
           WHEN 'spring-boot.l3.actuator' THEN 'org.springframework.boot.actuate'
           WHEN 'apache-kafka.l3.dead-letter' THEN 'org.springframework.kafka.listener.DeadLetterPublishingRecoverer'
       END
FROM evidence_rule_predicate p
JOIN evidence_rule_clause c ON c.clause_id = p.clause_id
JOIN evidence_rule r ON r.rule_id = c.rule_id AND r.registry_version = c.registry_version
WHERE r.registry_version = 'registry-20260910.1' AND r.rule_type = 'L3';

-- ---------------------------------------------------------------------------
-- 7. 발행
--
-- CURRENT는 부분 유니크 인덱스가 하나로 강제하므로 내리는 것이 먼저다.
-- 이전 버전의 내용은 그대로 남는다.
-- ---------------------------------------------------------------------------
UPDATE technology_registry
SET status = 'RETIRED'
WHERE registry_version = 'registry-20260908.1';

UPDATE technology_registry
SET status = 'CURRENT', published_at = now()
WHERE registry_version = 'registry-20260910.1';

-- 발행했는데 내용이 비어 있으면 조용히 "아무 기술도 안 쓰는 저장소"만 나온다.
DO $$
DECLARE
    technologies integer;
    rules integer;
BEGIN
    SELECT count(*) INTO technologies FROM technology WHERE registry_version = 'registry-20260910.1';
    SELECT count(*) INTO rules FROM evidence_rule WHERE registry_version = 'registry-20260910.1';
    IF technologies < 29 OR rules < 29 THEN
        RAISE EXCEPTION '발행한 버전의 내용이 비었다: 기술 %, 규칙 %', technologies, rules;
    END IF;
END $$;
