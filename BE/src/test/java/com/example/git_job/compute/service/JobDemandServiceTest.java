package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.CDemandSnapshot;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.client.dto.CohortResolved;
import com.example.git_job.compute.client.dto.CohortSelector;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.JobDemandResponse;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/** 최신 preview 경로와 구 C fallback이 같은 수요 selector를 사용하는지 고정한다. */
class JobDemandServiceTest {

    private static final String COHORT = "c-" + "1".repeat(64);
    private static final String DEMAND = "c-" + "2".repeat(64);

    private CComputeApi compute;
    private JobDemandService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        service = new JobDemandService(compute, mock(ComputeResultReader.class));
        when(compute.previewDemand(any())).thenReturn(marketDemand());
    }

    private CohortSelector previewSelector() {
        ArgumentCaptor<CohortSelector> captor = ArgumentCaptor.forClass(CohortSelector.class);
        verify(compute).previewDemand(captor.capture());
        return captor.getValue();
    }

    @Test
    @DisplayName("목표 직무를 주면 preview에 활성 매칭 selector를 보낸다")
    void keepsActiveMatchingWhenRoleIsGiven() {
        service.demand(7L, "BACKEND", List.of("서울"), List.of("신입"), 20);

        CohortSelector sent = previewSelector();
        assertThat(sent.purpose()).isEqualTo(CohortSelector.ACTIVE_MATCHING);
        assertThat(sent.targetRole()).isEqualTo("BACKEND");
        assertThat(sent.regions()).containsExactly("서울");
        assertThat(sent.careerLevels()).containsExactly("신입");
        assertThat(sent.sources()).isNullOrEmpty();
    }

    @Test
    @DisplayName("목표 직무가 없으면 preview에 공식 현재 시장 selector를 보낸다")
    void asksTheCurrentMarketWithoutARole() {
        service.demand(7L, null, List.of(), List.of(), 20);

        CohortSelector sent = previewSelector();
        assertThat(sent.purpose()).isEqualTo(CohortSelector.CURRENT_MARKET);
        assertThat(sent.targetRole()).isNull();
        assertThat(sent.sources()).containsExactly("JOBKOREA", "SARAMIN");
    }

    @Test
    @DisplayName("preview 한 번으로 수요를 읽고 resolve와 snapshot은 호출하지 않는다")
    void readsPreviewWithoutResolveAndSnapshotRoundTrips() {
        JobDemandResponse response = service.demand(
                7L, "BACKEND", List.of("서울"), List.of("신입"), 10);

        assertThat(response.basis().jobCount()).isEqualTo(1_621);
        assertThat(response.technologies()).hasSize(2);
        verify(compute, never()).resolveCohort(any());
        verify(compute, never()).demand(any());
    }

    @Test
    @DisplayName("시장 응답의 분모와 비율은 C 값을 다시 계산하지 않고 사용한다")
    void passesThroughMarketBasisRatiosAndRank() {
        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 20);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.READY);
        assertThat(response.basis().targetRole()).isNull();
        assertThat(response.basis().jobCount()).isEqualTo(1_621);
        assertThat(response.basis().matchingJobCount()).isEqualTo(747);
        assertThat(response.basis().asOf()).isEqualTo("2026-09-18T03:00:00Z");
        JobDemandResponse.Technology first = response.technologies().get(0);
        assertThat(first.techId()).isEqualTo("java");
        assertThat(first.rank()).isEqualTo(1);
        assertThat(first.totalCount()).isEqualTo(284);
        assertThat(first.totalRatio()).isEqualTo(0.175);
    }

    @Test
    @DisplayName("구 C에 preview 경로가 없을 때만 같은 selector로 기존 두 호출을 사용한다")
    void fallsBackOnlyWhenOldCDoesNotHavePreviewRoute() {
        when(compute.previewDemand(any())).thenThrow(new CComputeException(
                CComputeStatus.NOT_PREPARED, null, null, "old route"));
        when(compute.resolveCohort(any())).thenReturn(
                new CohortResolved(COHORT, DEMAND, Map.of(), Map.of()));
        when(compute.demand(DEMAND)).thenReturn(
                new CDemandSnapshot(DEMAND, "DEMAND", marketDemand()));

        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 10);

        assertThat(response.basis().jobCount()).isEqualTo(1_621);
        ArgumentCaptor<CohortSelector> captor = ArgumentCaptor.forClass(CohortSelector.class);
        verify(compute).resolveCohort(captor.capture());
        assertThat(captor.getValue().purpose()).isEqualTo(CohortSelector.CURRENT_MARKET);
        assertThat(captor.getValue().sources()).containsExactly("JOBKOREA", "SARAMIN");
        verify(compute).demand(DEMAND);
    }

    @Test
    @DisplayName("preview 결과가 비어 있으면 값을 만들지 않고 준비 중 상태를 준다")
    void reportsPreparingWhenPreviewHasNoDemand() {
        when(compute.previewDemand(any())).thenReturn(null);

        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 20);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(response.statusReason()).isEqualTo("COHORT_NOT_PREPARED");
        assertThat(response.technologies()).isEmpty();
    }

    private static CSnapshot.Demand marketDemand() {
        return new CSnapshot.Demand(
                "cohort-1", "READY", 1_621, 1_700, 12, 67, 0, 747,
                Map.of("purpose", "CURRENT_MARKET", "as_of", "2026-09-18T03:00:00Z"),
                List.of(
                        new CSnapshot.TechnologyDemand(
                                "java", 1, 240, 44, 0, 284, 0.148, 0.027, 0.0, 0.175),
                        new CSnapshot.TechnologyDemand(
                                "python", 2, 200, 53, 0, 253, 0.123, 0.032, 0.0, 0.156)));
    }
}
