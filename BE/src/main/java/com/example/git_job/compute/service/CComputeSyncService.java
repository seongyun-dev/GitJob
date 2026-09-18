package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeClient;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.AnalysisCompleted;
import com.example.git_job.compute.client.dto.CohortResolved;
import com.example.git_job.compute.client.dto.CohortSelector;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 사용자 분석이 끝나면 C에 계산을 맡기고 결과 Snapshot ID를 저장한다 (S15P21E102-279).
 *
 * <p>순서는 {@code docs/ai/c-compute-backend-integration.md} §3이 정한다.</p>
 *
 * <pre>
 * job-cohorts/resolve  → cohort·demand Snapshot ID와 compute_versions
 * analyses/completed   → RECOMMENDATION Snapshot ID
 * user_c_snapshot 저장
 * </pre>
 *
 * <h2>트랜잭션을 걸지 않는다</h2>
 *
 * <p>가운데에 HTTP 왕복이 둘 있다. 트랜잭션 안에서 부르면 C가 느린 동안 DB 커넥션을
 * 쥐고 있게 되고, C의 계산 시간(초 단위)이 그대로 커넥션 풀 고갈로 번진다. 저장은
 * 한 문장이라 원자성이 따로 필요 없다.</p>
 *
 * <h2>같은 계산을 두 번 하지 않는다</h2>
 *
 * <p>{@code eventId}가 입력에서 결정론적으로 나오므로, 이미 저장된 event면 C를 부르지
 * 않고 그 결과를 돌려준다. 그 검사를 통과한 둘이 동시에 계산하더라도 C가 같은 event에
 * 같은 결과를 주고 UNIQUE 제약이 두 번째 저장을 무시한다.</p>
 */
@Service
public class CComputeSyncService {

    private static final Logger log = LoggerFactory.getLogger(CComputeSyncService.class);

    private static final String COHORT_RESOLVE_PATH = "/internal/v1/c/job-cohorts/resolve";
    private static final String ANALYSES_COMPLETED_PATH = "/internal/v1/c/analyses/completed";
    /**
     * 저장된 Snapshot을 다시 계산해야 하는 BE↔C 활성 매칭 계약.
     * 공고 수요 집계나 추천 알고리즘 결과 의미가 바뀌면 반드시 올린다.
     */
    static final String COMPUTE_CONTRACT_VERSION =
            ComputeSnapshotStore.CURRENT_COMPUTE_CONTRACT_VERSION;
    private static final int MAX_ATTEMPTS = 3;
    private static final int RUNNING_LEASE_SECONDS = 120;

    private final CComputeClient client;
    private final UserEvidenceAssembler assembler;
    private final UserTargetStore targets;
    private final ComputeSnapshotStore snapshots;

    public CComputeSyncService(CComputeClient client, UserEvidenceAssembler assembler,
                               UserTargetStore targets, ComputeSnapshotStore snapshots) {
        this.client = client;
        this.assembler = assembler;
        this.targets = targets;
        this.snapshots = snapshots;
    }

    /**
     * 계산을 맡긴다.
     *
     * @return 계산할 조건이 아직 갖춰지지 않았으면 비어 있다. 목표 직무가 없거나 성공한
     *         분석이 없는 경우이며, 오류가 아니라 정상 상태다.
     * @throws CComputeException C가 준비되지 않았거나 장애일 때. 호출자가 상태로 바꾼다.
     */
    public Optional<ComputeSnapshot> synchronize(long userId) {
        return synchronize(userId, null);
    }

    /** 저장된 재시도 행이 아직 현재 identity인지 확인한 뒤 다시 계산한다. */
    Optional<ComputeSnapshot> synchronizeDue(ComputeAttempt due) {
        return synchronize(due.userId(), due);
    }

