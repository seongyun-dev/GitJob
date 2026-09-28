package com.example.git_job.db;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.util.Map;
import org.hibernate.cfg.AvailableSettings;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.hibernate.SpringBeanContainer;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor.CipherAlgorithm;
import org.springframework.security.crypto.encrypt.BytesEncryptor;
import org.springframework.security.crypto.keygen.KeyGenerators;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * 모든 배포 환경이 {@code JPA_DDL_AUTO=validate}로 뜬다. 그래서 엔티티 매핑이
 * 마이그레이션과 한 군데라도 어긋나면 애플리케이션이 아예 기동하지 않는다.
 * 그 실패를 배포가 아니라 여기에서 먼저 만나기 위한 테스트다.
 *
 * <p>H2로는 대신할 수 없다. CHAR와 VARCHAR, TIMESTAMPTZ처럼 validate가 실제로
 * 비교하는 타입이 PostgreSQL과 다르게 보고되기 때문이다. 그래서 Docker가 필요하며,
 * Docker가 있으면 자동으로 돌고 없으면 건너뛴다.
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class SchemaValidationTest {

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private LocalContainerEntityManagerFactoryBean entityManagers;

    @Test
    @DisplayName("마이그레이션만 적용한 DB에서 모든 엔티티가 validate를 통과한다")
    void everyEntityMatchesTheDeploymentSchema() {
        postgres = new PostgreSQLContainer("postgres:16.4-alpine");
        postgres.start();

        var config = new HikariConfig();
        config.setJdbcUrl(postgres.getJdbcUrl());
        config.setUsername(postgres.getUsername());
        config.setPassword(postgres.getPassword());
        config.setMaximumPoolSize(2);
        dataSource = new HikariDataSource(config);

        // 운영과 같은 마이그레이션을 그대로 돌린다. 여기서 만들지 않는 테이블에
        // 엔티티가 걸려 있으면 실패해야 한다.
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration")
                .load().migrate();

        entityManagers = new LocalContainerEntityManagerFactoryBean();
        entityManagers.setDataSource(dataSource);
        // 애플리케이션과 같은 범위를 스캔한다. 새 엔티티가 생겨도 자동으로 포함된다.
        entityManagers.setPackagesToScan("com.example.git_job");
        entityManagers.setPersistenceUnitName("schema-validation");
        entityManagers.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
        entityManagers.setJpaPropertyMap(Map.of(
                "hibernate.hbm2ddl.auto", "validate",
                // 애플리케이션에서는 Spring Boot 가 이것을 끼워 준다. 없으면 Hibernate 가
                // AttributeConverter 를 기본 생성자로 만들려 하고, 의존성을 주입받는
                // 변환기는 만들어지지 못한다. 검증 대상이 아닌 이유로 실패하지 않도록
                // 운영과 같은 방식으로 빈을 공급한다.
                AvailableSettings.BEAN_CONTAINER, new SpringBeanContainer(beanFactory())));

        // validate 실패는 EntityManagerFactory 생성 시점에 예외로 나온다.
        assertDoesNotThrow(entityManagers::afterPropertiesSet);

        // 스캔이 조용히 0개를 잡고 통과하는 것을 막는다. 그러면 이 테스트는 아무것도 지키지 않는다.
        assertTrue(entityManagers.getObject().getMetamodel().getEntities().size() >= 2,
                "엔티티 스캔 범위가 잘못되어 검증 대상이 없다");
    }

    /**
     * 변환기가 필요로 하는 빈만 담은 최소 팩토리. 키는 아무 값이나 되며, 여기서
     * 확인하는 것은 복호화 결과가 아니라 매핑이 스키마와 맞는지다.
     */
    private static DefaultListableBeanFactory beanFactory() {
        var beans = new DefaultListableBeanFactory();
        beans.registerSingleton("bytesEncryptor", (BytesEncryptor) new AesBytesEncryptor(
                "0".repeat(64), "5c0744940b5c369b",
                KeyGenerators.secureRandom(16), CipherAlgorithm.GCM));
        return beans;
    }

    @Test
    @DisplayName("엔티티가 매핑한 테이블은 baseline 마이그레이션에 실제로 존재한다")
    void mappedTablesExistInBaselineMigration() {
        String baseline = assertDoesNotThrow(
                () -> new ClassPathResource("db/migration/V1__baseline_schema.sql")
                        .getContentAsString(java.nio.charset.StandardCharsets.UTF_8));
        assertTrue(baseline.contains("CREATE TABLE \"analysis_job\""), "analysis_job이 baseline에 없다");
        assertTrue(baseline.contains("CREATE TABLE \"user\""), "user가 baseline에 없다");
    }

    @AfterAll
    void stop() {
        if (entityManagers != null) {
            entityManagers.destroy();
        }
        if (dataSource != null) {
            dataSource.close();
        }
        if (postgres != null) {
            postgres.stop();
        }
    }
}
