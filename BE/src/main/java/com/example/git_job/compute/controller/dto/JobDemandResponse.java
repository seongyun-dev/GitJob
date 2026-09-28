package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CSnapshot;
import java.util.List;

/**
 * 직무별 기술 수요 집계 (S15P21E102-279).
 *
 * <p>개인 결과가 아니다. 로그인만 확인하고 소유권 검사는 하지 않으며, C에도
 * {@code user_id} 없이 공용 Snapshot으로 조회한다.</p>
 *
 * <p>비율은 C가 준 값을 그대로 옮긴다. 건수를 분모로 다시 나누면 C의 중복 제거와 제외
 * 정책이 빠진 숫자가 나와, 같은 화면의 두 수치가 서로 맞지 않게 된다.</p>
 */
public record JobDemandResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        List<Technology> technologies
) {

    public static JobDemandResponse pending(ComputeState state, Basis basis) {
        return new JobDemandResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, List.of());
    }

    public static JobDemandResponse of(ComputeState state, Basis basis,
                                       List<CSnapshot.TechnologyDemand> technologies) {
        return new JobDemandResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis,
                technologies.stream().map(Technology::of).toList());
    }

    public record Technology(String techId, int rank, int requiredCount, int preferredCount,
            int generalCount, int totalCount, double requiredRatio, double preferredRatio,
            double generalRatio, double totalRatio) {

        static Technology of(CSnapshot.TechnologyDemand demand) {
            return new Technology(demand.techId(), demand.rank(), demand.requiredCount(),
                    demand.preferredCount(), demand.generalCount(), demand.totalCount(),
                    demand.requiredRatio(), demand.preferredRatio(), demand.generalRatio(),
                    demand.totalRatio());
        }
    }
}
