package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisProgressEvent;
import com.example.git_job.analysis.service.AnalysisProgressService;
import lombok.RequiredArgsConstructor;
import org.springframework.kafka.annotation.KafkaListener;

/**
 * 워커가 보낸 단계 전환을 받는다.
 *
 * <p>{@link RepositoryAnalysisResultConsumer} 와 달리 {@code @Component} 가 아니다.
 * 진행 토픽은 선택값이고, 토픽 이름이 없을 때 이 리스너가 살아 있으면 Spring 이
 * 이름 없는 토픽을 구독하려다 기동에서 실패한다. 빈 등록은
 * {@link RepositoryAnalysisKafkaConfiguration} 이 조건부로 한다.</p>
 *
 * <p>여기서 던지지 않는다. 오프셋이 멈추면 표시용 메시지 하나가 파티션을 세우고,
 * 그 뒤의 진행은 물론 다른 분석의 진행까지 막힌다. 실패는 컨테이너 error handler
 * 가 몇 번 재시도한 뒤 버린다 -- 결과 토픽과 정반대의 선택이며, 잃어도 되는
 * 메시지이기 때문에 할 수 있는 선택이다.</p>
 */
@RequiredArgsConstructor
public class RepositoryAnalysisProgressConsumer {

    private final AnalysisProgressService progress;

    @KafkaListener(
            topics = "${gitjob.kafka.topics.repository-analysis.progress}",
            groupId = "${gitjob.kafka.consumer.repository-analysis-progress.group-id}",
            containerFactory = "repositoryAnalysisProgressListenerFactory")
    public void onProgress(RepositoryAnalysisProgressEvent event) {
        progress.apply(event);
    }
}
