package com.example.git_job.compute.service;

import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import java.time.Instant;
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

    public ComputeRetryScheduler(ComputeSnapshotStore attempts, CComputeSyncService sync) {
        this.attempts = attempts;
        this.sync = sync;
    }

    @Scheduled(fixedDelayString = "${gitjob.compute.retry.poll-interval:5s}",
            initialDelayString = "${gitjob.compute.retry.initial-delay:10s}")
    public void retryDue() {
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
}
