package com.example.git_job.compute.client.dto;

import java.util.List;
import java.util.Map;

/**
 * {@code GET .../recommendations/{id}/job-postings}의 응답 (S15P21E102-279).
 *
 * <p>현행 {@code mode=IMPACT}는 새로 맞는 확인된 기술 조건을 가진 공고를 준다.
 * 구 {@code WHAT_IF}의 전체 충족 증가 목록은 저장 결과 호환용이다.</p>
 *
 * <p>증가 건수와 목록이 한 응답에서 나오는 것이 중요하다. 화면의 "+7건"과 목록을 서로
 * 다른 호출에서 읽으면, 그 사이에 새 Snapshot이 생겼을 때 둘이 어긋난다.</p>
 */
public record CRelatedJobs(
        String snapshotId,
        String resultId,
        String resultStatus,
        Boolean recomputeRequired,
        String calculationSnapshotId,
        String cohortId,
        /** {@code CURRENT}, 구 {@code WHAT_IF}, 또는 {@code IMPACT}. */
        String view,
        String techId,
        int totalCount,
        int offset,
        int limit,
        Integer currentCount,
        Integer projectedCount,
        Integer increasedCount,
        List<Job> items,
        List<String> dataGaps,
        String impactKind,
        ImpactCounts impactCounts,
        Map<String, List<String>> impactJobKinds
) {

    public CRelatedJobs(String snapshotId, String resultId, String resultStatus,
            Boolean recomputeRequired, String calculationSnapshotId, String cohortId,
            String view, String techId, int totalCount, int offset, int limit,
            int currentCount, int projectedCount, int increasedCount, List<Job> items,
            List<String> dataGaps) {
        this(snapshotId, resultId, resultStatus, recomputeRequired,
                calculationSnapshotId, cohortId, view, techId, totalCount, offset,
                limit, currentCount, projectedCount, increasedCount, items, dataGaps,
                null, null, null);
    }

    /** 구 C 응답을 만드는 테스트와 교차 배포 호환용 생성자. */
    public CRelatedJobs(String snapshotId, String calculationSnapshotId, String cohortId,
            String view, String techId, int totalCount, int offset, int limit,
            int currentCount, int projectedCount, int increasedCount, List<Job> items,
            List<String> dataGaps) {
        this(snapshotId, null, "LEGACY", false, calculationSnapshotId, cohortId, view,
                techId, totalCount, offset, limit, currentCount, projectedCount,
                increasedCount, items, dataGaps, null, null, null);
    }

    public record ImpactCounts(int requiredCount, int preferredCount, int affectedCount) {
    }

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
            String deadline,
            String eligibility
    ) {
        public Job(String jobId, String sourceSite, String sourceUrl,
                String companyName, String title, String region, String careerLevel,
                String postedAt, String deadline) {
            this(jobId, sourceSite, sourceUrl, companyName, title, region,
                    careerLevel, postedAt, deadline, null);
        }
    }
}
