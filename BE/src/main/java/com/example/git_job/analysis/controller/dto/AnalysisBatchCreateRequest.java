package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.service.AnalysisSubmissionService.Target;
import java.util.List;

/**
 * 분석 요청 본문. 고른 저장소 전부를 한 번에 받는다.
 *
 * <h2>구 본문도 함께 받는다</h2>
 *
 * <p>{@code repositories}가 없고 {@code repositoryFullName}이 있으면 저장소 하나짜리
 * 배치로 읽는다. 배포는 BE가 먼저 올라가므로, 그 사이 구 화면이 보내는
 * {@code {repositoryFullName, branchName}} 본문이 맞지 않으면 <b>배포와 배포 사이에
 * 분석 요청이 전부 실패한다.</b></p>
 *
 * <p>화면 배포가 끝나면 다음 MR에서 두 필드를 지운다. 그때까지만 있는 호환 계층이다.</p>
 *
 * @param repositories 새 본문. 항목 형태는 구 단건 본문과 같아서 화면이 바꿔야 하는 것은
 *                     감싸는 배열뿐이다
 */
public record AnalysisBatchCreateRequest(
        List<AnalysisCreateRequest> repositories,
        @Deprecated String repositoryFullName,
        @Deprecated String branchName
) {

    /** 어느 형태로 왔든 대상 목록 하나로 만든다. 둘 다 비면 빈 목록이고 호출부가 400을 준다. */
    public List<Target> targets() {
        if (repositories != null && !repositories.isEmpty()) {
            return repositories.stream()
                    .map(item -> new Target(item.repositoryFullName(), item.branchName()))
                    .toList();
        }
        if (repositoryFullName != null) {
            return List.of(new Target(repositoryFullName, branchName));
        }
        return List.of();
    }
}
