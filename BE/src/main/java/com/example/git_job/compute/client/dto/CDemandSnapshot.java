package com.example.git_job.compute.client.dto;

/**
 * 공용 수요 Snapshot ({@code job-demand-snapshot/v1}) (S15P21E102-279).
 *
 * <p>{@link CSnapshot}과 나눈 이유는 {@code payload}의 종류가 다르기 때문이다. 같은
 * 경로가 {@code kind}에 따라 다른 본문을 주므로, 하나의 타입으로 받으면 어느 쪽 필드가
 * 비어 있는지 호출부가 매번 확인해야 한다.</p>
 *
 * <p>비율은 C가 준 값을 그대로 옮긴다. 분자와 분모로 다시 나누면 C의 중복 제거·제외
 * 정책이 빠진 숫자가 나온다.</p>
 */
public record CDemandSnapshot(String snapshotId, String kind, CSnapshot.Demand payload) {
}
