package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.service.AnalysisResultService;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.service.EvidenceAuthorshipService;
import com.example.git_job.compute.service.CComputeSyncService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import lombok.RequiredArgsConstructor;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Consumes the analysis worker's results.
 *
 * <p>This listener is the only reason {@code analysis_job} ever leaves
 * {@code QUEUED}. Without it the worker can clone, parse and judge perfectly
 * and the user still sees "대기 중" forever.</p>
 *
 * <p>Deliberately thin. Deserialization is the container's job, the decision is
 * {@link AnalysisResultService}'s, and this only connects them — so the
 * transaction boundary is the service method rather than the poll loop.</p>
 *
 * <p>Throwing here means the offset is not committed and the message comes
 * back. The container's error handler decides how many times before giving up;
 * see {@code RepositoryAnalysisKafkaConfiguration}.</p>
 */
@Component
@RequiredArgsConstructor
public class RepositoryAnalysisResultConsumer {

    private static final Logger log =
            LoggerFactory.getLogger(RepositoryAnalysisResultConsumer.class);

    private final AnalysisResultService results;
    private final EvidenceAuthorshipService authorship;
    private final CComputeSyncService compute;

    /**
     * v1 과 v3 두 토픽을 함께 구독한다 (S15P21E102-279 후속).
     *
     * <p>워커는 Registry 버전에 따라 발행 토픽을 <b>바꾼다</b>. v1 을 함께 보내지
     * 않으므로 v3 토픽을 구독하지 않으면 {@code registry-20260911.3/.4} 결과가 통째로
     * 도달하지 않고, 분석은 QUEUED 에 남아 C 계산도 시작되지 않는다.</p>
     *
     * <p>두 리스너로 나누지 않는 이유는 처리가 같기 때문이다. 계약 버전 차이는 payload
     * 의 선택 필드로 드러나고, 그 해석은 {@link AnalysisResultService} 한 곳에 있다.</p>
     *
     * <p>토픽 목록은 빈이 만든다({@code repositoryAnalysisResultTopics}). v3 토픽은
     * 선택값이라 미설정이면 빈 문자열이 되는데, 그대로 애너테이션에 넣으면 Spring 이
     * 이름 없는 토픽을 구독하려다 실패한다.</p>
     */
    @KafkaListener(
            topics = "#{@repositoryAnalysisResultTopics}",
            groupId = "${gitjob.kafka.consumer.repository-analysis-results.group-id}",
            containerFactory = "repositoryAnalysisResultListenerFactory")
    public void onResult(RepositoryAnalysisResultEvent event) {
        AnalysisResultService.Applied applied = results.apply(event);

        // 근거는 위에서 이미 커밋됐다. 기여 판정은 GitHub 을 호출하므로 따로 둔다 --
        // 여기서 던지면 오프셋이 안 올라가고 결과 전체가 재배달되는데, 그러면
        // GitHub 이 잠깐 느렸다는 이유로 판정된 근거 수백 건을 다시 쓰게 된다.
        // 판정이 없으면 Personal Level 만 비고, 재분석이 채운다.
        AnalysisJob job = results.attributionTarget(event, applied);
        if (job == null) {
            return;
        }
        try {
            authorship.attribute(job);
        } catch (RuntimeException unavailable) {
            log.warn("authorship deferred: analysisId={}, reason={}",
                    job.getAnalysisId(), unavailable.toString());
        }

        // 기여 판정 뒤에 부른다. C 는 개인 Level 을 top-level personal_assessments 로 받는데,
        // 판정이 붙기 전에 보내면 아무도 본인 근거가 없는 Evidence 로 추천이 계산된다.
        //
        // 판정이 실패했어도 부른다. 그때는 개인 Level 이 미확인으로 가고, C 가 그것을
        // "본인이 안 썼다"가 아니라 "확인되지 않았다"로 다룬다. 계산 자체를 미루면
        // 화면은 근거가 있는데도 아무 결과가 없는 상태가 된다.
        //
        // 여기서 던지지 않는 이유는 위와 같다 -- 오프셋이 안 올라가면 C 가 잠깐 느렸다는
        // 이유로 판정된 근거 수백 건을 다시 쓰게 된다. C 계산은 다음 분석 완료나
        // 목표 직무 변경에서 다시 시도된다.
        try {
            compute.synchronize(job.getUserId());
        } catch (RuntimeException unavailable) {
            log.warn("C compute deferred: userId={}, analysisId={}, reason={}",
                    job.getUserId(), job.getAnalysisId(), unavailable.toString());
        }
    }
}
