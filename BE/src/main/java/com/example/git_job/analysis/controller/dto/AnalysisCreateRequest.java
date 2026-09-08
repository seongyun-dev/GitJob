package com.example.git_job.analysis.controller.dto;

/**
 * 분석 요청 본문. 사용자가 고른 저장소와 브랜치만 받는다.
 *
 * <p>analysisId, commitSha, Registry 버전은 담지 않는다. 클라이언트가 보낸 값을 쓰면
 * 권한 밖 저장소나 임의의 commit을 분석시킬 수 있으므로 서버가 GitHub에 물어 채운다.
 * 형식 검증은 {@code RepositoryCoordinate}가 담당한다.</p>
 *
 * @param repositoryFullName {@code owner/repo}
 * @param branchName 분석할 브랜치. 서버가 이 브랜치의 현재 tip commit으로 고정한다
 */
public record AnalysisCreateRequest(String repositoryFullName, String branchName) {
}
