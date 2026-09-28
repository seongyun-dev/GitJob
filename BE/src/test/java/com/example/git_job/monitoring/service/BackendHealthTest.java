package com.example.git_job.monitoring.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.sql.SQLException;
import javax.sql.DataSource;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.health.actuate.endpoint.CompositeHealthDescriptor;
import org.springframework.boot.health.actuate.endpoint.HealthDescriptor;
import org.springframework.boot.health.actuate.endpoint.HealthEndpoint;
import org.springframework.boot.health.autoconfigure.actuate.endpoint.HealthEndpointAutoConfiguration;
import org.springframework.boot.health.autoconfigure.application.DiskSpaceHealthContributorAutoConfiguration;
import org.springframework.boot.health.autoconfigure.contributor.HealthContributorAutoConfiguration;
import org.springframework.boot.health.autoconfigure.registry.HealthContributorRegistryAutoConfiguration;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.boot.health.contributor.Status;
import org.springframework.boot.jdbc.autoconfigure.health.DataSourceHealthContributorAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Backend 칩이 무엇을 근거로 켜지는지 고정한다 (S15P21E102-321).
 *
 * <p>여기서 증명하려는 것은 두 가지다. 하나, 이 값이 <strong>동어반복이 아니라는 것</strong> —
 * "응답했으니 살아 있다"가 아니라 DB·디스크 같은 실제 contributor의 상태가 합쳐진 값이라는
 * 것. 둘, 모른다는 말을 죽었다는 말로 바꾸지 않는다는 것.</p>
 *
 * <p>앞쪽은 실제 auto-configuration을 올려서 확인한다. Actuator가 이 프로젝트의 의존성
 * 구성에서 어떤 contributor를 실제로 등록하는지는 mock으로 알 수 없기 때문이다.</p>
 */
class BackendHealthTest {

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(
                    org.springframework.boot.actuate.autoconfigure.endpoint.EndpointAutoConfiguration.class,
                    HealthContributorRegistryAutoConfiguration.class,
                    HealthContributorAutoConfiguration.class,
                    DiskSpaceHealthContributorAutoConfiguration.class,
                    DataSourceHealthContributorAutoConfiguration.class,
                    HealthEndpointAutoConfiguration.class));

    /**
     * 프로젝트가 의존하는 구성에서 실제로 무엇이 등록되는지.
     *
     * <p>{@code db}가 없으면 이 칩은 "BE 프로세스가 떴다"만 말하는 동어반복이 된다.</p>
     */
    @Test
    @DisplayName("집계에 DB와 디스크 contributor가 실제로 들어 있다")
    void theAggregateActuallyContainsRealContributors() {
        runner.withUserConfiguration(BrokenDataSource.class).run(context -> {
            HealthDescriptor health = context.getBean(HealthEndpoint.class).health();

            assertThat(health).isInstanceOf(CompositeHealthDescriptor.class);
            assertThat(((CompositeHealthDescriptor) health).getComponents())
                    .containsKeys("db", "diskSpace");
        });
    }

    @Test
    @DisplayName("contributor가 모두 정상이면 UP이다")
    void aHealthyAggregateIsUp() {
        runner.run(context ->
                assertThat(backendHealth(context.getBean(HealthEndpoint.class)).upOrNull())
                        .isTrue());
    }

    /**
     * 프로세스는 떠 있는데 DB에 닿지 못하는 상태. 화면이 알고 싶은 것이 정확히 이것이다.
     */
    @Test
    @DisplayName("DB에 닿지 못하면 DOWN이다")
    void aBrokenDatabaseTurnsTheChipDown() {
        runner.withUserConfiguration(BrokenDataSource.class).run(context -> {
            HealthEndpoint endpoint = context.getBean(HealthEndpoint.class);

            assertThat(endpoint.health().getStatus()).isEqualTo(Status.DOWN);
            assertThat(backendHealth(endpoint).upOrNull()).isFalse();
        });
    }

    @Test
    @DisplayName("OUT_OF_SERVICE도 DOWN으로 옮긴다")
    void outOfServiceIsAFailure() {
        runner.withBean("suspended", HealthIndicator.class,
                        () -> () -> Health.status(Status.OUT_OF_SERVICE).build())
                .run(context -> assertThat(
                        backendHealth(context.getBean(HealthEndpoint.class)).upOrNull())
                        .isFalse());
    }

    /*
      Actuator가 스스로 "모르겠다"고 한 것을 "죽었다"로 바꾸지 않는다. 화면에서 그 둘은
      부르는 사람이 다르다.
    */
    @Test
    @DisplayName("Actuator가 UNKNOWN이라고 하면 판정하지 않는다")
    void anUnknownStatusStaysUnknown() {
        // 기본 contributor를 끄고 UNKNOWN 하나만 남겨 집계를 UNKNOWN으로 만든다.
        runner.withPropertyValues("management.health.defaults.enabled=false")
                .withBean("unsure", HealthIndicator.class,
                        () -> () -> Health.status(Status.UNKNOWN).build())
                .run(context -> assertThat(
                        backendHealth(context.getBean(HealthEndpoint.class)).upOrNull())
                        .isNull());
    }

    @Test
    @DisplayName("집계가 터지면 죽은 것이 아니라 재지 못한 것이다")
    void aFailingAggregateIsNotAFailingService() {
        HealthEndpoint endpoint = mock(HealthEndpoint.class);
        when(endpoint.health()).thenThrow(new IllegalStateException("registry 손상"));

        assertThat(new BackendHealth(provider(endpoint)).upOrNull()).isNull();
    }

    /** Actuator가 없는 구성(테스트 슬라이스 등)에서는 판정하지 않는다. */
    @Test
    @DisplayName("HealthEndpoint 자체가 없으면 UNKNOWN이다")
    void noEndpointMeansNoVerdict() {
        assertThat(new BackendHealth(provider(null)).upOrNull()).isNull();
    }

    private static BackendHealth backendHealth(HealthEndpoint endpoint) {
        return new BackendHealth(provider(endpoint));
    }

    @SuppressWarnings("unchecked")
    private static ObjectProvider<HealthEndpoint> provider(HealthEndpoint endpoint) {
        ObjectProvider<HealthEndpoint> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(endpoint);
        return provider;
    }

    @Configuration(proxyBeanMethods = false)
    static class BrokenDataSource {
        @Bean
        DataSource dataSource() throws SQLException {
            DataSource dataSource = mock(DataSource.class);
            when(dataSource.getConnection())
                    .thenThrow(new SQLException("connection refused"));
            return dataSource;
        }
    }
}
