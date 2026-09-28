package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.service.AnalysisSubmissionService.BatchSubmission;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Item;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Outcome;
import java.util.List;

/**
 * 배치 등록 응답. 결과를 기다리지 않고 조회 경로만 돌려준다.
 *
 * <h2>항목 목록은 언제나 내려간다</h2>
 *
 * <p>하나도 접수되지 않았을 때도 오류 봉투로 접지 않는다. {@code ErrorResponse}는 code와
 * message 한 쌍뿐이라, 세 저장소가 서로 다른 이유로 실패하면 사용자가 그 사유를 가장
 * 필요로 하는 순간에 버리게 된다. 화면은 이미 저장소 카드마다 실패 배지를 그린다.</p>
 *
 * <p>대신 HTTP 상태로 가른다 -- 새로 만든 것이 있으면 202, 없으면 200이다. 오류 봉투는
 * 배치 단위 사유(차단 409, 형식 400, GitHub 연결 401/424)에만 쓴다.</p>
 *
 * @param pollAfterSeconds 진행 중인 것이 하나도 없으면 {@code null}. 화면이 폴링을 멈추는
 *                         유일한 신호가 이 값이라, 조회 응답과 같은 규약을 쓴다
 * @param statusUrl 이 배치의 진행을 읽을 곳. 개별 분석이 아니라 묶음을 가리킨다
 */
public record AnalysisBatchAcceptedResponse(
        String batchId,
        int totalCount,
        int acceptedCount,
        int reusedCount,
        int failedCount,
        Integer pollAfterSeconds,
        String statusUrl,
        List<ItemResponse> items
) {

    /**
     * @param requestedRepositoryFullName 클라이언트가 보낸 이름 그대로. 서버는 GitHub 정규
     *                                    표기로 바꾸지만 화면은 목록에서 받은 이름으로
     *                                    상태를 키잉하므로 원래 이름이 함께 있어야 한다
     * @param outcome {@code ACCEPTED} · {@code REUSED} · {@code FAILED}
     * @param message 실패 사유 문장. 코드만 주면 화면이 모르는 코드를 전부 "요청을 처리할
     *                수 없습니다."로 뭉갠다
     */
    public record ItemResponse(
            String requestedRepositoryFullName,
            String outcome,
            String analysisId,
            String status,
            String repositoryFullName,
            String branchName,
            String commitSha,
            String statusUrl,
            String errorCode,
            String message
    ) {
    }

    public static AnalysisBatchAcceptedResponse from(BatchSubmission submission) {
        boolean anyPending = submission.countOf(Outcome.ACCEPTED) > 0
                || submission.countOf(Outcome.REUSED) > 0;
        return new AnalysisBatchAcceptedResponse(
                submission.batchId(),
                submission.items().size(),
                (int) submission.countOf(Outcome.ACCEPTED),
                (int) submission.countOf(Outcome.REUSED),
                (int) submission.countOf(Outcome.FAILED),
                anyPending ? submission.pollAfterSeconds() : null,
                "/api/v1/me/analyses/latest-batch",
                submission.items().stream().map(AnalysisBatchAcceptedResponse::item).toList());
    }

    private static ItemResponse item(Item item) {
        return new ItemResponse(
                item.requestedRepositoryFullName(),
                item.outcome().name(),
                item.analysisId(),
                item.status(),
                item.repositoryFullName(),
                item.branchName(),
                item.commitSha(),
                item.analysisId() == null ? null : "/api/v1/analyses/" + item.analysisId(),
                item.error() == null ? null : item.error().getCode(),
                item.error() == null ? null : item.error().getMessage());
    }
}
