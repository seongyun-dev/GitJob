package com.example.git_job.analysis.service;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubBranchResponse;
import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.domain.RepositoryCoordinate;
import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

/**
 * 사용자가 고른 저장소·브랜치를 분석 요청으로 바꾼다 (B-FN-002).
 *
 * <p>{@link AnalysisRequestService}가 요구하는 선행 조건을 여기서 갖춘다. 즉 GitHub
 * 권한 확인, 브랜치 존재 확인과 SHA 확정, 서버가 만드는 ID·Registry 버전이다.
 * 클라이언트가 보낸 값 중 실제로 쓰는 것은 저장소 이름과 브랜치 이름뿐이고,
 * 나머지는 모두 GitHub 응답이나 서버가 정한다.</p>
 *
 * <p>GitHub 호출은 트랜잭션 밖에서 끝낸다. 외부 왕복 두 번을 트랜잭션 안에 넣으면
 * 그동안 DB 커넥션을 붙잡고 있게 된다.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisSubmissionService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisSubmissionService.class);

    private final GithubRepositoryClient githubRepositoryClient;
    private final GithubAccessTokenProvider accessTokenProvider;
    private final AnalysisJobRepository analysisJobs;
    private final AnalysisRequestService analysisRequestService;
    private final AnalysisRequestProperties properties;
    private final CurrentRegistryVersion currentRegistryVersion;

    public Submission submit(long userId, String repositoryFullName, String branchName, String traceId) {
        var coordinate = RepositoryCoordinate.of(repositoryFullName, branchName);
        String accessToken = accessTokenProvider.accessTokenOf(userId);

        // 이 호출이 성공한다는 것이 곧 사용자가 저장소에 접근할 수 있다는 증거다.
        // 권한이 없으면 GitHub이 404를 주고 REPOSITORY_NOT_FOUND로 바뀐다.
        GithubRepositoryResponse repository = githubRepositoryClient.fetchRepository(
                accessToken, coordinate.owner(), coordinate.repository());
        if (!repository.analyzable()) {
            throw new CustomException(ErrorCode.REPOSITORY_NOT_ANALYZABLE);
        }

        GithubBranchResponse branch = githubRepositoryClient.fetchBranch(
                accessToken, coordinate.owner(), coordinate.repository(), coordinate.branch());

        String repositoryId = Long.toString(repository.id());
        var existing = analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                userId, repositoryId, AnalysisJob.IN_PROGRESS_STATUSES);
        if (existing.isPresent()) {
            // 명세: 같은 사용자에게 같은 저장소 분석이 진행 중이면 중복 Job을 만들지 않는다.
            // 오류로 돌려주면 화면이 실패 처리를 해야 하므로, 진행 중인 Job을 그대로 안내한다.
            AnalysisJob job = existing.get();
            log.info("Reusing in-progress analysis: analysisId={}, repositoryId={}",
                    job.getAnalysisId(), repositoryId);
            return new Submission(job.getAnalysisId(), job.getStatus(), repository.fullName(),
                    job.getBranchName(), job.getCommitSha(), properties.pollAfterSeconds(), false);
        }

        // 저장소 이름은 GitHub이 준 정규 표기를 쓴다. 사용자가 대소문자를 다르게 보내거나
        // 이름이 바뀐 저장소를 옛 이름으로 보내도 이벤트에는 실제 이름이 남아야 한다.
        var payload = new RepositoryAnalysisRequestPayload(
                "an_" + newId(),
                "ar_" + newId(),
                repository.id(),
                repository.fullName(),
                branch.name(),
                branch.commitSha(),
                RepositoryAnalysisMode.SNAPSHOT,
                currentRegistryVersion.resolve());

        // 이벤트 계약은 traceId를 필수로 요구한다. 필터가 항상 채우지만, 비어 있을 때
        // 계약 위반으로 500을 내는 대신 새 값을 만들어 요청 자체는 살린다.
        String correlationId = traceId == null || traceId.isBlank() ? "tr_" + newId() : traceId;
        try {
            var event = analysisRequestService.enqueueAuthorized(userId, payload, correlationId);
            log.info("Analysis enqueued: analysisId={}, repositoryId={}, branch={}, eventId={}",
                    payload.analysisId(), repositoryId, branch.name(), event.eventId());
            return new Submission(payload.analysisId(), AnalysisJob.STATUS_QUEUED,
                    payload.repositoryFullName(), payload.branchName(), payload.commitSha(),
                    properties.pollAfterSeconds(), true);
        } catch (DataIntegrityViolationException concurrent) {
            return reuseConcurrentWinner(userId, repositoryId, repository.fullName(), concurrent);
        }
    }

    /**
     * The check above and the insert are separate statements, so two near-simultaneous requests
     * can both pass the check. The uq_analysis_job_active index decides that race, and this is
     * the loser's path.
     *
     * <p>The winning row is guaranteed to be visible here. A unique index does not report a
     * violation while the other transaction is still open -- it blocks -- so by the time this
     * exception arrives, that transaction has committed.</p>
     *
     * <p>Empty means something else violated integrity, or the winner finished within
     * milliseconds. Neither should be hidden behind a "reused an existing job" answer.</p>
     */
    private Submission reuseConcurrentWinner(long userId, String repositoryId,
            String repositoryFullName, DataIntegrityViolationException cause) {
        AnalysisJob winner = analysisJobs
                .findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                        userId, repositoryId, AnalysisJob.IN_PROGRESS_STATUSES)
                .orElseThrow(() -> cause);
        log.info("Concurrent request lost the duplicate race, reusing: analysisId={}, repositoryId={}",
                winner.getAnalysisId(), repositoryId);
        return new Submission(winner.getAnalysisId(), winner.getStatus(), repositoryFullName,
                winner.getBranchName(), winner.getCommitSha(), properties.pollAfterSeconds(), false);
    }

    private String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * @param created 새로 등록했으면 true, 진행 중이던 Job을 그대로 돌려줬으면 false.
     *                컨트롤러가 202와 200을 가르는 근거다
     */
    public record Submission(
            String analysisId,
            String status,
            String repositoryFullName,
            String branchName,
            String commitSha,
            int pollAfterSeconds,
            boolean created
    ) {
    }
}
