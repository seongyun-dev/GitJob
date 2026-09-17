package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeClient;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.AnalysisCompleted;
import com.example.git_job.compute.client.dto.CohortResolved;
import com.example.git_job.compute.client.dto.CohortSelector;
import com.example.git_job.compute.client.dto.EvidencePayload;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.service.UserEvidenceAssembler.Unavailable;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 분석 완료 → C 호출 → Snapshot 저장의 순서와 멱등을 고정한다 (S15P21E102-279).
 *
 * <p>여기서 지키는 인수 조건은 "재시작하거나 같은 분석 완료 이벤트가 재전달되어도 중복
 * 계산되지 않는다"이다. Kafka 재배달이 정상 경로이므로, 같은 상황에서 같은 event ID가
 * 나오지 않으면 사용자 한 명이 분석을 한 번 돌릴 때 C 계산이 여러 번 일어난다.</p>
 */
class CComputeSyncServiceTest {

    private static final long USER_ID = 7L;
    private static final String EVIDENCE_VERSION = "f".repeat(64);
    private static final String COHORT = "c-" + "1".repeat(64);
    private static final String DEMAND = "c-" + "2".repeat(64);
    private static final String RECOMMENDATION = "c-" + "3".repeat(64);

    private CComputeClient client;
    private UserEvidenceAssembler assembler;
    private UserTargetStore targets;
    private ComputeSnapshotStore snapshots;
    private CComputeSyncService service;

    @BeforeEach
    void setUp() {
        client = mock(CComputeClient.class);
        assembler = mock(UserEvidenceAssembler.class);
        targets = mock(UserTargetStore.class);
        snapshots = mock(ComputeSnapshotStore.class);
        service = new CComputeSyncService(client, assembler, targets, snapshots);

        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(assembler.assemble(USER_ID)).thenReturn(assembled());
        when(snapshots.findByEventId(any())).thenReturn(Optional.empty());
        when(snapshots.tryStartAttempt(eq(USER_ID), any(), eq(EVIDENCE_VERSION), any(), any(),
                anyInt())).thenAnswer(invocation -> Optional.of(new ComputeAttempt(
                        USER_ID, invocation.getArgument(1), EVIDENCE_VERSION, "RUNNING",
                        "COMPUTING", 1, UUID.randomUUID(), invocation.getArgument(4),
                        invocation.getArgument(3))));
        when(snapshots.save(any())).thenReturn(true);
        stubResolve(Map.of("runtime", "c/1.0"));
        stubCompleted(RECOMMENDATION);
    }

    private static Assembled assembled() {
        EvidencePayload payload = new EvidencePayload(EvidencePayload.SCHEMA_VERSION,
                String.valueOf(USER_ID), "u7-" + EVIDENCE_VERSION.substring(0, 32),
                "registry-20260911.4", UserEvidenceAssembler.LEVEL_POLICY_VERSION,
                "registry-20260911.4", "COMPLETE", List.of(), List.of(), List.of());
        return new Assembled(EVIDENCE_VERSION, payload, null);
    }

    private void stubResolve(Map<String, String> computeVersions) {
        when(client.post(eq("/internal/v1/c/job-cohorts/resolve"), any(), eq(CohortResolved.class)))
                .thenReturn(new CohortResolved(COHORT, DEMAND, Map.of(), computeVersions));
    }

    private void stubCompleted(String recommendationSnapshotId) {
        when(client.post(eq("/internal/v1/c/analyses/completed"), any(),
                eq(AnalysisCompleted.Result.class)))
                .thenReturn(new AnalysisCompleted.Result("ev-1", "COMPLETED",
                        List.of(new AnalysisCompleted.Reference("MATCHING", "c-ignored"),
                                new AnalysisCompleted.Reference("RECOMMENDATION",
                                        recommendationSnapshotId))));
    }

    @Test
    @DisplayName("목표 직무가 없으면 C를 부르지 않는다")
    void skipsWithoutTarget() {
        when(targets.find(USER_ID)).thenReturn(Optional.empty());

        assertThat(service.synchronize(USER_ID)).isEmpty();
        verify(client, never()).post(any(), any(), any());
    }

    @Test
    @DisplayName("보낼 Evidence가 없으면 C를 부르지 않는다")
    void skipsWithoutEvidence() {
        when(assembler.assemble(USER_ID))
                .thenReturn(new Assembled(null, null, Unavailable.NO_ANALYSIS));

        assertThat(service.synchronize(USER_ID)).isEmpty();
        verify(client, never()).post(any(), any(), any());
    }

