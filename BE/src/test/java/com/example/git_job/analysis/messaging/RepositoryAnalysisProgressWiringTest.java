package com.example.git_job.analysis.messaging;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

import com.example.git_job.analysis.service.AnalysisProgressService;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.kafka.autoconfigure.KafkaProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;

/**
 * 진행 표시가 <b>꺼진 채로</b> 배포되는지 확인한다.
 *
 * <p>이 티켓의 배포 순서는 "BE 를 먼저 올려도 아무 일도 일어나지 않는다"에 기대고
 * 있다. 그 약속을 지키는 것은 토픽 이름이 비었을 때 리스너가 아예 존재하지 않는
 * 것뿐이고, 조건을 잘못 쓰면 빈 문자열도 "설정됨"으로 읽혀 기동에서 죽는다 --
 * {@code @ConditionalOnProperty} 는 실제로 그렇게 동작한다.</p>
 *
 * <p>{@code contextLoads} 가 이것을 대신 잡아 주지 못한다. 그쪽은 Postgres 가 없는
 * 개발 기기에서 Flyway 단계에서 먼저 멈춘다.</p>
 */
class RepositoryAnalysisProgressWiringTest {

    private final ApplicationContextRunner contexts = new ApplicationContextRunner()
            .withUserConfiguration(RepositoryAnalysisKafkaConfiguration.class)
            .withBean(KafkaProperties.class, KafkaProperties::new)
            .withBean(KafkaTemplate.class,
                    () -> new KafkaTemplate<>(new DefaultKafkaProducerFactory<>(Map.of())))
            .withBean(AnalysisProgressService.class, () -> mock(AnalysisProgressService.class))
            .withPropertyValues(
                    "gitjob.kafka.topics.repository-analysis.requests=gitjob.requests.v1",
                    "gitjob.kafka.topics.repository-analysis.results=gitjob.results.v1",
                    "gitjob.kafka.topics.repository-analysis.results-dlq=gitjob.results.dlq.v1");

    @Test
    @DisplayName("진행 토픽이 없으면 구독하지 않는다")
    void doesNotSubscribeWhenTheTopicIsNotConfigured() {
        contexts.run(context -> assertEquals(0,
                context.getBeanNamesForType(RepositoryAnalysisProgressConsumer.class).length));
    }

    @Test
    @DisplayName("진행 토픽을 채우면 그때 구독한다")
    void subscribesOnceTheTopicIsConfigured() {
        contexts.withPropertyValues(
                        "gitjob.kafka.topics.repository-analysis.progress=gitjob.progress.v1")
                .run(context -> assertEquals(1,
                        context.getBeanNamesForType(RepositoryAnalysisProgressConsumer.class)
                                .length));
    }
}
