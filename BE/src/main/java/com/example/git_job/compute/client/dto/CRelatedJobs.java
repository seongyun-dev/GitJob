package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * {@code GET .../recommendations/{id}/job-postings}의 응답 (S15P21E102-279).
 *
 * <p>{@code mode=WHAT_IF}는 <b>신규로 늘어나는 공고만</b> 준다. 현재 충족 공고와 합친
 * 목록이 아니므로 {@code items}의 길이는 {@code increasedCount}와 같은 것을 센다.</p>
 *
 * <p>증가 건수와 목록이 한 응답에서 나오는 것이 중요하다. 화면의 "+7건"과 목록을 서로
 * 다른 호출에서 읽으면, 그 사이에 새 Snapshot이 생겼을 때 둘이 어긋난다.</p>
 */
public record CRelatedJobs(
        String snapshotId,
        String calculationSnapshotId,
        String cohortId,
        /** {@code CURRENT} 또는 {@code WHAT_IF}. */
        String view,
        String techId,
        int totalCount,
        int offset,
        int limit,
        int currentCount,
        int projectedCount,
        int increasedCount,
        List<Job> items,
        List<String> dataGaps
) {

    /** 공고 모집단의 공고 한 건. 매칭 평가가 아니라 공고 자체다. */
    public record Job(
            String jobId,
            String sourceSite,
            String sourceUrl,
            String companyName,
            String title,
            String region,
            String careerLevel,
            String postedAt,
            String deadline
    ) {
    }
}
