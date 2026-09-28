package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
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
 * 직무별 기술 수요와 현재 시장 수요 (S15P21E102-279, -338, -334).
 *
 * <p>개인 결과가 아니다. 사용자가 고른 조건으로 공용 COHORT·DEMAND를 고르고 그 수요
 * 집계를 그대로 옮긴다. 로그인은 확인하지만 소유권 검사는 없다.</p>
 *
 * <p>목표 직무를 주면 그 직무의 활성 코호트, 주지 않으면 지금 확보한 공고 전체의 시장
 * 수요다. 두 질문은 분모가 다르므로 여기서 selector를 나눠 보낸다. 직무가 없다고 해서
 * 5개 직무 결과를 합치지는 않는다 — 합집합은 같은 공고를 여러 번 세고, 어떤 직무에도
 * 매칭되지 않은 공고를 통째로 잃는다.</p>
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
        CohortSelector selector = selector(targetRole, regions, careerLevels);
        try {
            CSnapshot.Demand demand = compute.previewDemand(selector);
            return response(target, basis, demand, limit);
        } catch (CComputeException e) {
            // 구 C에는 preview 경로가 없다. 라우트 자체가 없는 404만 기존
            // resolve+snapshot 경로로 호환하고, 계산 대기·장애는 중복 호출하지 않는다.
            if (e.getStatus() == CComputeStatus.NOT_PREPARED && e.getCode() == null) {
                return legacyDemand(userId, target, basis, selector, limit);
            }
            return JobDemandResponse.pending(reader.translate(e, userId), basis);
        }
    }

    private JobDemandResponse legacyDemand(long userId, Target target, Basis basis,
                                            CohortSelector selector, int limit) {
        try {
            CohortResolved cohort = compute.resolveCohort(selector);
            if (cohort == null || !cohort.isComplete()) {
                return JobDemandResponse.pending(
                        ComputeState.preparing("COHORT_NOT_PREPARED"), basis);
            }
            CDemandSnapshot snapshot = compute.demand(cohort.demandSnapshotId());
            return response(target, basis, snapshot == null ? null : snapshot.payload(), limit);
        } catch (CComputeException e) {
            return JobDemandResponse.pending(reader.translate(e, userId), basis);
        }
    }

    private JobDemandResponse response(Target target, Basis basis, CSnapshot.Demand demand,
                                       int limit) {
        if (demand == null || demand.technologies() == null) {
            return JobDemandResponse.pending(
                    ComputeState.preparing("COHORT_NOT_PREPARED"), basis);
        }
        List<CSnapshot.TechnologyDemand> technologies = demand.technologies().stream()
                .sorted(Comparator.comparingInt(CSnapshot.TechnologyDemand::rank))
                .limit(limit)
                .toList();
        return JobDemandResponse.of(ComputeState.ready(), Basis.of(target, demand), technologies);
    }

    /**
     * 목표 직무의 유무가 곧 질문의 종류다.
     *
     * <p>빈 문자열도 "고르지 않음"으로 읽는다. 쿼리 문자열에서 {@code targetRole=}은
     * 사용자가 값을 지운 모습이고, 그것을 직무 이름으로 C에 보내면 422가 난다.</p>
     */
    private static CohortSelector selector(String targetRole, List<String> regions,
                                           List<String> careerLevels) {
        if (targetRole == null || targetRole.isBlank()) {
            return CohortSelector.currentMarket(regions, careerLevels);
        }
        return CohortSelector.activeMatching(targetRole, regions, careerLevels);
    }
}
