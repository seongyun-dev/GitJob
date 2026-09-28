package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CRelatedJobs;
import com.example.git_job.compute.controller.dto.WhatIfResponse;
import com.example.git_job.compute.service.UserEvidenceAssembler.Unavailable;
import com.example.git_job.compute.support.ComputeTestSupport;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 조건 영향 건수와 공고 목록이 한 결과에서 나오는지 고정한다 (S15P21E102-279).
 *
 * <p>활성 공고 필터가 바뀌어도 카드·상세의 기준을 섞지 않고, 상세 건수와 목록은
 * 한 호출에서 받아 같은 시점을 사용한다.</p>
 */
class WhatIfServiceTest {

    private static final long USER_ID = 7L;
    private static final String RECOMMENDATION = "c-3";

    private CComputeApi compute;
    private WhatIfService service;
    private ComputeResultReader resultReader;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        UserTargetStore targets = mock(UserTargetStore.class);
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString(),
                eq(ComputeSnapshotStore.CURRENT_COMPUTE_CONTRACT_VERSION))).thenReturn(Optional.of(
                new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2", RECOMMENDATION,
                        "ev-1", "BACKEND|서울|신입", Instant.EPOCH)));
        resultReader = reader(targets, snapshots);
        service = new WhatIfService(compute, resultReader);
    }

    private static CRelatedJobs page(int offset, int itemCount, int totalCount) {
        List<CRelatedJobs.Job> items = java.util.stream.IntStream.range(0, itemCount)
                .mapToObj(index -> new CRelatedJobs.Job("job-" + index, "saramin",
                        "https://example.test/" + index, "회사", "백엔드", "서울", "신입",
                        "2026-09-01T00:00:00Z", "2026-09-26T14:59:59Z"))
                .toList();
        return new CRelatedJobs(RECOMMENDATION, null, "READY", false, "calc-1",
                "cohort-1", "IMPACT", "kafka", totalCount, offset, 20,
                0, 0, 0, items, List.of(), "ALL",
                new CRelatedJobs.ImpactCounts(totalCount, 0, totalCount),
                Map.of("job-0", List.of("REQUIRED", "PREFERRED")));
    }

    @Test
    @DisplayName("조건 영향 건수와 목록이 한 호출에서 나온다")
    void countsAndItemsComeFromOneCall() {
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(0, 7, 7));

        WhatIfResponse response = service.whatIf(USER_ID, "kafka", 1, 20);

        assertThat(response.impactCounts().affectedCount()).isEqualTo(7);
        assertThat(response.counts()).isNull();
        assertThat(response.items().getFirst().requiredImpact()).isTrue();
        assertThat(response.items().getFirst().preferredImpact()).isTrue();
        assertThat(response.items()).hasSize(7);
        assertThat(response.totalCount()).isEqualTo(7);
        // C 를 한 번만 부른다. 숫자와 목록을 따로 부르면 어긋날 수 있다.
        verify(compute).relatedJobs(RECOMMENDATION, USER_ID, "IMPACT", "kafka", "ALL", 0, 20);
    }

    @Test
    @DisplayName("필수 영향 탭과 페이지를 C의 같은 IMPACT 요청에 전달한다")
    void forwardsImpactKindAndPage() {
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyString(),
                anyInt(), anyInt())).thenReturn(page(20, 1, 21));

        service.whatIf(USER_ID, "kafka", "REQUIRED", 2, 20);

        verify(compute).relatedJobs(RECOMMENDATION, USER_ID, "IMPACT", "kafka",
                "REQUIRED", 1, 20);
    }

    @Test
    @DisplayName("구 계산 결과가 남아 있으면 IMPACT를 호출하지 않고 재계산을 기다린다")
    void waitsForV8BeforeImpactRequest() {
        UserTargetStore targets = mock(UserTargetStore.class);
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.of(
                new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2",
                        RECOMMENDATION, "ev-1", "BACKEND|서울|신입",
                        "active-matching/job-demand-v4+recommendation-v7", Instant.EPOCH)));
        when(snapshots.findAttempt(anyLong(), anyString(), anyString()))
                .thenReturn(Optional.empty());
        WhatIfService rolling = new WhatIfService(compute, reader(targets, snapshots));

        WhatIfResponse response = rolling.whatIf(USER_ID, "kafka", 1, 20);

        assertThat(response.dataStatus()).isEqualTo("PREPARING");
        assertThat(response.statusReason()).isEqualTo("COMPUTE_PENDING");
        assertThat(response.impactCounts()).isNull();
        when(snapshots.findAttempt(anyLong(), anyString(), anyString())).thenReturn(Optional.of(
                new ComputeAttempt(USER_ID, "BACKEND|서울|신입", "f".repeat(64),
                        "FAILED", "COMPUTE_INVALID_INPUT", 1,
                        java.util.UUID.randomUUID(), null, Instant.EPOCH)));
        assertThat(rolling.whatIf(USER_ID, "kafka", 1, 20).dataStatus()).isEqualTo("FAILED");
        verify(compute, never()).relatedJobs(anyString(), anyLong(), anyString(),
                anyString(), anyString(), anyInt(), anyInt());
    }

    @Test
    @DisplayName("stale What-if는 활성 목록을 제공하면서 비동기 재계산을 요청한다")
    void staleResultRequestsAsyncRecompute() {
        CRelatedJobs current = page(0, 1, 1);
        CRelatedJobs stale = new CRelatedJobs(current.snapshotId(), "ur-1", "STALE", true,
                current.calculationSnapshotId(), current.cohortId(), current.view(),
                current.techId(), current.totalCount(), current.offset(), current.limit(),
                current.currentCount(), current.projectedCount(), current.increasedCount(),
                current.items(), current.dataGaps(), current.impactKind(),
                current.impactCounts(), current.impactJobKinds());
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(stale);
        ComputeRetryScheduler scheduler = mock(ComputeRetryScheduler.class);
        WhatIfService staleService = new WhatIfService(compute, resultReader, scheduler);

        WhatIfResponse response = staleService.whatIf(USER_ID, "kafka", 1, 20);

        assertThat(response.dataStatus()).isEqualTo("PARTIAL");
        assertThat(response.statusReason()).isEqualTo("STALE_RESULT_RECOMPUTING");
        verify(scheduler).requestInitialSync(USER_ID);
    }

    @Test
    @DisplayName("hasNext는 받은 창의 끝과 전체 수로 판단한다")
    void computesHasNextFromWindow() {
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(0, 20, 45));
        assertThat(service.whatIf(USER_ID, "kafka", 1, 20).hasNext()).isTrue();

        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(40, 5, 45));
        assertThat(service.whatIf(USER_ID, "kafka", 3, 20).hasNext()).isFalse();
    }

    @Test
    @DisplayName("결과가 없으면 0이 아니라 상태로 알린다")
    void reportsPendingInsteadOfZero() {
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        UserTargetStore targets = mock(UserTargetStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of(), List.of(), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());
        UserEvidenceAssembler assembler = mock(UserEvidenceAssembler.class);
        when(assembler.assemble(anyLong()))
                .thenReturn(ComputeTestSupport.unavailable(Unavailable.NO_ANALYSIS));
        WhatIfService pending = new WhatIfService(compute,
                ComputeTestSupport.reader(targets, snapshots, assembler,
                        mock(CComputeSyncService.class)));

        WhatIfResponse response = pending.whatIf(USER_ID, "kafka", 1, 20);

        // 건수 0은 새로 맞는 조건이 없다는 의미다. 여기서는 아직 계산한 적이 없다.
        assertThat(response.counts()).isNull();
        assertThat(response.dataStatus()).isEqualTo("NO_DATA");
    }
}
