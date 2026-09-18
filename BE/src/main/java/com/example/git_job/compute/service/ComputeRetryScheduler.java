package com.example.git_job.compute.service;

import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import java.time.Instant;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 저장된 next retry time이 지난 계산만 다시 시작한다 (S15P21E102-308). */
@Component
public class ComputeRetryScheduler {

    private static final Logger log = LoggerFactory.getLogger(ComputeRetryScheduler.class);
    private static final int BATCH_SIZE = 20;

    private final ComputeSnapshotStore attempts;
    private final CComputeSyncService sync;
    private final Set<Long> requestedUsers = ConcurrentHashMap.newKeySet();

    public ComputeRetryScheduler(ComputeSnapshotStore attempts, CComputeSyncService sync) {
        this.attempts = attempts;
        this.sync = sync;
    }

    /** 목표 조건 저장처럼 응답을 막으면 안 되는 최초 계산을 다음 scheduler tick에 맡긴다. */
    public void requestInitialSync(long userId) {
        requestedUsers.add(userId);
    }

    @Scheduled(fixedDelayString = "${gitjob.compute.retry.poll-interval:5s}",
            initialDelayString = "${gitjob.compute.retry.initial-delay:10s}")
    public void retryDue() {
        requestedUsers.stream().limit(BATCH_SIZE).toList().forEach(userId -> {
            requestedUsers.remove(userId);
            try {
                sync.synchronize(userId);
            } catch (RuntimeException failure) {
                // synchronize가 attempt/backoff를 저장하며, 저장 전에 실패하거나 프로세스가
                // 종료되어도 recoverMissing이 DB 상태를 기준으로 다시 발견한다.
                log.warn("C compute requested sync deferred: userId={}, reason={}",
                        userId, failure.toString());
            }
        });
        for (ComputeAttempt due : attempts.dueAttempts(Instant.now(), BATCH_SIZE)) {
            try {
                // target/evidence가 바뀌었으면 읽었던 token의 오래된 행만 정리한다.
                sync.synchronizeDue(due);
            } catch (RuntimeException failure) {
                // synchronize가 terminal/backoff 상태를 먼저 저장한다. 한 사용자의 실패가
                // 같은 batch의 다른 사용자를 막지 않게 여기서는 로그만 남긴다.
                log.warn("C compute retry deferred: userId={}, reason={}",
                        due.userId(), failure.toString());
            }
        }
    }

    /**
     * 배포 전 완료 사용자와 완료 event 유실 사용자의 최초 계산 상태를 복구한다.
     * 기존 attempt는 {@link #retryDue()}가, 이후 정상 완료 event는 consumer가 맡는다.
     */
    @Scheduled(fixedDelayString = "${gitjob.compute.recovery.poll-interval:5m}",
            initialDelayString = "${gitjob.compute.recovery.initial-delay:15s}")
    public void recoverMissing() {
        for (Long userId : attempts.usersMissingComputeState(
                CComputeSyncService.COMPUTE_CONTRACT_VERSION, BATCH_SIZE)) {
            try {
                sync.synchronize(userId);
            } catch (RuntimeException failure) {
                // synchronize가 attempt 상태를 먼저 저장한다. 같은 batch의 복구를 계속한다.
                log.warn("C compute initial recovery deferred: userId={}, reason={}",
                        userId, failure.toString());
            }
        }
    }
}
