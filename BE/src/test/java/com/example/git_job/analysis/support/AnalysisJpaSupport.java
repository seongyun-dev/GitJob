package com.example.git_job.analysis.support;

import com.example.git_job.analysis.repository.AnalysisJobRepository;
import jakarta.persistence.EntityManagerFactory;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import javax.sql.DataSource;
import org.springframework.data.jpa.repository.support.JpaRepositoryFactory;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.SharedEntityManagerCreator;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;

/**
 * Builds the JPA half of the analysis module for tests that assemble their own context.
 * Spring Boot does this through auto-configuration; these tests cannot, because the
 * DataSource only exists once a container has started.
 */
public final class AnalysisJpaSupport {
    private static final AtomicInteger UNIT_COUNTER = new AtomicInteger();

    private AnalysisJpaSupport() {
    }

    /**
     * @param ddlAuto "validate" checks the entity mapping against the SQL the deployment
     *                actually applies; "none" for schemas that only approximate it.
     */
    public static LocalContainerEntityManagerFactoryBean entityManagerFactory(
            DataSource dataSource, String ddlAuto) {
        var factory = new LocalContainerEntityManagerFactoryBean();
        factory.setDataSource(dataSource);
        factory.setPackagesToScan("com.example.git_job.analysis.domain");
        factory.setPersistenceUnitName("analysis-test-" + UNIT_COUNTER.incrementAndGet());
        factory.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
        factory.setJpaPropertyMap(Map.of("hibernate.hbm2ddl.auto", ddlAuto));
        factory.afterPropertiesSet();
        return factory;
    }

    /**
     * The shared EntityManager proxy delegates to whichever one the current transaction
     * holds, which is what the repository needs to join the caller's transaction.
     */
    public static AnalysisJobRepository repository(EntityManagerFactory entityManagerFactory) {
        return new JpaRepositoryFactory(
                SharedEntityManagerCreator.createSharedEntityManager(entityManagerFactory))
                .getRepository(AnalysisJobRepository.class);
    }
}
