package com.example.git_job.analysis.service;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubBranchResponse;
import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.domain.RepositoryCoordinate;
import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

/**
 * 사용자가 고른 저장소·브랜치를 분석 요청으로 바꾼다 (B-FN-002).
 *
 * <p>{@link AnalysisRequestService}가 요구하는 선행 조건을 여기서 갖춘다. 즉 GitHub
 * 권한 확인, 브랜치 존재 확인과 SHA 확정, 서버가 만드는 ID·Registry 버전이다.
 * 클라이언트가 보낸 값 중 실제로 쓰는 것은 저장소 이름과 브랜치 이름뿐이고,
 * 나머지는 모두 GitHub 응답이나 서버가 정한다.</p>
 *
 * <p>GitHub 호출은 트랜잭션 밖에서 끝낸다. 외부 왕복 두 번을 트랜잭션 안에 넣으면
 * 그동안 DB 커넥션을 붙잡고 있게 된다. 배치가 되면 왕복이 2N번이라 더 중요해졌다.</p>
 *
 * <h2>한 사용자에 한 배치</h2>
 *
 * <p>진행 중인 분석이 있으면 새 배치를 받지 않는다(409). 저장소별 중복 방지와는 다른
 * 규칙이다 -- 그쪽은 같은 저장소를 두 번 돌리지 않으려는 것이고, 이쪽은 사용자가 한
 * 번에 한 묶음만 돌리게 하는 것이다.</p>
 *
 * <p>"진행 중"은 {@code activeWindow} 안의 것만 말한다. 창을 넘긴 분석은
 * {@link StaleAnalysisReaper}가 종료시키므로, 워커가 죽어 멈춘 잡 하나가 사용자를
 * 영구히 막는 일은 생기지 않는다.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisSubmissionService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisSubmissionService.class);

    /**
     * 항목이 아니라 요청 전체를 실패시켜야 하는 오류.
     *
     * <p>GitHub 연결 자체가 끊긴 상태라 저장소를 바꿔도 결과가 같고, 화면에는 항목별
     * 배지가 아니라 "GitHub 다시 연결" 복구 경로가 떠야 한다. 항목 안에 묻으면 그
     * 경로가 뜨지 않는다.</p>
     */
    /**
     * 대상 해소의 동시 실행 수.
     *
     * <p>GitHub rate limit 때문에 상한을 둔다. 한 항목이 왕복 두 번이라 4면 한 번에
     * 8개의 호출이 떠 있고, {@code maxBatchSize}가 10이면 세 묶음으로 끝난다.</p>
     */
    static final int RESOLVE_CONCURRENCY = 4;

    private static final Set<ErrorCode> GLOBAL_FAILURES = Set.of(
            ErrorCode.GITHUB_TOKEN_INVALID,
            ErrorCode.GITHUB_RECONNECT_REQUIRED,
            ErrorCode.GITHUB_UNAVAILABLE);

    private final GithubRepositoryClient githubRepositoryClient;
    private final GithubAccessTokenProvider accessTokenProvider;
    private final AnalysisJobRepository analysisJobs;
    private final AnalysisRequestService analysisRequestService;
    private final AnalysisRequestProperties properties;
    private final CurrentRegistryVersion currentRegistryVersion;

    /** 요청 하나가 고른 저장소와 브랜치. */
    public record Target(String repositoryFullName, String branchName) {
    }

    /** 항목 하나의 결말. 실패가 아니라 재사용인 경우를 따로 둔다. */
    public enum Outcome {
        /** 새로 등록했다. */
        ACCEPTED,
        /** 같은 저장소 분석이 이미 진행 중이라 그 Job을 그대로 안내한다. */
        REUSED,
        /** 이 저장소만 실패했다. 나머지는 접수될 수 있다. */
        FAILED
    }

    /**
     * @param requestedRepositoryFullName 클라이언트가 보낸 이름 그대로. 서버는 GitHub의
     *                                    정규 표기로 바꾸지만 화면은 목록에서 받은 이름으로
     *                                    상태를 키잉하므로, 돌려줄 때 원래 이름이 필요하다
     */
    public record Item(
            String requestedRepositoryFullName,
            Outcome outcome,
            String analysisId,
            String status,
            String repositoryFullName,
            String branchName,
            String commitSha,
            ErrorCode error
    ) {
        static Item failed(String requested, ErrorCode error) {
            return new Item(requested, Outcome.FAILED, null, null, null, null, null, error);
        }
    }

    /**
     * @param batchId 접수된 것이 하나도 없으면 {@code null}. 만들지 않은 묶음의 ID를
     *                돌려주면 화면이 없는 배치를 조회하게 된다
     */
    public record BatchSubmission(String batchId, List<Item> items, int pollAfterSeconds) {

        public long countOf(Outcome outcome) {
            return items.stream().filter(item -> item.outcome() == outcome).count();
        }

        /** 하나라도 새로 만들었으면 202, 아니면 200. */
        public boolean created() {
            return countOf(Outcome.ACCEPTED) > 0;
        }
    }

    /**
     * 고른 저장소 전부를 한 묶음으로 등록한다.
     *
     * <p>항목 하나가 실패해도 나머지를 버리지 않는다. 저장소별 실패 사유는 화면이
     * 카드마다 그리는 값이고, 전부 실패했을 때 그것을 오류 봉투 하나로 접으면
     * {@code ErrorResponse}가 code·message 한 쌍뿐이라 가장 필요한 순간에 사유를 잃는다.</p>
     */
    public BatchSubmission submitBatch(long userId, List<Target> targets, String traceId) {
        if (targets.isEmpty()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        if (targets.size() > properties.maxBatchSize()) {
            log.info("Batch rejected, {} targets exceeds max {}: userId={}",
                    targets.size(), properties.maxBatchSize(), userId);
            throw new CustomException(ErrorCode.ANALYSIS_BATCH_TOO_LARGE);
        }

        /*
         * GitHub을 부르기 전에 끊는다. 어차피 막힐 요청이 rate limit을 2N번 쓰고 나서
         * 409를 받을 이유가 없다. 이것은 빠른 거절이고, 진짜 판정은 잠금을 잡은 뒤
         * enqueueBatchAuthorized 안에서 한 번 더 한다.
         */
        if (analysisRequestService.hasActiveAnalysis(userId)) {
            throw new CustomException(ErrorCode.ANALYSIS_BATCH_IN_PROGRESS);
        }

        String accessToken = accessTokenProvider.accessTokenOf(userId);
        Resolution resolution = resolveAll(userId, accessToken, targets);

        if (resolution.payloads().isEmpty()) {
            // 만들 것이 없다. 묶음도 만들지 않고 항목별 사유만 돌려준다.
            return new BatchSubmission(
                    null, List.copyOf(resolution.items()), properties.pollAfterSeconds());
        }

        String batchId = "ab_" + newId();
        String correlationId = traceId == null || traceId.isBlank() ? "tr_" + newId() : traceId;
        try {
            analysisRequestService.enqueueBatchAuthorized(userId, batchId,
                    resolution.payloads(), resolution.staleAnalysisIds(), correlationId);
        } catch (DataIntegrityViolationException concurrent) {
            /*
             * 배치 경로에서는 사실상 도달하지 않는다. 같은 사용자의 동시 제출은 advisory
             * lock이 직렬화하고, 저장소별 경합은 그 잠금 안에서 이미 걸러지기 때문이다.
             * 여기에 닿았다면 예상한 중복 경합이 아니라 진짜 이상 신호이므로 감추지 않는다.
             */
            log.error("Batch insert violated a constraint: userId={}, batchId={}",
                    userId, batchId);
            throw concurrent;
        }
        log.info("Analysis batch enqueued: batchId={}, userId={}, accepted={}, reused={},"
                        + " failed={}, staleClosed={}",
                batchId, userId,
                resolution.items().stream().filter(i -> i.outcome() == Outcome.ACCEPTED).count(),
                resolution.items().stream().filter(i -> i.outcome() == Outcome.REUSED).count(),
                resolution.items().stream().filter(i -> i.outcome() == Outcome.FAILED).count(),
                resolution.staleAnalysisIds().size());
        return new BatchSubmission(
                batchId, List.copyOf(resolution.items()), properties.pollAfterSeconds());
    }

    /**
     * 대상별 해소 결과.
     *
     * @param staleAnalysisIds 창을 넘긴 채 저장소를 점유하고 있던 분석. 새 잡을 넣기 전에
     *                         같은 트랜잭션에서 닫아야 {@code uq_analysis_job_active}가 풀린다
     */
    private record Resolution(
            List<Item> items,
            List<RepositoryAnalysisRequestPayload> payloads,
            List<String> staleAnalysisIds) {
    }

    /** 병렬 해소의 결과 한 칸. 전역 실패는 값으로 실어 보내고 호출부가 던진다. */
    private record Resolved(
            Item item,
            RepositoryAnalysisRequestPayload payload,
            String staleAnalysisId,
            ErrorCode globalFailure) {

        static Resolved of(Item item) {
            return new Resolved(item, null, null, null);
        }
    }

    /**
     * 모든 대상을 GitHub에 물어 확정한다.
     *
     * <h2>제한 병렬로 도는 이유</h2>
     *
     * <p>항목마다 왕복이 두 번이라 순차로 돌면 10개 요청이 GitHub 호출 20회를 차례로
     * 기다리고, 그동안 요청 스레드 하나가 묶인다. 이 경로는 화면이 POST를 N개 병렬로
     * 보내던 자리를 대신하는 것이라, 순차로 두면 저장소를 많이 고른 사용자에게는 이전보다
     * 느려진다.</p>
     *
     * <p>동시 수를 {@link #RESOLVE_CONCURRENCY}로 묶는 것은 rate limit 때문이다. 상한 없이
     * 열면 한 번의 제출이 남은 한도를 한꺼번에 태운다.</p>
     *
     * <p>결과는 입력 순서를 그대로 지킨다. 화면은 이름으로 항목을 찾지만, 응답 순서가
     * 호출마다 달라지면 로그와 테스트를 읽을 수 없다.</p>
     */
    private Resolution resolveAll(long userId, String accessToken, List<Target> targets) {
        /*
         * Registry 버전은 묶음 전체가 하나를 공유한다. 항목마다 따로 읽으면 해소가 도는
         * 동안 CURRENT가 바뀐 배치의 절반이 다른 기준으로 판정된다.
         *
         * 지연 초기화인 것은 만들 것이 하나도 없을 때 Registry를 읽지 않기 위해서다 --
         * 전부 재사용이거나 전부 실패한 요청이 판정 기준을 확정할 이유가 없다.
         */
        Supplier<String> registry = new OnceSupplier(currentRegistryVersion::resolve);

        // 한도를 넘긴 뒤에도 계속 두드리면 회복만 늦어진다. 남은 항목은 부르지 않는다.
        var rateLimited = new AtomicBoolean(false);

        List<Resolved> resolved;
        int threads = Math.min(RESOLVE_CONCURRENCY, targets.size());
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        try {
            var futures = new ArrayList<Future<Resolved>>(targets.size());
            for (Target target : targets) {
                futures.add(pool.submit(
                        () -> resolveOne(userId, accessToken, target, registry, rateLimited)));
            }
            resolved = new ArrayList<>(futures.size());
            for (Future<Resolved> future : futures) {
                resolved.add(awaitResolved(future));
            }
        } finally {
            pool.shutdownNow();
        }

        var items = new ArrayList<Item>(targets.size());
        var payloads = new ArrayList<RepositoryAnalysisRequestPayload>(targets.size());
        var stale = new ArrayList<String>();
        for (Resolved one : resolved) {
            items.add(one.item());
            if (one.payload() != null) {
                payloads.add(one.payload());
            }
            if (one.staleAnalysisId() != null) {
                stale.add(one.staleAnalysisId());
            }
        }
        return new Resolution(items, payloads, stale);
    }

    /**
     * 값을 정확히 한 번만 만드는 지연 공급자.
     *
     * <p>{@code AtomicReference.updateAndGet}으로는 안 된다 -- CAS 가 실패하면 함수를 다시
     * 부르고, 두 스레드가 동시에 {@code null}을 보면 둘 다 부른다. 여기서 두 번 부른다는
     * 것은 Registry 를 두 번 읽는다는 뜻이고, 그사이 CURRENT 가 바뀌면 한 묶음이 서로 다른
     * 기준으로 판정된다 -- 막으려던 바로 그 일이다.</p>
     */
    private static final class OnceSupplier implements Supplier<String> {
        private final Supplier<String> source;
        private String value;

        OnceSupplier(Supplier<String> source) {
            this.source = source;
        }

        @Override
        public synchronized String get() {
            if (value == null) {
                value = source.get();
            }
            return value;
        }
    }

    /**
     * 전역 실패는 해소 전체를 중단시킨다. GitHub 연결이 끊긴 상태라 저장소를 바꿔도
     * 결과가 같고, 화면에는 항목 배지가 아니라 재연결 경로가 떠야 한다.
     */
    private Resolved awaitResolved(Future<Resolved> future) {
        Resolved one;
        try {
            one = future.get();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("저장소 해소가 중단되었습니다.", interrupted);
        } catch (ExecutionException failure) {
            if (failure.getCause() instanceof RuntimeException runtime) {
                throw runtime;
            }
            throw new IllegalStateException(failure.getCause());
        }
        if (one.globalFailure() != null) {
            throw new CustomException(one.globalFailure());
        }
        return one;
    }

    private Resolved resolveOne(long userId, String accessToken, Target target,
            Supplier<String> registry, AtomicBoolean rateLimited) {
        if (rateLimited.get()) {
            return Resolved.of(
                    Item.failed(target.repositoryFullName(), ErrorCode.GITHUB_RATE_LIMITED));
        }
        try {
            return resolve(userId, accessToken, target, registry);
        } catch (CustomException failure) {
            ErrorCode code = failure.getErrorCode();
            if (GLOBAL_FAILURES.contains(code)) {
                return new Resolved(
                        Item.failed(target.repositoryFullName(), code), null, null, code);
            }
            if (code == ErrorCode.GITHUB_RATE_LIMITED) {
                rateLimited.set(true);
            }
            return Resolved.of(Item.failed(target.repositoryFullName(), code));
        }
    }

    /**
     * 항목 하나를 GitHub에 물어 확정한다.
     *
     * <p>{@code registry}는 묶음이 공유하는 판정 기준이다. 실제로 새 잡을 만들 때만
     * 값을 꺼내므로, 전부 재사용이거나 전부 실패한 요청은 Registry를 읽지 않는다.</p>
     */
    private Resolved resolve(long userId, String accessToken, Target target,
            Supplier<String> registry) {
        var coordinate = RepositoryCoordinate.of(target.repositoryFullName(), target.branchName());

        // 이 호출이 성공한다는 것이 곧 사용자가 저장소에 접근할 수 있다는 증거다.
        // 권한이 없으면 GitHub이 404를 주고 REPOSITORY_NOT_FOUND로 바뀐다.
        GithubRepositoryResponse repository = githubRepositoryClient.fetchRepository(
                accessToken, coordinate.owner(), coordinate.repository());
        if (!repository.analyzable()) {
            throw new CustomException(ErrorCode.REPOSITORY_NOT_ANALYZABLE);
        }

        GithubBranchResponse branch = githubRepositoryClient.fetchBranch(
                accessToken, coordinate.owner(), coordinate.repository(), coordinate.branch());

        String repositoryId = Long.toString(repository.id());
        Optional<AnalysisJob> existing =
                analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                        userId, repositoryId, AnalysisJob.IN_PROGRESS_STATUSES);

        String staleAnalysisId = null;
        if (existing.isPresent()) {
            AnalysisJob running = existing.get();
            if (isStale(running)) {
                /*
                 * 창을 넘긴 잡이다. 재사용하면 사용자가 고른 저장소가 조용히 사라진다 --
                 * 그 잡은 곧 reaper가 ANALYSIS_TIMED_OUT으로 닫을 것이고, 묶음 밖이라
                 * 화면은 그 사실조차 알지 못한 채 카드가 대기 상태로 굳는다.
                 *
                 * 그래서 재사용하지 않고 새로 만든다. 다만 그 잡이
                 * uq_analysis_job_active로 이 저장소를 점유하고 있으므로, INSERT 전에
                 * 같은 트랜잭션에서 닫아야 한다. 그 일은 enqueueBatchAuthorized가 한다.
                 */
                staleAnalysisId = running.getAnalysisId();
                log.info("Replacing a stale analysis: analysisId={}, repositoryId={},"
                                + " requestedAt={}",
                        running.getAnalysisId(), repositoryId, running.getRequestedAt());
            } else {
                /*
                 * 창 안의 진행 중 잡이다. 제출 게이트가 이미 409로 걸렀어야 하므로
                 * 정상 흐름에서는 도달하지 않는다. 그래도 남겨 두는 것은, 게이트와 이
                 * 조회가 어긋난 순간에 INSERT가 부분 UNIQUE 인덱스를 위반해 묶음 전체를
                 * 롤백시키는 것보다 이 저장소 하나를 재사용으로 안내하는 편이 낫기
                 * 때문이다. 실패가 아니라 세 번째 결말로 두는 이유이기도 하다.
                 */
                log.warn("Reusing an in-window analysis the gate should have blocked:"
                                + " analysisId={}, repositoryId={}",
                        running.getAnalysisId(), repositoryId);
                return Resolved.of(new Item(target.repositoryFullName(), Outcome.REUSED,
                        running.getAnalysisId(), running.getStatus(), repository.fullName(),
                        running.getBranchName(), running.getCommitSha(), null));
            }
        }

        // 저장소 이름은 GitHub이 준 정규 표기를 쓴다. 사용자가 대소문자를 다르게 보내거나
        // 이름이 바뀐 저장소를 옛 이름으로 보내도 이벤트에는 실제 이름이 남아야 한다.
        var payload = new RepositoryAnalysisRequestPayload(
                "an_" + newId(),
                "ar_" + newId(),
                repository.id(),
                repository.fullName(),
                branch.name(),
                branch.commitSha(),
                RepositoryAnalysisMode.SNAPSHOT,
                registry.get());
        var item = new Item(target.repositoryFullName(), Outcome.ACCEPTED, payload.analysisId(),
                AnalysisJob.STATUS_QUEUED, payload.repositoryFullName(), payload.branchName(),
                payload.commitSha(), null);
        return new Resolved(item, payload, staleAnalysisId, null);
    }

    /** 유효시간을 넘긴 진행 중 잡. 판정 기준은 제출 차단·reaper와 같은 값이다. */
    private boolean isStale(AnalysisJob job) {
        return job.getRequestedAt().isBefore(Instant.now().minus(properties.activeWindow()));
    }

    private String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }
}