    private Optional<ComputeSnapshot> synchronize(long userId, ComputeAttempt due) {
        Optional<Target> target = targets.find(userId);
        if (target.isEmpty()) {
            log.debug("C 계산 생략: 목표 직무 미선택 userId={}", userId);
            return Optional.empty();
        }
        Assembled assembled = assembler.assemble(userId);
        if (!assembled.isReady()) {
            // 이유를 남긴다. 재분석해야 풀리는 상태(계보 없음·Rule Pack 혼재)를
            // "계산 중"과 같이 취급하면 화면이 영원히 기다린다.
            log.debug("C 계산 생략: userId={}, reason={}", userId, assembled.unavailable());
            return Optional.empty();
        }
        Target selectedTarget = target.get();
        if (due != null && (!due.targetKey().equals(selectedTarget.targetKey())
                || !due.evidenceVersion().equals(assembled.evidenceVersion()))) {
            // 목표/Evidence가 바뀐 뒤 남은 retry다. 읽었던 정확한 token만 지우고
            // 아래에서 현재 identity를 정상 claim한다.
            snapshots.deleteAttempt(due);
        }
        Instant now = Instant.now();
        Optional<ComputeAttempt> claimed = snapshots.tryStartAttempt(userId,
                selectedTarget.targetKey(), assembled.evidenceVersion(), now,
                now.plusSeconds(RUNNING_LEASE_SECONDS), MAX_ATTEMPTS);
        if (claimed.isEmpty()) {
            log.debug("C 계산 생략: active/terminal attempt userId={}, targetKey={}, evidence={}",
                    userId, selectedTarget.targetKey(), assembled.evidenceVersion());
            return Optional.empty();
        }

        ComputeAttempt attempt = claimed.get();
        if (attempt.failed()) {
            log.warn("C 계산 retry budget 소진: userId={}, targetKey={}, evidence={}",
                    userId, selectedTarget.targetKey(), assembled.evidenceVersion());
            return Optional.empty();
        }
        try {
            ComputeSnapshot result = compute(userId, selectedTarget, assembled, true);
            snapshots.clearAttempt(attempt);
            return Optional.of(result);
        } catch (CComputeException failure) {
            recordFailure(attempt, failure);
            throw failure;
        } catch (RuntimeException failure) {
            recordRetry(attempt, "COMPUTE_UNAVAILABLE", null);
            throw failure;
        }
    }

    private void recordFailure(ComputeAttempt attempt, CComputeException failure) {
        switch (failure.getStatus()) {
            case INVALID_INPUT -> recordTerminal(attempt, "COMPUTE_INVALID_INPUT");
            case CONFLICT -> recordTerminal(attempt, "COMPUTE_IDEMPOTENCY_CONFLICT");
            case TOO_LARGE -> recordTerminal(attempt, "COMPUTE_RESULT_TOO_LARGE");
            case SCOPE_MISMATCH -> recordTerminal(attempt, "COMPUTE_SCOPE_MISMATCH");
            case INTEGRITY_FAILED -> recordTerminal(attempt, "COMPUTE_INTEGRITY_FAILED");
            case NOT_FOUND -> recordTerminal(attempt, "COMPUTE_INPUT_NOT_FOUND");
            case PREPARING, NOT_PREPARED, MATCHING_NOT_PREPARED, COMPUTE_FAILED, TIMEOUT,
                    UNAVAILABLE
                    -> recordRetry(attempt, "COMPUTE_RETRYING", failure.getRetryAfterSec());
        }
    }

    private void recordRetry(ComputeAttempt attempt, String reason, Integer retryAfterSec) {
        Instant now = Instant.now();
        if (attempt.attemptCount() >= MAX_ATTEMPTS) {
            snapshots.markFailed(attempt, "COMPUTE_RETRY_EXHAUSTED", now);
            return;
        }
        int backoff = retryAfterSec == null
                ? Math.min(300, 5 * (1 << Math.max(0, attempt.attemptCount() - 1)))
                : Math.max(0, retryAfterSec);
        snapshots.markRetrying(attempt, reason, now.plusSeconds(backoff), now);
    }

    private void recordTerminal(ComputeAttempt attempt, String reason) {
        snapshots.markFailed(attempt, reason, Instant.now());
    }

