package com.example.git_job.compute.service;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class ComputeRetrySchedulerTest {

    @Test
    @DisplayName("한 사용자의 재시도 실패가 같은 batch의 다음 사용자를 막지 않는다")
    void retriesEveryDueUserIndependently() {
        ComputeSnapshotStore attempts = mock(ComputeSnapshotStore.class);
        CComputeSyncService sync = mock(CComputeSyncService.class);
        ComputeAttempt first = attempt(7L);
        ComputeAttempt second = attempt(8L);
        when(attempts.dueAttempts(any(), anyInt())).thenReturn(List.of(first, second));
        when(sync.synchronizeDue(first)).thenThrow(new IllegalStateException("down"));

        new ComputeRetryScheduler(attempts, sync).retryDue();

        verify(sync).synchronizeDue(first);
        verify(sync).synchronizeDue(second);
    }

    @Test
    @DisplayName("분석은 성공했지만 계산 상태가 없는 사용자를 독립적으로 복구한다")
    void recoversEveryMissingComputeUserIndependently() {
        ComputeSnapshotStore attempts = mock(ComputeSnapshotStore.class);
        CComputeSyncService sync = mock(CComputeSyncService.class);
        when(attempts.usersMissingComputeState(anyInt())).thenReturn(List.of(7L, 8L));
        when(sync.synchronize(7L)).thenThrow(new IllegalStateException("down"));

        new ComputeRetryScheduler(attempts, sync).recoverMissing();

        verify(sync).synchronize(7L);
        verify(sync).synchronize(8L);
    }

    private static ComputeAttempt attempt(long userId) {
        return new ComputeAttempt(userId, "BACKEND||", "f".repeat(64), "RETRYING",
                "COMPUTE_RETRYING", 1, UUID.randomUUID(), Instant.EPOCH, Instant.EPOCH);
    }
}