    @Test
    @DisplayName("resolve로 받은 cohort와 RECOMMENDATION Snapshot을 저장한다")
    void storesResolvedPair() {
        Optional<ComputeSnapshot> stored = service.synchronize(USER_ID);

        assertThat(stored).isPresent();
        ComputeSnapshot snapshot = stored.orElseThrow();
        assertThat(snapshot.userId()).isEqualTo(USER_ID);
        assertThat(snapshot.cohortSnapshotId()).isEqualTo(COHORT);
        // 두 Snapshot은 같은 회차의 쌍이다. 하나만 쓰면 분모가 어긋난다.
        assertThat(snapshot.demandSnapshotId()).isEqualTo(DEMAND);
        assertThat(snapshot.recommendationSnapshotId()).isEqualTo(RECOMMENDATION);
        assertThat(snapshot.evidenceVersion()).isEqualTo(EVIDENCE_VERSION);
        assertThat(snapshot.targetKey()).isEqualTo("BACKEND|서울|신입");
    }

    @Test
    @DisplayName("selector에는 로그인 사용자의 저장된 목표 직무만 실린다")
    void sendsStoredSelector() {
        service.synchronize(USER_ID);

        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(client).post(eq("/internal/v1/c/job-cohorts/resolve"), body.capture(),
                eq(CohortResolved.class));
        CohortSelector selector = (CohortSelector) body.getValue();
        assertThat(selector.schemaVersion()).isEqualTo("job-cohort-resolve-selector/v1");
        assertThat(selector.targetRole()).isEqualTo("BACKEND");
        assertThat(selector.regions()).containsExactly("서울");
        assertThat(selector.careerLevels()).containsExactly("신입");
    }

    @Test
    @DisplayName("같은 event가 이미 저장돼 있으면 계산을 다시 맡기지 않는다")
    void reusesStoredResult() {
        ComputeSnapshot existing = new ComputeSnapshot(USER_ID, EVIDENCE_VERSION, COHORT, DEMAND,
                RECOMMENDATION, "ev-stored", "BACKEND|서울|신입", Instant.EPOCH);
        when(snapshots.findByEventId(any())).thenReturn(Optional.of(existing));

        assertThat(service.synchronize(USER_ID)).contains(existing);

        // resolve 는 멱등하고 값이 싸지만, 계산 전달은 하지 않아야 한다.
        verify(client, never()).post(eq("/internal/v1/c/analyses/completed"), any(), any());
        verify(snapshots, never()).save(any());
    }

    @Test
    @DisplayName("event ID는 같은 입력이면 같고 계산 버전이 바뀌면 달라진다")
    void eventIdIsDeterministic() {
        String first = CComputeSyncService.eventId(USER_ID, EVIDENCE_VERSION, COHORT,
                Map.of("runtime", "c/1.0", "registry", "registry-20260911.4"));
        String again = CComputeSyncService.eventId(USER_ID, EVIDENCE_VERSION, COHORT,
                Map.of("registry", "registry-20260911.4", "runtime", "c/1.0"));
        String afterDeploy = CComputeSyncService.eventId(USER_ID, EVIDENCE_VERSION, COHORT,
                Map.of("runtime", "c/1.1", "registry", "registry-20260911.4"));

        // Map 순서가 달라도 같아야 한다. 아니면 재시작마다 중복 계산이 생긴다.
        assertThat(first).isEqualTo(again).startsWith("ev-").hasSize(67);
        // 계산 버전이 바뀌면 같은 event 로 다시 보내지 않는다. 보내면 C 가 409 로 막는다.
        assertThat(afterDeploy).isNotEqualTo(first);
    }

    @Test
    @DisplayName("409는 한 번만 다시 시도한다")
    void retriesConflictOnce() {
        when(client.post(eq("/internal/v1/c/analyses/completed"), any(),
                eq(AnalysisCompleted.Result.class)))
                .thenThrow(new CComputeException(CComputeStatus.CONFLICT, "IDEMPOTENCY_CONFLICT",
                        null, "conflict"));

        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class);

