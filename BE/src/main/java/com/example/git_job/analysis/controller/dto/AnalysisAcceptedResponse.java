package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.service.AnalysisSubmissionService;

/**
 * 분석 등록 응답. 결과를 기다리지 않고 조회 경로만 돌려준다.
 *
 * @param commitSha 실제로 분석될 commit. 응답 후 브랜치가 움직여도 이 값은 바뀌지 않는다
 * @param pollAfterSec 재조회 권장 간격(초)
 */
public record AnalysisAcceptedResponse(
        String analysisId,
        String status,
        String repositoryFullName,
        String branchName,
        String commitSha,
        int pollAfterSec,
        String statusUrl
) {

    public static AnalysisAcceptedResponse from(AnalysisSubmissionService.Submission submission) {
        return new AnalysisAcceptedResponse(
                submission.analysisId(),
                submission.status(),
                submission.repositoryFullName(),
                submission.branchName(),
                submission.commitSha(),
                submission.pollAfterSeconds(),
                "/api/v1/analyses/" + submission.analysisId());
    }
}
