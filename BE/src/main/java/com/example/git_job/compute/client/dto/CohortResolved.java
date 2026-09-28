package com.example.git_job.compute.client.dto;

import java.util.Map;

/**
 * {@code job-cohorts/resolve}의 성공 응답 (S15P21E102-279).
 *
 * <p>두 Snapshot ID는 같은 완료 event와 stream에서 원자적으로 저장된 쌍이다. 하나만
 * 골라 쓰거나 서로 다른 회차의 것을 섞으면 추천 수치의 분모와 공고 목록의 분모가
 * 달라진다.</p>
 *
 * <p>{@code criteria}는 C가 정규화한 실제 조건이다. 우리가 보낸 selector가 아니라 이쪽을
 * 화면의 "비교 기준"으로 표시해야 한다 — {@code as_of}와 정규화된 직무 이름이 여기에만
 * 있다.</p>
 *
 * <p>{@code computeVersions}는 Registry·런타임 버전이다. 완료 event ID의 재료로 쓰는데,
 * 그래야 배포로 버전이 바뀐 뒤 같은 event를 다시 보내 409를 받는 일이 없다.</p>
 */
public record CohortResolved(
        String cohortSnapshotId,
        String demandSnapshotId,
        Map<String, Object> criteria,
        Map<String, String> computeVersions
) {

    public boolean isComplete() {
        return cohortSnapshotId != null && !cohortSnapshotId.isBlank()
                && demandSnapshotId != null && !demandSnapshotId.isBlank();
    }
}