    /**
     * @param retryOnConflict 409를 한 번만 다시 시도한다. C의 계산 버전이 방금 바뀐 경우
     *                        새 {@code compute_versions}로 event ID가 달라져 풀린다.
     *                        무한히 다시 만들지 않으려고 깊이를 하나로 묶어 둔다.
     */
    private ComputeSnapshot compute(long userId, Target target, Assembled assembled,
                                    boolean retryOnConflict) {
        CohortResolved cohort = client.post(COHORT_RESOLVE_PATH,
                CohortSelector.of(target.targetRole(), target.regions(), target.careerLevels()),
                CohortResolved.class);
        if (cohort == null || !cohort.isComplete()) {
            // 200인데 쌍이 아니면 C가 준비되지 않은 것이다. 하나만 들고 계산하면 추천의
            // 분모와 공고 목록의 분모가 달라진다.
            throw new CComputeException(CComputeStatus.NOT_PREPARED, "COHORT_NOT_PREPARED", null,
                    "C가 cohort·demand 쌍을 반환하지 않았습니다.");
        }

        String eventId = eventId(userId, assembled.evidenceVersion(),
                cohort.cohortSnapshotId(), cohort.computeVersions());
        Optional<ComputeSnapshot> existing = snapshots.findByEventId(eventId);
        if (existing.isPresent()) {
            log.debug("C 계산 재사용: userId={}, eventId={}", userId, eventId);
            return existing.get();
        }

        AnalysisCompleted event = new AnalysisCompleted(
                AnalysisCompleted.SCHEMA_VERSION,
                eventId,
                // trace_id만 다른 재전달은 C가 허용한다. 멱등은 event_id가 지킨다.
                UUID.randomUUID().toString(),
                Instant.now(),
                String.valueOf(userId),
                assembled.payload().analysisId(),
                cohort.cohortSnapshotId(),
                assembled.payload());

        AnalysisCompleted.Result result;
        try {
            result = client.post(ANALYSES_COMPLETED_PATH, event, AnalysisCompleted.Result.class);
        } catch (CComputeException e) {
            if (e.getStatus() == CComputeStatus.CONFLICT && retryOnConflict) {
                // 같은 event ID에 다른 내용이라는 뜻이다. 대개 C의 계산 버전이 방금 바뀌어
                // resolve가 새 compute_versions를 줄 준비가 된 상태다. 한 번만 다시 만든다.
                log.warn("C event 충돌로 재계산: userId={}, eventId={}", userId, eventId);
                return compute(userId, target, assembled, false);
            }
            throw e;
        }

        String recommendation = result == null ? null : result.recommendationSnapshotId();
        if (recommendation == null) {
            // 큐에 넣었다는 응답을 완료로 받아들이지 않는다. 결과 ID 없이 저장하면
            // 공개 API가 존재하지 않는 Snapshot을 조회한다.
            throw new CComputeException(CComputeStatus.COMPUTE_FAILED, null, null,
                    "C 완료 응답에 RECOMMENDATION Snapshot이 없습니다: eventId=" + eventId);
        }

        ComputeSnapshot snapshot = new ComputeSnapshot(userId, assembled.evidenceVersion(),
                cohort.cohortSnapshotId(), cohort.demandSnapshotId(), recommendation,
                eventId, target.targetKey(), COMPUTE_CONTRACT_VERSION, Instant.now());
        boolean inserted = snapshots.save(snapshot);
        log.info("C 계산 완료: userId={}, targetKey={}, recommendation={}, inserted={}",
                userId, target.targetKey(), recommendation, inserted);
        return inserted ? snapshot : snapshots.findByEventId(eventId).orElse(snapshot);
    }

    /**
     * 완료 event의 결정론적 ID.
     *
     * <p>{@code computeVersions}를 재료에 넣는 것이 중요하다. C는 Registry나 알고리즘
     * 버전이 바뀐 뒤 같은 event ID로 다시 계산하려 하면 409로 거절한다. 버전을 재료에
     * 넣어 두면 배포로 버전이 바뀐 순간 ID가 저절로 달라져 그 충돌이 생기지 않는다.</p>
     *
     * <p>시각이나 난수를 넣지 않는다. 넣으면 재시작할 때마다 C가 같은 계산을 다시 한다.</p>
     */
    static String eventId(long userId, String evidenceVersion, String cohortSnapshotId,
                          Map<String, String> computeVersions) {
        StringBuilder canonical = new StringBuilder()
                .append(userId).append('')
                .append(evidenceVersion).append('')
                .append(cohortSnapshotId).append('\u001e')
                .append("backend_contract").append('\u001f')
                .append(COMPUTE_CONTRACT_VERSION);
        new TreeMap<>(computeVersions == null ? Map.<String, String>of() : computeVersions)
                .forEach((key, value) -> canonical.append('')
                        .append(key).append('').append(value));
        return "ev-" + sha256(canonical.toString());
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256을 사용할 수 없습니다.", e);
        }
    }
}
