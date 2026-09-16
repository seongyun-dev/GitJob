package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CRelatedJobs;
import java.util.List;

/**
 * 추천 기술을 채웠을 때의 변화와 신규 부합 공고 (화면 03) (S15P21E102-279).
 *
 * <p>증가 건수와 목록이 <b>한 응답</b>에서 나온다. 인수 조건이 "What-if 증가 건수와 신규
 * 부합 공고 목록이 동일한 결과를 사용할 것"이고, 두 호출로 나누면 그 사이에 새 Snapshot이
 * 생겼을 때 숫자와 목록이 어긋난다.</p>
 *
 * <p>C의 {@code WHAT_IF} 모드는 <b>새로 늘어나는 공고만</b> 준다. 현재 충족 공고를 포함한
 * 목록이 아니므로 {@code totalCount}는 {@code increasedCount}와 같은 것을 센다.</p>
 */
public record WhatIfResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        String techId,
        Counts counts,
        int page,
        int perPage,
        boolean hasNext,
        int totalCount,
        List<Job> items,
        List<String> dataGaps
) {

    public static WhatIfResponse pending(ComputeState state, Basis basis, String techId,
                                         int page, int perPage) {
        return new WhatIfResponse(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                basis, techId, null, page, perPage, false, 0, List.of(), List.of());
    }

    public static WhatIfResponse of(ComputeState state, Basis basis, CRelatedJobs jobs,
                                    int page, int perPage) {
        List<CRelatedJobs.Job> items = jobs.items() == null ? List.of() : jobs.items();
        return new WhatIfResponse(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                basis, jobs.techId(),
                new Counts(jobs.currentCount(), jobs.projectedCount(), jobs.increasedCount()),
                page, perPage,
                // C 는 hasNext 를 주지 않고 offset·total 만 준다. 받은 창의 끝이 전체보다
                // 앞이면 다음 쪽이 있다.
                jobs.offset() + items.size() < jobs.totalCount(),
                jobs.totalCount(),
                items.stream().map(Job::of).toList(),
                jobs.dataGaps() == null ? List.of() : jobs.dataGaps());
    }

    /** 분모는 같은 COHORT의 공고 수다. 세 값이 서로 다른 Snapshot에서 오면 안 된다. */
    public record Counts(int currentCount, int projectedCount, int increasedCount) {
    }

    public record Job(String jobId, String title, String companyName, String sourceSite,
            String sourceUrl, String region, String careerLevel, String deadline) {

        static Job of(CRelatedJobs.Job job) {
            return new Job(job.jobId(), job.title(), job.companyName(), job.sourceSite(),
                    job.sourceUrl(), job.region(), job.careerLevel(), job.deadline());
        }
    }
}
