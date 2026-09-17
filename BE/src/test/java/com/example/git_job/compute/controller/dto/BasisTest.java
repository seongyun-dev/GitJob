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
}
