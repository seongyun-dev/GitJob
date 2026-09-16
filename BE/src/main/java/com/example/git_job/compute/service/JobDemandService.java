package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.dto.CDemandSnapshot;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.client.dto.CohortResolved;
import com.example.git_job.compute.client.dto.CohortSelector;
import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.JobDemandResponse;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * 직무별 기술 수요 (S15P21E102-279).
 *
 * <p>개인 결과가 아니다. 사용자가 고른 조건으로 공용 COHORT·DEMAND를 고르고 그 수요
 * 집계를 그대로 옮긴다. 로그인은 확인하지만 소유권 검사는 없다.</p>
 *
 * <p>순위와 비율을 다시 계산하지 않는다. C가 중복 제거·품질 제외를 거쳐 만든 분모를 우리가
 * 모르기 때문에, 건수를 다시 나누면 같은 화면의 두 수치가 어긋난다.</p>
 */
@Service
public class JobDemandService {

    private final CComputeApi compute;
    private final ComputeResultReader reader;

    public JobDemandService(CComputeApi compute, ComputeResultReader reader) {
        this.compute = compute;
        this.reader = reader;
    }

    public JobDemandResponse demand(long userId, String targetRole, List<String> regions,
                                    List<String> careerLevels, int limit) {
        Target target = new Target(targetRole, regions, careerLevels, Instant.EPOCH);
        Basis basis = Basis.of(target);
        try {
            CohortResolved cohort = compute.resolveCohort(
                    CohortSelector.of(targetRole, regions, careerLevels));
            if (cohort == null || !cohort.isComplete()) {
                return JobDemandResponse.pending(
                        ComputeState.preparing("COHORT_NOT_PREPARED"), basis);
            }
            CDemandSnapshot snapshot = compute.demand(cohort.demandSnapshotId());
            CSnapshot.Demand demand = snapshot == null ? null : snapshot.payload();
            if (demand == null || demand.technologies() == null) {
                return JobDemandResponse.pending(
                        ComputeState.preparing("COHORT_NOT_PREPARED"), basis);
            }
            List<CSnapshot.TechnologyDemand> technologies = demand.technologies().stream()
                    .sorted(Comparator.comparingInt(CSnapshot.TechnologyDemand::rank))
                    .limit(limit)
                    .toList();
            return JobDemandResponse.of(ComputeState.ready(), Basis.of(target, demand),
                    technologies);
        } catch (CComputeException e) {
            // 계산 대기·미준비는 상태로, 장애는 예외로 나간다. 판단은 한곳에 모은다.
            return JobDemandResponse.pending(reader.translate(e, userId), basis);
        }
    }
}
