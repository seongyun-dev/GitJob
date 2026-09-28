package com.example.git_job.analysis.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 워커가 끝내지 못한 분석을 종료시킨다 (S15P21E102-136).
 *
 * <h2>왜 필요한가</h2>
 *
 * <p>분석이 {@code QUEUED}에 영구히 남는 일이 실제로 있었다(2026-09 운영, 49시간).
 * 워커가 요청을 집어 가지 못했거나, 집어 간 뒤 결과를 내기 전에 죽었거나,
 * Debezium이 멈춰 요청이 Kafka에 닿지 못한 경우다. 그 상태를 되돌릴 경로가 코드
 * 어디에도 없었다 -- 재시도 루프도, 오래된 잡을 정리하는 것도.</p>
 *
 * <p>그대로 두고 "진행 중이면 새 요청을 막는다"를 얹으면 그 사용자는 영영 새 분석을
 * 못 한다. 차단에 유효시간을 두는 것만으로는 부족하다 -- 유효시간은 배치 차단만
 * 풀어 주고 {@code uq_analysis_job_active}는 풀어 주지 못하기 때문이다. 그 부분
 * UNIQUE 인덱스는 {@code (user_id, repository_id)}를 진행 중 상태에서 점유하므로,
 * 멈춘 잡이 살아 있는 한 <b>그 저장소는 영구히 분석 불가</b>가 된다. 인덱스를
 * 실제로 풀려면 상태를 종료로 옮기는 수밖에 없고, 그 일을 여기서 한다.</p>
 *
 * <h2>{@code activeWindow}를 그대로 쓴다</h2>
 *
 * <p>차단 기준과 정리 기준이 같은 값이어야 한다. 정리가 더 늦으면 차단이 풀린 뒤에도
 * 저장소가 묶여 있고, 정리가 더 이르면 아직 막고 있는 잡을 죽이게 된다.</p>
 *
 * <p>기본 2시간의 근거는 워커가 한 잡을 붙들 수 있는 최대 시간이다
 * ({@code Infra/compose/compose.yaml}의 {@code analysis-worker}):
 * 클론 타임아웃 600초, claim lease 900초, Kafka max poll interval 900초,
 * 최대 시도 5회 -- 최악의 경우 5 x 15분 = 75분. 2시간은 그 위의 여유다.
 * <b>워커 쪽 값을 올리면 여기도 함께 올려야 한다.</b></p>
 *
 * <h2>감수하는 것</h2>
 *
 * <p>살아 있는데 느린 분석을 죽일 수 있다. 그때 워커가 뒤늦게 보낸 결과는
 * {@code AnalysisResultService}가 {@code ALREADY_TERMINAL}로 흘리고, 그 분석의 근거는
 * 저장되지 않는다. 그래서 창을 워커 최악값의 배 가까이 잡았고, 실제로 그런 일이
 * 일어나면 {@code AnalysisResultService}가 WARN으로 알린다. 그 로그가 보이기
 * 시작하면 창이 짧다는 뜻이다.</p>
 */
@Component
public class StaleAnalysisReaper {

    private static final Logger log = LoggerFactory.getLogger(StaleAnalysisReaper.class);

    /**
     * 한 tick에서 종료시킬 최대 건수.
     *
     * <p>{@code ComputeRetryScheduler}와 같은 값이다. 오래 밀린 상태에서 한 트랜잭션이
     * 수천 행을 잠그지 않게 나눠 처리하고, 남은 것은 다음 tick이 가져간다.</p>
     */
    private static final int BATCH_SIZE = 20;

    private final AnalysisJobRepository jobs;
    private final AnalysisRequestProperties properties;

    public StaleAnalysisReaper(AnalysisJobRepository jobs, AnalysisRequestProperties properties) {
        this.jobs = jobs;
        this.properties = properties;
    }

    @Scheduled(fixedDelayString = "${gitjob.analysis.reaper.poll-interval:1m}",
            initialDelayString = "${gitjob.analysis.reaper.initial-delay:30s}")
    @Transactional
    public void reapStale() {
        Instant now = Instant.now();
        Instant threshold = now.minus(properties.activeWindow());
        List<AnalysisJob> stale = jobs.findByStatusInAndRequestedAtBefore(
                AnalysisJob.IN_PROGRESS_STATUSES, threshold, PageRequest.of(0, BATCH_SIZE));

        for (AnalysisJob job : stale) {
            // fail()은 진행 중이 아닌 잡에 false를 돌려준다. 조회와 이 줄 사이에 워커가
            // 끝냈다면 그 결과를 덮지 않고 넘어간다.
            if (!job.fail(AnalysisJob.ERROR_ANALYSIS_TIMED_OUT, now)) {
                continue;
            }
            jobs.save(job);
            // WARN인 이유: 정상 운영에서는 나오지 않는 줄이다. 이 로그가 쌓이면 워커가
            // 죽었거나 요청이 Kafka에 닿지 못하고 있다는 뜻이고, 이번 장애에서 그것을
            // 이틀 동안 아무도 몰랐다.
            log.warn("Analysis reaped after {}: analysisId={}, userId={}, repositoryId={},"
                            + " requestedAt={}",
                    properties.activeWindow(), job.getAnalysisId(), job.getUserId(),
                    job.getRepositoryId(), job.getRequestedAt());
        }
    }
}
