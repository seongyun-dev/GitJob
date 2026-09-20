package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.RecommendationResponse;
import com.example.git_job.compute.controller.dto.SkillGapResponse;
import com.example.git_job.compute.service.ComputeResultReader.Computed;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * Skill Gap과 다음 학습 기술 (S15P21E102-279).
 *
 * <p>둘이 한 서비스인 이유는 둘 다 같은 RECOMMENDATION Snapshot 하나에서 나오기
 * 때문이다. C가 한 계산에서 Gap·추천·What-if를 함께 저장하므로 두 화면의 숫자가 서로
 * 맞는다. 각각 다른 Snapshot을 읽으면 "부족 기술 9개"와 "추천 후보 3개"가 다른 기준 위에
 * 서게 된다.</p>
 */
@Service
public class SkillGapService {

    private final CComputeApi compute;
    private final ComputeResultReader reader;
    private final ComputeRetryScheduler scheduler;

    public SkillGapService(CComputeApi compute, ComputeResultReader reader) {
        this(compute, reader, null);
    }

    @Autowired
    public SkillGapService(CComputeApi compute, ComputeResultReader reader,
                           ComputeRetryScheduler scheduler) {
        this.compute = compute;
        this.reader = reader;
        this.scheduler = scheduler;
    }

    public SkillGapResponse skillGap(long userId) {
        Computed<CSnapshot> computed = read(userId);
        if (!computed.hasValue()) {
            return SkillGapResponse.pending(computed.state(), Basis.of(computed.target()));
        }
        CSnapshot.Recommendation recommendation = computed.value().payload();
        boolean hasGapRows = recommendation.gap() != null
                && recommendation.gap().technologies() != null
                && !recommendation.gap().technologies().isEmpty();
        ComputeState state = "INSUFFICIENT_EVIDENCE".equals(recommendation.status())
                && hasGapRows
                ? ComputeState.partial("PARTIAL_SKILL_GAP_EVIDENCE")
                : ComputeState.ofRecommendation(recommendation.status());
        state = staleState(userId, computed.value(), state);
        return SkillGapResponse.of(state,
                Basis.of(computed.target(), recommendation.demand()), recommendation);
    }

    public RecommendationResponse recommendations(long userId) {
        Computed<CSnapshot> computed = read(userId);
        if (!computed.hasValue()) {
            return RecommendationResponse.pending(computed.state(), Basis.of(computed.target()));
        }
        CSnapshot.Recommendation recommendation = computed.value().payload();
        ComputeState state = staleState(userId, computed.value(),
                ComputeState.ofRecommendation(recommendation.status()));
        return RecommendationResponse.of(state,
                Basis.of(computed.target(), recommendation.demand()), recommendation);
    }

    private Computed<CSnapshot> read(long userId) {
        return reader.read(userId, snapshot ->
                compute.recommendation(snapshot.recommendationSnapshotId(), userId));
    }

    private ComputeState staleState(long userId, CSnapshot snapshot, ComputeState current) {
        if (!"STALE".equals(snapshot.resultStatus())) {
            return current;
        }
        if (scheduler != null) {
            scheduler.requestInitialSync(userId);
        }
        return ComputeState.partial("STALE_RESULT_RECOMPUTING");
    }
}
