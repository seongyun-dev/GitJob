package com.example.git_job.analysis.service;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 서버가 분석 요청에 채워 넣는 값. 클라이언트가 보낸 값을 쓰지 않는다.
 *
 * <p>Registry 버전은 여기 없다. 설정으로 두면 실재하지 않는 버전이 기본값으로
 * 앉을 수 있고, 실제로 그랬다. {@link CurrentRegistryVersion}이 C Registry의
 * 활성 alias를 DB에서 읽는다.</p>
 *
 * @param pollAfterSeconds 202 응답에 실어 보낼 재조회 권장 간격
 * @param activeWindow 진행 중 분석이 새 요청을 막는 기간이자, 그것을 넘긴 분석을
 *                     {@code StaleAnalysisReaper}가 종료시키는 기준. 두 곳이 같은 값을
 *                     쓰는 것이 중요하다 -- 차단만 풀고 잡을 살려 두면 그 저장소가
 *                     {@code uq_analysis_job_active}에 묶여 영구히 분석 불가가 된다
 * @param completedBatchVisibleFor 끝난 배치를 화면에 계속 보여 주는 기간. 새로고침해도
 *                                 "4/4 완료"가 남아 있되 며칠 뒤 옛 배치가 되살아나지 않게 한다
 * @param maxBatchSize 한 요청에 담을 수 있는 저장소 수. 항목마다 GitHub 왕복이 2번이라
 *                     상한이 없으면 한 요청이 rate limit을 통째로 쓴다
 */
@ConfigurationProperties("gitjob.analysis.request")
public record AnalysisRequestProperties(
        @DefaultValue("2") int pollAfterSeconds,
        @DefaultValue("2h") Duration activeWindow,
        @DefaultValue("30m") Duration completedBatchVisibleFor,
        @DefaultValue("10") int maxBatchSize
) {

    public AnalysisRequestProperties {
        if (pollAfterSeconds < 1) {
            throw new IllegalArgumentException("pollAfterSeconds must be at least 1");
        }
        if (activeWindow == null || activeWindow.isZero() || activeWindow.isNegative()) {
            throw new IllegalArgumentException("activeWindow must be positive");
        }
        if (completedBatchVisibleFor == null || completedBatchVisibleFor.isNegative()) {
            throw new IllegalArgumentException("completedBatchVisibleFor must not be negative");
        }
        if (maxBatchSize < 1) {
            throw new IllegalArgumentException("maxBatchSize must be at least 1");
        }
    }
}