        // 두 번째도 409 면 포기한다. 새 event ID 를 무한히 만들지 않는다.
        verify(client, times(2)).post(eq("/internal/v1/c/analyses/completed"), any(), any());
        verify(snapshots).markFailed(any(), eq("COMPUTE_IDEMPOTENCY_CONFLICT"), any());
    }

    @Test
    @DisplayName("422는 terminal failure로 저장한다")
    void persistsInvalidInputAsTerminalFailure() {
        when(client.post(eq("/internal/v1/c/analyses/completed"), any(),
                eq(AnalysisCompleted.Result.class)))
                .thenThrow(new CComputeException(CComputeStatus.INVALID_INPUT, "INVALID_INPUT",
                        null, "invalid"));

        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class);

        verify(snapshots).markFailed(any(), eq("COMPUTE_INVALID_INPUT"), any());
        verify(snapshots, never()).markRetrying(any(), any(), any(), any());
    }

    @Test
    @DisplayName("일시 오류만 next retry time과 함께 저장한다")
    void persistsTransientFailureForBoundedRetry() {
        when(client.post(eq("/internal/v1/c/job-cohorts/resolve"), any(),
                eq(CohortResolved.class)))
                .thenThrow(new CComputeException(CComputeStatus.UNAVAILABLE, null, null, "down"));

        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class);

        verify(snapshots).markRetrying(any(), eq("COMPUTE_RETRYING"), any(), any());
        verify(snapshots, never()).markFailed(any(), any(), any());
    }

    @Test
    @DisplayName("세 번째 일시 실패는 retry exhausted terminal 상태가 된다")
    void stopsAfterTheRetryBudget() {
        when(snapshots.tryStartAttempt(eq(USER_ID), any(), eq(EVIDENCE_VERSION), any(), any(),
                anyInt())).thenAnswer(invocation -> Optional.of(new ComputeAttempt(
                        USER_ID, invocation.getArgument(1), EVIDENCE_VERSION, "RUNNING",
                        "COMPUTING", 3, UUID.randomUUID(), invocation.getArgument(4),
                        invocation.getArgument(3))));
        when(client.post(eq("/internal/v1/c/job-cohorts/resolve"), any(),
                eq(CohortResolved.class)))
                .thenThrow(new CComputeException(CComputeStatus.UNAVAILABLE, null, null, "down"));

        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class);

        verify(snapshots).markFailed(any(), eq("COMPUTE_RETRY_EXHAUSTED"), any());
        verify(snapshots, never()).markRetrying(any(), any(), any(), any());
    }

    @Test
    @DisplayName("현재 identity와 다른 due attempt는 읽었던 token만 정리한다")
    void removesOnlyTheObservedObsoleteAttempt() {
        ComputeAttempt obsolete = new ComputeAttempt(USER_ID, "FRONTEND||", "e".repeat(64),
                "RETRYING", "COMPUTE_RETRYING", 1, UUID.randomUUID(), Instant.EPOCH,
                Instant.EPOCH);

        service.synchronizeDue(obsolete);

        verify(snapshots).deleteAttempt(obsolete);
        verify(snapshots).tryStartAttempt(eq(USER_ID), eq("BACKEND|서울|신입"),
                eq(EVIDENCE_VERSION), any(), any(), anyInt());
    }

    @Test
    @DisplayName("cohort와 demand 쌍이 아니면 미준비로 본다")
    void requiresBothSnapshots() {
        when(client.post(eq("/internal/v1/c/job-cohorts/resolve"), any(), eq(CohortResolved.class)))
                .thenReturn(new CohortResolved(COHORT, null, Map.of(), Map.of()));

        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class)
                .satisfies(thrown -> assertThat(((CComputeException) thrown).getStatus())
                        .isEqualTo(CComputeStatus.NOT_PREPARED));
        verify(snapshots, never()).save(any());
    }

    @Test
    @DisplayName("RECOMMENDATION Snapshot이 없으면 저장하지 않는다")
    void refusesResultWithoutRecommendation() {
        when(client.post(eq("/internal/v1/c/analyses/completed"), any(),
                eq(AnalysisCompleted.Result.class)))
                .thenReturn(new AnalysisCompleted.Result("ev-1", "COMPLETED",
                        List.of(new AnalysisCompleted.Reference("MATCHING", "c-only"))));

        // 큐에 넣었다는 응답을 완료로 받아들이면 공개 API 가 없는 Snapshot 을 조회한다.
        assertThatThrownBy(() -> service.synchronize(USER_ID))
                .isInstanceOf(CComputeException.class);
        verify(snapshots, never()).save(any());
    }

    @Test
    @DisplayName("완료 event는 사용자 단위 분석 ID와 resolve한 cohort를 싣는다")
    void sendsUserScopedEvent() {
        service.synchronize(USER_ID);

        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(client).post(eq("/internal/v1/c/analyses/completed"), body.capture(),
                eq(AnalysisCompleted.Result.class));
        AnalysisCompleted event = (AnalysisCompleted) body.getValue();

        assertThat(event.schemaVersion()).isEqualTo("c-compute-event/v1");
        assertThat(event.userId()).isEqualTo("7");
        assertThat(event.cohortSnapshotId()).isEqualTo(COHORT);
        assertThat(event.analysisId()).isEqualTo(event.evidence().analysisId());
        assertThat(event.occurredAt()).isNotNull();
        // trace_id 만 다른 재전달은 C 가 허용한다. 멱등은 event_id 가 지킨다.
        assertThat(event.traceId()).isNotBlank().isNotEqualTo(event.eventId());
    }

    @Test
    @DisplayName("동시에 두 번 저장되면 먼저 저장된 행을 쓴다")
    void survivesConcurrentInsert() {
        ComputeSnapshot winner = new ComputeSnapshot(USER_ID, EVIDENCE_VERSION, COHORT, DEMAND,
                RECOMMENDATION, "ev-winner", "BACKEND|서울|신입", Instant.EPOCH);
        when(snapshots.save(any())).thenReturn(false);
        when(snapshots.findByEventId(any()))
                .thenReturn(Optional.empty())
                .thenReturn(Optional.of(winner));

        assertThat(service.synchronize(USER_ID)).contains(winner);
        verify(assembler).assemble(anyLong());
    }
}
