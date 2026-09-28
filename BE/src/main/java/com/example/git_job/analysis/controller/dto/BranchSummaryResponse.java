package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.client.dto.GithubBranchResponse;

/**
 * 브랜치 선택 화면용 응답.
 *
 * @param commitSha 조회 시점의 tip. 분석 요청 시 서버가 다시 확정하므로 표시용이다
 */
public record BranchSummaryResponse(String name, String commitSha, boolean isProtected) {

    public static BranchSummaryResponse from(GithubBranchResponse branch) {
        return new BranchSummaryResponse(
                branch.name(), branch.commitSha(), Boolean.TRUE.equals(branch.isProtected()));
    }
}
