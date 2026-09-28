package com.example.git_job.compute.controller.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class BasisTest {

    @Test
    @DisplayName("수요 분모와 입력·비교 후보 공고 수를 서로 다른 기준으로 보존한다")
    void preservesDemandPopulationFunnel() {
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-1", "READY", 13,
                1_744, 0, 1_452, 279, 253,
                Map.of("target_role", "BACKEND", "as_of", "2026-09-15T22:30:04Z"),
                List.of());

        Basis basis = Basis.of(
                new Target("BACKEND", List.of(), List.of(), Instant.EPOCH), demand);

        assertThat(basis.jobCount()).isEqualTo(13);
        assertThat(basis.inputJobCount()).isEqualTo(1_744);
        assertThat(basis.matchingJobCount()).isEqualTo(253);
        assertThat(basis.excludedJobCount()).isEqualTo(1_452);
        assertThat(basis.reviewJobCount()).isEqualTo(279);
    }

    @Test
    @DisplayName("시장 수요는 직무가 없고, 없다고 해서 분모까지 잃지 않는다")
    void keepsTheMarketDenominatorWithoutARole() {
        // CURRENT_MARKET criteria 에는 target_role 자체가 없다. fallback 도 null 이므로
        // 기준 직무는 비지만, 나머지 기준은 그대로 표시할 수 있어야 한다.
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-market", "READY", 1_621,
                1_700, 12, 67, 0, 747,
                Map.of("purpose", "CURRENT_MARKET", "as_of", "2026-09-18T03:00:00Z"),
                List.of());

        Basis basis = Basis.of(
                new Target(null, List.of(), List.of(), Instant.EPOCH), demand);

        assertThat(basis.targetRole()).isNull();
        assertThat(basis.asOf()).isEqualTo("2026-09-18T03:00:00Z");
        assertThat(basis.jobCount()).isEqualTo(1_621);
        assertThat(basis.matchingJobCount()).isEqualTo(747);
    }
}
