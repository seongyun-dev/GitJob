package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CRelatedJobs;
import java.util.List;

/**
 * 추천 기술 학습 시 확인된 조건에 영향을 받는 공고 (화면 03) (S15P21E102-279).
 *
 * <p>영향 건수와 목록은 <b>한 응답</b>에서 나온다. 서로 다른 시점의 활성 공고를
 * 섞어 세지 않는다.</p>
 *
 * <p>v8은 {@code IMPACT} 모드의 필수·우대 조건 영향을 사용한다. 구 {@code WHAT_IF}
 * 숫자는 호환용이며 v8 응답에서는 null이다. {@code totalCount}는 선택한 영향 탭의
 * 활성 공고 수다.</p>
 */
public record WhatIfResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        String techId,
        Counts counts,
        String impactKind,
        ImpactCounts impactCounts,
        int page,
        int perPage,
        boolean hasNext,
        int totalCount,
        List<Job> items,
        List<String> dataGaps
) {

    public static WhatIfResponse pending(ComputeState state, Basis basis, String techId,
                                         String impactKind, int page, int perPage) {
        return new WhatIfResponse(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                basis, techId, null, impactKind, null, page, perPage, false, 0,
                List.of(), List.of());
    }

    public static WhatIfResponse of(ComputeState state, Basis basis, CRelatedJobs jobs,
                                    int page, int perPage) {
        List<CRelatedJobs.Job> items = jobs.items() == null ? List.of() : jobs.items();
        return new WhatIfResponse(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                basis, jobs.techId(),
                jobs.impactCounts() == null
                        ? new Counts(jobs.currentCount(), jobs.projectedCount(), jobs.increasedCount())
                        : null,
                jobs.impactKind(),
                jobs.impactCounts() == null ? null : new ImpactCounts(
                        jobs.impactCounts().requiredCount(),
                        jobs.impactCounts().preferredCount(),
                        jobs.impactCounts().affectedCount()),
                page, perPage,
                // C 는 hasNext 를 주지 않고 offset·total 만 준다. 받은 창의 끝이 전체보다
                // 앞이면 다음 쪽이 있다.
                jobs.offset() + items.size() < jobs.totalCount(),
                jobs.totalCount(),
                items.stream().map(job -> Job.of(job,
                        jobs.impactJobKinds() == null ? List.of()
                                : jobs.impactJobKinds().getOrDefault(job.jobId(), List.of())))
                        .toList(),
                jobs.dataGaps() == null ? List.of() : jobs.dataGaps());
    }

    /** 분모는 같은 COHORT의 공고 수다. 세 값이 서로 다른 Snapshot에서 오면 안 된다. */
    public record Counts(int currentCount, int projectedCount, int increasedCount) {
    }

    public record ImpactCounts(int requiredCount, int preferredCount, int affectedCount) {
    }

    public record Job(String jobId, String title, String companyName, String sourceSite,
            String sourceUrl, String region, String careerLevel, String deadline,
            boolean requiredImpact, boolean preferredImpact, String eligibility) {

        static Job of(CRelatedJobs.Job job, List<String> kinds) {
            return new Job(job.jobId(), job.title(), job.companyName(), job.sourceSite(),
                    job.sourceUrl(), job.region(), job.careerLevel(), job.deadline(),
                    kinds.contains("REQUIRED"), kinds.contains("PREFERRED"),
                    job.eligibility());
        }
    }
}
