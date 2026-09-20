package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.dto.EvidencePayload;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

class AdminComputeAttemptServiceTest {

    private static final long USER_ID = 7L;
    private static final String TARGET_KEY = "BACKEND|서울|신입";
    private static final String EVIDENCE = "a".repeat(64);

    private final ComputeSnapshotStore attempts = mock(ComputeSnapshotStore.class);
    private final UserTargetStore targets = mock(UserTargetStore.class);
    private final UserEvidenceAssembler evidence = mock(UserEvidenceAssembler.class);
    private final AdminComputeAttemptService service =
            new AdminComputeAttemptService(attempts, targets, evidence);

    @Test
    void dryRunAndRearmRequireTheCurrentExactIdentity() {
        UUID token = UUID.randomUUID();
        ComputeAttempt failed = new ComputeAttempt(USER_ID, TARGET_KEY, EVIDENCE,
                "FAILED", "COMPUTE_RETRY_EXHAUSTED", 3, token, null, Instant.now());
        ComputeAttempt rearmed = new ComputeAttempt(USER_ID, TARGET_KEY, EVIDENCE,
                "RETRYING", "OPERATOR_REARMED", 0, UUID.randomUUID(), Instant.now(),
                Instant.now());
        when(attempts.findAttempt(USER_ID, TARGET_KEY, EVIDENCE))
                .thenReturn(Optional.of(failed));
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.now())));
        when(targets.findForUpdate(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.now())));
        when(evidence.assemble(USER_ID)).thenReturn(
                new Assembled(EVIDENCE, mock(EvidencePayload.class), null));
        when(attempts.rearmFailedAttempt(org.mockito.ArgumentMatchers.eq(USER_ID),
                org.mockito.ArgumentMatchers.eq(TARGET_KEY),
                org.mockito.ArgumentMatchers.eq(EVIDENCE),
                org.mockito.ArgumentMatchers.eq(token), org.mockito.ArgumentMatchers.eq(42L),
                org.mockito.ArgumentMatchers.eq("canary"),
                org.mockito.ArgumentMatchers.any(Instant.class)))
                .thenReturn(Optional.of(rearmed));

        assertThat(service.dryRun(USER_ID, TARGET_KEY, EVIDENCE, token).eligible()).isTrue();
        assertThat(service.rearm(USER_ID, TARGET_KEY, EVIDENCE, token, 42L, "canary"))
                .isEqualTo(rearmed);
        verify(attempts).rearmFailedAttempt(org.mockito.ArgumentMatchers.eq(USER_ID),
                org.mockito.ArgumentMatchers.eq(TARGET_KEY),
                org.mockito.ArgumentMatchers.eq(EVIDENCE),
                org.mockito.ArgumentMatchers.eq(token), org.mockito.ArgumentMatchers.eq(42L),
                org.mockito.ArgumentMatchers.eq("canary"),
                org.mockito.ArgumentMatchers.any(Instant.class));
    }

    @Test
    void rearmRejectsAStaleTargetBeforeMutation() {
        UUID token = UUID.randomUUID();
        when(attempts.findAttempt(USER_ID, TARGET_KEY, EVIDENCE)).thenReturn(Optional.of(
                new ComputeAttempt(USER_ID, TARGET_KEY, EVIDENCE, "FAILED", "FAILED", 1,
                        token, null, Instant.now())));
        when(targets.findForUpdate(USER_ID)).thenReturn(Optional.of(
                new Target("FRONTEND", List.of(), List.of(), Instant.now())));
        when(evidence.assemble(USER_ID)).thenReturn(
                new Assembled(EVIDENCE, mock(EvidencePayload.class), null));

        assertThatThrownBy(() -> service.rearm(
                USER_ID, TARGET_KEY, EVIDENCE, token, 42L, "canary"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("stale");
    }
}
