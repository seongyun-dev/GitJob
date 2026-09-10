package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubBranchResponse;
import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataIntegrityViolationException;

/**
 * 이 서비스의 핵심은 "클라이언트가 보낸 값으로 무엇을 하지 않는가"다.
 * 저장소 ID, 정규 이름, commit SHA, Registry 버전은 모두 서버가 정한다.
 */
class AnalysisSubmissionServiceTest {

    private static final long USER_ID = 42L;
    private static final String TOKEN = "gho_token";
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";

    private GithubRepositoryClient githubRepositoryClient;
    private GithubAccessTokenProvider accessTokenProvider;
    private AnalysisJobRepository analysisJobs;
    private AnalysisRequestService analysisRequestService;
    private CurrentRegistryVersion currentRegistryVersion;
    private AnalysisSubmissionService service;

    @BeforeEach
    void setup() {
        githubRepositoryClient = mock(GithubRepositoryClient.class);
        accessTokenProvider = mock(GithubAccessTokenProvider.class);
        analysisJobs = mock(AnalysisJobRepository.class);
        analysisRequestService = mock(AnalysisRequestService.class);
        currentRegistryVersion = mock(CurrentRegistryVersion.class);
        when(currentRegistryVersion.resolve()).thenReturn("registry-20260908.9");
        service = new AnalysisSubmissionService(githubRepositoryClient, accessTokenProvider,
                analysisJobs, analysisRequestService, new AnalysisRequestProperties(3),
                currentRegistryVersion);

        when(accessTokenProvider.accessTokenOf(USER_ID)).thenReturn(TOKEN);
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                anyLong(), anyString(), any())).thenReturn(Optional.empty());
        when(analysisRequestService.enqueueAuthorized(anyLong(), any(), anyString()))
                .thenAnswer(invocation -> RepositoryAnalysisRequestedEvent.create(
                        "ev_1", Instant.now(), invocation.getArgument(2), invocation.getArgument(1)));
    }

    private void githubReturns(String fullName, long id, boolean archived, String branchName) {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), anyString(), anyString()))
                .thenReturn(new GithubRepositoryResponse(id, fullName.split("/")[1], fullName,
                        false, "main", null, "Java", "2026-09-08T00:00:00Z", null,
                        archived, false,
                        new GithubRepositoryResponse.Owner(fullName.split("/")[0], null),
                        new GithubRepositoryResponse.Permissions(false, true, true)));
        when(githubRepositoryClient.fetchBranch(eq(TOKEN), anyString(), anyString(), anyString()))
                .thenReturn(new GithubBranchResponse(
                        branchName, new GithubBranchResponse.Commit(SHA), false));
    }

    private RepositoryAnalysisRequestPayload capturePayload() {
        var captor = ArgumentCaptor.forClass(RepositoryAnalysisRequestPayload.class);
        verify(analysisRequestService).enqueueAuthorized(eq(USER_ID), captor.capture(), anyString());
        return captor.getValue();
    }

    @Test
    @DisplayName("저장소 이름과 SHA는 GitHub 응답에서 가져오고 ID·Registry는 서버가 만든다")
    void buildsThePayloadFromGithubAndServerConfigurationOnly() {
        githubReturns("octocat/GitJob", 987654321L, false, "feature/cdc");

        var submission = service.submit(USER_ID, "octocat/GitJob", "feature/cdc", "tr_1");

        var payload = capturePayload();
        assertEquals(987654321L, payload.githubRepositoryId());
        assertEquals("octocat/GitJob", payload.repositoryFullName());
        assertEquals("feature/cdc", payload.branchName());
        assertEquals(SHA, payload.commitSha());
        // 설정이 아니라 technology_registry의 CURRENT 행에서 온 값이다.
        assertEquals("registry-20260908.9", payload.registryVersion());
        assertEquals(RepositoryAnalysisMode.SNAPSHOT, payload.analysisMode());
        assertTrue(payload.analysisId().startsWith("an_"));
        assertTrue(payload.analysisRepositoryId().startsWith("ar_"));
        assertEquals(payload.analysisId(), submission.analysisId());
        assertEquals("QUEUED", submission.status());
        assertEquals(3, submission.pollAfterSeconds());
        assertTrue(submission.created());
    }

    @Test
    @DisplayName("사용자가 다른 대소문자로 보내도 이벤트에는 GitHub의 정규 이름이 남는다")
    void usesTheCanonicalRepositoryNameFromGithub() {
        githubReturns("octocat/GitJob", 1L, false, "main");

        service.submit(USER_ID, "OCTOCAT/gitjob", "main", "tr_1");

        assertEquals("octocat/GitJob", capturePayload().repositoryFullName());
    }

    @Test
    @DisplayName("요청마다 새 분석 ID를 만든다 (재요청이 이전 분석을 덮어쓰지 않는다)")
    void generatesFreshIdentifiersForEveryRequest() {
        githubReturns("octocat/repo", 1L, false, "main");

        service.submit(USER_ID, "octocat/repo", "main", "tr_1");
        service.submit(USER_ID, "octocat/repo", "main", "tr_2");

        var captor = ArgumentCaptor.forClass(RepositoryAnalysisRequestPayload.class);
        verify(analysisRequestService, org.mockito.Mockito.times(2))
                .enqueueAuthorized(eq(USER_ID), captor.capture(), anyString());
        var first = captor.getAllValues().get(0);
        var second = captor.getAllValues().get(1);
        assertNotEquals(first.analysisId(), second.analysisId());
        assertNotEquals(first.analysisRepositoryId(), second.analysisRepositoryId());
    }

    @Test
    @DisplayName("같은 저장소 분석이 진행 중이면 새 Job을 만들지 않고 그것을 안내한다")
    void reusesAnInProgressJobInsteadOfCreatingADuplicate() {
        githubReturns("octocat/repo", 555L, false, "main");
        AnalysisJob running = AnalysisJob.queue(
                "an_existing", USER_ID, "555", "develop", SHA, Instant.now());
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                USER_ID, "555", AnalysisJob.IN_PROGRESS_STATUSES)).thenReturn(Optional.of(running));

        var submission = service.submit(USER_ID, "octocat/repo", "main", "tr_1");

        assertEquals("an_existing", submission.analysisId());
        assertEquals("develop", submission.branchName());
        assertFalse(submission.created());
        verify(analysisRequestService, never()).enqueueAuthorized(anyLong(), any(), anyString());
    }

    @Test
    @DisplayName("동시 요청이 uq_analysis_job_active에 걸리면 이긴 Job을 안내한다")
    void handsBackTheWinnerWhenTheUniqueIndexRejectsAConcurrentInsert() {
        githubReturns("octocat/repo", 555L, false, "main");
        AnalysisJob winner = AnalysisJob.queue(
                "an_winner", USER_ID, "555", "main", SHA, Instant.now());
        // 사전 검사에서는 비어 있었고, 인덱스 위반 뒤 재조회에서 상대가 보인다.
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                anyLong(), anyString(), any()))
                .thenReturn(Optional.empty(), Optional.of(winner));
        // when(...) 형태로 다시 스텁하면 @BeforeEach의 thenAnswer가 그 자리에서 실행된다.
        doThrow(new DataIntegrityViolationException("uq_analysis_job_active"))
                .when(analysisRequestService).enqueueAuthorized(anyLong(), any(), anyString());

        var submission = service.submit(USER_ID, "octocat/repo", "main", "tr_1");

        assertEquals("an_winner", submission.analysisId());
        assertFalse(submission.created());
    }

    @Test
    @DisplayName("무결성 위반인데 진행 중인 Job이 없으면 감추지 않고 그대로 던진다")
    void rethrowsWhenTheViolationWasNotTheDuplicateRace() {
        githubReturns("octocat/repo", 555L, false, "main");
        var violation = new DataIntegrityViolationException("some other constraint");
        doThrow(violation).when(analysisRequestService)
                .enqueueAuthorized(anyLong(), any(), anyString());

        var thrown = assertThrows(DataIntegrityViolationException.class,
                () -> service.submit(USER_ID, "octocat/repo", "main", "tr_1"));

        assertSame(violation, thrown);
    }

    @Test
    @DisplayName("아카이브 저장소는 권한 오류가 아니라 저장소 상태 오류로 거절한다")
    void refusesArchivedRepositories() {
        githubReturns("octocat/repo", 1L, true, "main");

        var failure = assertThrows(CustomException.class,
                () -> service.submit(USER_ID, "octocat/repo", "main", "tr_1"));

        assertEquals(ErrorCode.REPOSITORY_NOT_ANALYZABLE, failure.getErrorCode());
        assertNotEquals(ErrorCode.REPOSITORY_ACCESS_DENIED, failure.getErrorCode());
        verify(analysisRequestService, never()).enqueueAuthorized(anyLong(), any(), anyString());
    }

    @Test
    @DisplayName("형식이 어긋난 입력은 GitHub을 호출하기 전에 끊는다")
    void validatesInputBeforeSpendingAGithubCall() {
        var failure = assertThrows(CustomException.class,
                () -> service.submit(USER_ID, "octocat/repo", "../../etc", "tr_1"));

        assertEquals(ErrorCode.INVALID_REQUEST_BODY, failure.getErrorCode());
        verifyNoInteractions(githubRepositoryClient);
        verifyNoInteractions(accessTokenProvider);
    }

    @Test
    @DisplayName("traceId가 비어도 이벤트 계약을 깨지 않고 요청을 살린다")
    void substitutesACorrelationIdWhenTheFilterLeftNone() {
        githubReturns("octocat/repo", 1L, false, "main");

        service.submit(USER_ID, "octocat/repo", "main", null);

        var captor = ArgumentCaptor.forClass(String.class);
        verify(analysisRequestService).enqueueAuthorized(eq(USER_ID), any(), captor.capture());
        assertTrue(captor.getValue().startsWith("tr_"));
    }
}
