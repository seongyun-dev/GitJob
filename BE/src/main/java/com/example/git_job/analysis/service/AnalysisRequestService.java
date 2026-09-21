package com.example.git_job.analysis.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.messaging.RepositoryAnalysisKafkaProperties;
import com.example.git_job.analysis.outbox.AnalysisOutboxStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.store.AnalysisBatchStore;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.json.JsonMapper;

/**
 * Durable enqueue boundary for analysis jobs (the existing analysis_job model).
 * Call only after checking the authenticated user's repository/branch access and resolving SHA.
 * IDs and registry version must be assigned by the server, not copied from public request JSON.
 */
@Service
public class AnalysisRequestService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisRequestService.class);

    private final AnalysisJobRepository analysisJobs;
    private final AnalysisOutboxStore outbox;
    private final AnalysisBatchStore batches;
    private final RepositoryAnalysisKafkaProperties topics;
    private final JsonMapper jsonMapper;
    private final AnalysisRequestProperties properties;

    public AnalysisRequestService(AnalysisJobRepository analysisJobs, AnalysisOutboxStore outbox,
            AnalysisBatchStore batches, RepositoryAnalysisKafkaProperties topics,
            JsonMapper jsonMapper, AnalysisRequestProperties properties) {
        this.analysisJobs = analysisJobs;
        this.outbox = outbox;
        this.batches = batches;
        this.topics = topics;
        this.jsonMapper = jsonMapper;
        this.properties = properties;
    }

    /**
     * 한 묶음을 통째로 등록한다. 이 경로가 실제 제출이 지나가는 곳이다.
     *
     * <h2>한 트랜잭션이어야 하는 이유</h2>
     *
     * <p>부분 커밋은 {@code completedCount}/{@code totalCount}가 영영 어긋난 반쪽 배치를
     * 만든다. 그리고 중간에 죽으면 제대로 등록되지도 않은 잡이 사용자를
     * {@code activeWindow} 내내 막는다 -- 고치려던 것과 같은 고장이다.</p>
     *
     * <h2>잠금을 먼저 잡는다</h2>
     *
     * <p>{@link AnalysisSubmissionService}가 GitHub을 부르기 전에 이미 한 번 차단을
     * 검사하지만, 그것은 빠른 거절일 뿐 판정이 아니다. 검사와 INSERT 사이에 다른 요청이
     * 끼어들 수 있으므로 <b>잠금을 잡은 뒤 다시 검사한 결과가 진짜</b>다.</p>
     *
     * <p>그 재검사는 반드시 이 트랜잭션 안에서 일어나야 한다. 그래서 공개 메서드
     * {@link #hasActiveAnalysis(long)}이 아니라 같은 클래스의 private
     * {@link #anyActiveAnalysis(long)}를 부른다 -- 공개 메서드를 부르면 지금은 자기 호출이라
     * 우연히 같은 트랜잭션에 머물지만, 누군가 그 호출을 다른 빈으로 빼거나
     * {@code REQUIRES_NEW}를 붙이는 순간 게이트가 조용히 무력해진다.</p>
     *
     * @param batchId 이 묶음의 ID. 구성원 전부가 같은 값을 갖는다
     * @param staleAnalysisIds 이 저장소들을 점유한 채 창을 넘긴 분석. INSERT 전에 닫아야
     *                         {@code uq_analysis_job_active}가 풀린다
     * @return 저장된 순서대로의 요청 이벤트
     */
    @Transactional
    public List<RepositoryAnalysisRequestedEvent> enqueueBatchAuthorized(
            long userId, String batchId, List<RepositoryAnalysisRequestPayload> payloads,
            List<String> staleAnalysisIds, String traceId) {
        if (userId < 1) {
            throw new IllegalArgumentException("userId must be positive");
        }
        if (payloads.isEmpty()) {
            throw new IllegalArgumentException("payloads must not be empty");
        }

        batches.lockUserBatchGate(userId);
        if (anyActiveAnalysis(userId)) {
            throw new CustomException(ErrorCode.ANALYSIS_BATCH_IN_PROGRESS);
        }
        closeStale(staleAnalysisIds);

        var events = new ArrayList<RepositoryAnalysisRequestedEvent>(payloads.size());
        for (RepositoryAnalysisRequestPayload payload : payloads) {
            events.add(enqueueOne(userId, batchId, payload, traceId));
        }
        return events;
    }

    /**
     * 창을 넘긴 채 저장소를 점유하고 있던 분석을 닫는다.
     *
     * <p>{@link StaleAnalysisReaper}가 결국 할 일을 여기서 앞당기는 것이다. 기다리면
     * 새 잡의 INSERT가 부분 UNIQUE 인덱스를 위반하고, 배치가 한 트랜잭션이라 묶음 전체가
     * 롤백된다. 같은 트랜잭션에서 닫으면 그 자리에서 점유가 풀린다.</p>
     *
     * <p>{@code fail()}이 진행 중이 아닌 잡에 {@code false}를 주므로, 그사이 워커가
     * 끝냈다면 그 결과를 덮지 않는다.</p>
     */
    private void closeStale(List<String> staleAnalysisIds) {
        if (staleAnalysisIds.isEmpty()) {
            return;
        }
        Instant now = Instant.now();
        for (AnalysisJob stale : analysisJobs.findAllById(staleAnalysisIds)) {
            if (stale.fail(AnalysisJob.ERROR_ANALYSIS_TIMED_OUT, now)) {
                analysisJobs.saveAndFlush(stale);
                log.warn("Closed a stale analysis to make room for a new request:"
                                + " analysisId={}, userId={}, repositoryId={}, requestedAt={}",
                        stale.getAnalysisId(), stale.getUserId(), stale.getRepositoryId(),
                        stale.getRequestedAt());
            }
        }
    }

    /**
     * 진행 중 분석이 있는지. 제출 차단과 조회가 <b>같은 이 판정</b>을 쓴다.
     *
     * <p>판단을 두 곳에서 하면 화면이 "제출 가능"이라 말한 뒤 서버가 409를 주는 상태가
     * 생긴다. 창을 넘긴 분석은 {@link StaleAnalysisReaper}가 종료시키므로 여기서 그것을
     * 걸러도 사용자가 영구히 막히지 않는다.</p>
     */
    @Transactional(readOnly = true)
    public boolean hasActiveAnalysis(long userId) {
        return anyActiveAnalysis(userId);
    }

    /**
     * 판정 자체. 트랜잭션 경계를 갖지 않으므로 호출자의 트랜잭션에 그대로 참여한다 --
     * 잠금 안의 재검사가 이 사실에 기대고 있다.
     */
    private boolean anyActiveAnalysis(long userId) {
        return analysisJobs.existsByUserIdAndStatusInAndRequestedAtAfter(
                userId, AnalysisJob.IN_PROGRESS_STATUSES,
                Instant.now().minus(properties.activeWindow()));
    }

    /**
     * 단건 등록. 묶음 없이 접수되므로 {@code batch_id}는 {@code null}이다.
     *
     * <p>배치 경로가 생긴 뒤에도 남겨 둔다 -- CDC 통합 테스트가 이 경계를 직접 부르고,
     * 한 건짜리 등록의 의미가 배치와 다르지 않아 굳이 깨뜨릴 이유가 없다.</p>
     */
    @Transactional
    public RepositoryAnalysisRequestedEvent enqueueAuthorized(
            long userId, RepositoryAnalysisRequestPayload payload, String traceId) {
        if (userId < 1) {
            throw new IllegalArgumentException("userId must be positive");
        }
        return enqueueOne(userId, null, payload, traceId);
    }

    /** Returns only after job and event are saved; no Kafka connection is needed here. */
    private RepositoryAnalysisRequestedEvent enqueueOne(
            long userId, String batchId, RepositoryAnalysisRequestPayload payload,
            String traceId) {
        var event = RepositoryAnalysisRequestedEvent.create(
                "ev_" + UUID.randomUUID(), Instant.now(), traceId, payload);
        String json = jsonMapper.writeValueAsString(event);

        // saveAndFlush, not save: the outbox row below is written with JdbcTemplate, which
        // reaches the database immediately, while JPA would hold this insert until commit.
        // analysis_outbox.analysis_id references analysis_job, so the parent row has to be
        // there first. Both still roll back together as one transaction.
        analysisJobs.saveAndFlush(AnalysisJob.queue(
                payload.analysisId(), userId, Long.toString(payload.githubRepositoryId()),
                payload.repositoryFullName(), payload.branchName(), payload.commitSha(),
                event.occurredAt(), batchId));
        outbox.insert(event, topics.requests(), json);
        return event;
    }
}
