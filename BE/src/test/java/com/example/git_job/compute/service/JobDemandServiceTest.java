package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
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

/**
 * 목표 직무가 없는 요청은 시장 전체를 묻는 것이다 (S15P21E102-338).
 *
 * <p>직무를 받으면 그 직무의 활성 코호트, 받지 않으면 지금 확보한 공고 전체의 수요다.
 * 두 질문은 분모가 다르므로 어느 쪽인지가 요청에 드러나야 한다 — C에 보내는 selector의
 * {@code purpose}가 그 자리다.</p>
 *
 * <p>시장 모집단은 selector의 {@code sources}로 명시한다. 생략하면 C는 전체 출처를
 * 뜻하는 다른 범위로 읽고, 그 범위는 공식 수치와 분모가 다르다.</p>
 */
class JobDemandServiceTest {

    private static final String COHORT = "c-" + "1".repeat(64);
    private static final String DEMAND = "c-" + "2".repeat(64);

    private CComputeApi compute;
    private JobDemandService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        service = new JobDemandService(compute, mock(ComputeResultReader.class));
        when(compute.resolveCohort(any())).thenReturn(
                new CohortResolved(COHORT, DEMAND, Map.of(), Map.of()));
        when(compute.demand(anyString())).thenReturn(marketSnapshot());
    }

    private static CDemandSnapshot marketSnapshot() {
        return new CDemandSnapshot(DEMAND, "DEMAND", new CSnapshot.Demand(
                "cohort-1", "READY", 1_621, 1_700, 12, 67, 0, 747,
                Map.of("purpose", "CURRENT_MARKET", "as_of", "2026-09-18T03:00:00Z"),
                List.of(
                        new CSnapshot.TechnologyDemand("java", 1, 240, 44, 0, 284,
                                0.148, 0.027, 0.0, 0.175),
                        new CSnapshot.TechnologyDemand("python", 2, 200, 53, 0, 253,
                                0.123, 0.032, 0.0, 0.156))));
    }

    private CohortSelector sentSelector() {
        ArgumentCaptor<CohortSelector> captor = ArgumentCaptor.forClass(CohortSelector.class);
        verify(compute).resolveCohort(captor.capture());
        return captor.getValue();
    }

    @Test
    @DisplayName("목표 직무를 주면 기존 활성 매칭 selector를 그대로 보낸다")
    void keepsActiveMatchingWhenRoleIsGiven() {
        service.demand(7L, "BACKEND", List.of("서울"), List.of("신입"), 20);

        CohortSelector sent = sentSelector();
        assertThat(sent.purpose()).isEqualTo(CohortSelector.ACTIVE_MATCHING);
        assertThat(sent.targetRole()).isEqualTo("BACKEND");
        assertThat(sent.regions()).containsExactly("서울");
        assertThat(sent.careerLevels()).containsExactly("신입");
    }

    @Test
    @DisplayName("목표 직무가 없으면 현재 시장을 묻는다")
    void asksTheCurrentMarketWithoutARole() {
        service.demand(7L, null, List.of(), List.of(), 20);

        CohortSelector sent = sentSelector();
        assertThat(sent.purpose()).isEqualTo(CohortSelector.CURRENT_MARKET);
        assertThat(sent.targetRole()).isNull();
    }

    @Test
    @DisplayName("시장 모집단은 공식 출처를 명시해서 보낸다")
    void namesTheOfficialMarketSources() {
        service.demand(7L, null, List.of(), List.of(), 20);

        assertThat(sentSelector().sources()).containsExactly("JOBKOREA", "SARAMIN");
    }

    @Test
    @DisplayName("활성 매칭은 출처를 좁히지 않는다")
    void doesNotNarrowActiveMatchingSources() {
        service.demand(7L, "BACKEND", List.of(), List.of(), 20);

        assertThat(sentSelector().sources()).isNullOrEmpty();
    }

    @Test
    @DisplayName("시장 응답의 기준 직무는 비어 있고 분모는 C의 것이다")
    void reportsTheMarketBasisWithoutARole() {
        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 20);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.READY);
        assertThat(response.basis().targetRole()).isNull();
        assertThat(response.basis().jobCount()).isEqualTo(1_621);
        assertThat(response.basis().matchingJobCount()).isEqualTo(747);
        assertThat(response.basis().asOf()).isEqualTo("2026-09-18T03:00:00Z");
    }

    @Test
    @DisplayName("비율과 순위를 다시 계산하지 않고 C 값을 그대로 옮긴다")
    void passesThroughRatiosAndRank() {
        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 20);

        JobDemandResponse.Technology first = response.technologies().get(0);
        assertThat(first.techId()).isEqualTo("java");
        assertThat(first.rank()).isEqualTo(1);
        assertThat(first.totalCount()).isEqualTo(284);
        // 284/1621 = 0.1752...  C가 준 0.175 를 다시 나눠 덮어쓰면 안 된다.
        assertThat(first.totalRatio()).isEqualTo(0.175);
    }

    @Test
    @DisplayName("계산이 준비되지 않으면 값이 아니라 대기 상태를 준다")
    void reportsPreparingWhenTheMarketCohortIsNotReady() {
        when(compute.resolveCohort(any())).thenReturn(
                new CohortResolved(null, null, Map.of(), Map.of()));

        JobDemandResponse response = service.demand(7L, null, List.of(), List.of(), 20);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(response.statusReason()).isEqualTo("COHORT_NOT_PREPARED");
        assertThat(response.technologies()).isEmpty();
        assertThat(response.basis().targetRole()).isNull();
    }
}
