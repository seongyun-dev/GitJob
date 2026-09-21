package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atMost;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubBranchResponse;
import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisSubmissionService.BatchSubmission;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Item;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Outcome;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Target;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 이 서비스가 지키는 것 둘.
 *
 * <p>하나는 "클라이언트가 보낸 값으로 무엇을 하지 않는가"다 — 저장소 ID, 정규 이름,
 * commit SHA, Registry 버전은 모두 서버가 정한다.</p>
 *
 * <p>다른 하나는 배치의 경계다. 한 항목의 실패가 나머지를 버리지 않고, 진행 중인 분석이
 * 있으면 GitHub을 부르기도 전에 끊으며, 그 차단이 유효시간을 넘긴 잡 때문에 영구히
 * 붙어 있지 않는다.</p>
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
                analysisJobs, analysisRequestService,
                new AnalysisRequestProperties(3, Duration.ofHours(2), Duration.ofMinutes(30), 10),
                currentRegistryVersion);

        when(accessTokenProvider.accessTokenOf(USER_ID)).thenReturn(TOKEN);
        when(analysisRequestService.hasActiveAnalysis(USER_ID)).thenReturn(false);
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                anyLong(), anyString(), any())).thenReturn(Optional.empty());
    }

    private BatchSubmission submitOne(String fullName, String branch) {
        return service.submitBatch(USER_ID, List.of(new Target(fullName, branch)), "tr_1");
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

    @SuppressWarnings("unchecked")
    private List<RepositoryAnalysisRequestPayload> capturePayloads() {
        ArgumentCaptor<List<RepositoryAnalysisRequestPayload>> captor =
                ArgumentCaptor.forClass(List.class);
        verify(analysisRequestService).enqueueBatchAuthorized(
                eq(USER_ID), anyString(), captor.capture(), any(), anyString());
        return captor.getValue();
    }

    @Test
    @DisplayName("저장소 ID·정규 이름·SHA·Registry 버전을 서버가 채운다")
    void serverFillsEverythingTheClientDidNotSend() {
        githubReturns("octocat/GitJob", 555L, false, "develop");

        BatchSubmission submission = submitOne("octocat/gitjob", "develop");

        RepositoryAnalysisRequestPayload payload = capturePayloads().get(0);
        assertEquals(555L, payload.githubRepositoryId());
        assertEquals("octocat/GitJob", payload.repositoryFullName());
        assertEquals(SHA, payload.commitSha());
        assertEquals("registry-20260908.9", payload.registryVersion());
        assertEquals(RepositoryAnalysisMode.SNAPSHOT, payload.analysisMode());
        assertTrue(payload.analysisId().startsWith("an_"));
        assertTrue(payload.analysisRepositoryId().startsWith("ar_"));
        assertTrue(submission.created());
        assertEquals(3, submission.pollAfterSeconds());
    }

    @Test
    @DisplayName("응답 항목은 클라이언트가 보낸 이름을 그대로 돌려준다")
    void itemsEchoTheRequestedName() {
        githubReturns("octocat/GitJob", 555L, false, "main");

        Item item = submitOne("octocat/gitjob", "main").items().get(0);

        // 화면은 목록에서 받은 이름으로 상태를 키잉한다. 정규 표기만 주면 매칭이 어긋난다.
        assertEquals("octocat/gitjob", item.requestedRepositoryFullName());
        assertEquals("octocat/GitJob", item.repositoryFullName());
        assertEquals(Outcome.ACCEPTED, item.outcome());
    }

    @Test
    @DisplayName("요청마다 새 분석 ID를 만든다")
    void mintsFreshIdentifiersPerRequest() {
        githubReturns("octocat/GitJob", 555L, false, "main");

        String first = submitOne("octocat/GitJob", "main").items().get(0).analysisId();
        String second = submitOne("octocat/GitJob", "main").items().get(0).analysisId();

        assertNotEquals(first, second);
    }

    @Test
    @DisplayName("진행 중인 분석이 있으면 GitHub을 부르기 전에 409로 끊는다")
    void rejectsWhenTheUserAlreadyHasAnAnalysisInFlight() {
        when(analysisRequestService.hasActiveAnalysis(USER_ID)).thenReturn(true);

        CustomException thrown = assertThrows(CustomException.class,
                () -> submitOne("octocat/GitJob", "main"));

        assertEquals(ErrorCode.ANALYSIS_BATCH_IN_PROGRESS, thrown.getErrorCode());
        // 어차피 막힐 요청이 rate limit을 쓰지 않아야 한다.
        verifyNoInteractions(githubRepositoryClient);
        verifyNoInteractions(accessTokenProvider);
    }

    @Test
    @DisplayName("차단 판정은 전적으로 유효시간을 아는 쪽에 맡긴다")
    void theBlockDecisionIsDelegatedSoTheWindowIsAppliedInOnePlace() {
        githubReturns("octocat/GitJob", 555L, false, "main");

        submitOne("octocat/GitJob", "main");

        /*
         * 유효시간을 이 서비스가 따로 계산하면 reaper·조회와 셋이 각자 판정하게 되고,
         * 그중 하나만 어긋나도 화면이 "제출 가능"이라 말한 뒤 서버가 409를 준다.
         */
        verify(analysisRequestService).hasActiveAnalysis(USER_ID);
    }

    @Test
    @DisplayName("한 저장소가 실패해도 나머지는 접수한다")
    void oneFailedRepositoryDoesNotDiscardTheRest() {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), eq("octocat"), eq("missing")))
                .thenThrow(new CustomException(ErrorCode.REPOSITORY_NOT_FOUND));
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), eq("octocat"), eq("GitJob")))
                .thenReturn(new GithubRepositoryResponse(555L, "GitJob", "octocat/GitJob",
                        false, "main", null, "Java", "2026-09-08T00:00:00Z", null, false, false,
                        new GithubRepositoryResponse.Owner("octocat", null),
                        new GithubRepositoryResponse.Permissions(false, true, true)));
        when(githubRepositoryClient.fetchBranch(eq(TOKEN), anyString(), anyString(), anyString()))
                .thenReturn(new GithubBranchResponse("main", new GithubBranchResponse.Commit(SHA),
                        false));

        BatchSubmission submission = service.submitBatch(USER_ID, List.of(
                new Target("octocat/missing", "main"),
                new Target("octocat/GitJob", "main")), "tr_1");

        assertEquals(1, submission.countOf(Outcome.FAILED));
        assertEquals(1, submission.countOf(Outcome.ACCEPTED));
        assertTrue(submission.created());
        Item failed = submission.items().get(0);
        assertEquals("octocat/missing", failed.requestedRepositoryFullName());
        // 사유를 항목에 남긴다. 하나의 오류 봉투로 접으면 사유가 여럿일 때 나머지를 잃는다.
        assertEquals(ErrorCode.REPOSITORY_NOT_FOUND, failed.error());
        assertEquals(1, capturePayloads().size());
    }

    @Test
    @DisplayName("전부 실패하면 묶음을 만들지 않고 항목별 사유만 돌려준다")
    void allFailedMeansNoBatchButStillPerItemReasons() {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), anyString(), anyString()))
                .thenThrow(new CustomException(ErrorCode.REPOSITORY_NOT_FOUND));

        BatchSubmission submission = submitOne("octocat/missing", "main");

        assertNull(submission.batchId());
        assertFalse(submission.created());
        assertEquals(1, submission.items().size());
        assertEquals(ErrorCode.REPOSITORY_NOT_FOUND, submission.items().get(0).error());
        verify(analysisRequestService, never())
                .enqueueBatchAuthorized(anyLong(), anyString(), any(), any(), anyString());
    }

    @Test
    @DisplayName("GitHub 연결이 끊긴 것은 항목이 아니라 요청 전체의 실패다")
    void tokenFailuresAbortTheWholeRequest() {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), anyString(), anyString()))
                .thenThrow(new CustomException(ErrorCode.GITHUB_TOKEN_INVALID));

        CustomException thrown = assertThrows(CustomException.class, () -> service.submitBatch(
                USER_ID,
                List.of(new Target("octocat/a", "main"), new Target("octocat/b", "main")),
                "tr_1"));

        // 저장소를 바꿔도 결과가 같고, 화면에는 "GitHub 다시 연결" 복구 경로가 떠야 한다.
        assertEquals(ErrorCode.GITHUB_TOKEN_INVALID, thrown.getErrorCode());
    }

    /**
     * 해소가 제한 병렬로 돌기 때문에 "첫 항목 이후 전부 중단"은 될 수 없다 -- 동시에
     * 떠 있는 항목들은 이미 호출을 보낸 뒤다. 보장할 수 있는 것은 <b>동시 실행 수를
     * 넘겨 두드리지 않는다</b>는 것이고, 한도를 넘긴 뒤 회복을 늦추지 않으려면 그것으로
     * 충분하다.
     */
    @Test
    @DisplayName("rate limit을 만나면 동시 실행 수를 넘겨 두드리지 않는다")
    void stopsCallingGithubOnceTheRateLimitIsHit() {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), anyString(), anyString()))
                .thenThrow(new CustomException(ErrorCode.GITHUB_RATE_LIMITED));
        List<Target> many = java.util.stream.IntStream.rangeClosed(1, 8)
                .mapToObj(index -> new Target("octocat/repo" + index, "main"))
                .toList();

        BatchSubmission submission = service.submitBatch(USER_ID, many, "tr_1");

        assertEquals(8, submission.countOf(Outcome.FAILED));
        submission.items().forEach(item ->
                assertEquals(ErrorCode.GITHUB_RATE_LIMITED, item.error()));
        verify(githubRepositoryClient,
                atMost(AnalysisSubmissionService.RESOLVE_CONCURRENCY))
                .fetchRepository(eq(TOKEN), anyString(), anyString());
    }

    @Test
    @DisplayName("이미 진행 중인 같은 저장소는 실패가 아니라 재사용이다")
    void reusesAnInProgressJobInsteadOfCreatingADuplicate() {
        githubReturns("octocat/repo", 555L, false, "main");
        AnalysisJob running = AnalysisJob.queue(
                "an_existing", USER_ID, "555", "octocat/repo", "develop", SHA, Instant.now(), null);
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                USER_ID, "555", AnalysisJob.IN_PROGRESS_STATUSES)).thenReturn(Optional.of(running));

        BatchSubmission submission = submitOne("octocat/repo", "main");

        Item item = submission.items().get(0);
        assertEquals(Outcome.REUSED, item.outcome());
        assertEquals("an_existing", item.analysisId());
        assertNull(item.error());
        assertFalse(submission.created());
        assertNull(submission.batchId());
        verify(analysisRequestService, never())
                .enqueueBatchAuthorized(anyLong(), anyString(), any(), any(), anyString());
        verifyNoInteractions(currentRegistryVersion);
    }

    /**
     * 재사용은 창 밖의 잡에서만 걸릴 수 있는데(창 안이면 게이트가 409를 낸다), 그 잡은
     * 곧 reaper 가 닫는다. 재사용해 버리면 사용자가 고른 저장소가 묶음에서 빠진 채
     * 카드만 대기 상태로 남는다. 그래서 재사용하지 않고 새로 만든다.
     */
    @Test
    @DisplayName("창을 넘긴 잡이 점유한 저장소는 재사용하지 않고 새로 만든다")
    void aStaleJobIsReplacedRatherThanReused() {
        githubReturns("octocat/repo", 555L, false, "main");
        AnalysisJob stale = AnalysisJob.queue("an_stale", USER_ID, "555", "octocat/repo",
                "develop", SHA, Instant.now().minus(Duration.ofHours(49)), null);
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                USER_ID, "555", AnalysisJob.IN_PROGRESS_STATUSES)).thenReturn(Optional.of(stale));

        BatchSubmission submission = submitOne("octocat/repo", "main");

        Item item = submission.items().get(0);
        assertEquals(Outcome.ACCEPTED, item.outcome());
        assertNotEquals("an_stale", item.analysisId());
        assertTrue(submission.created());
    }

    @Test
    @DisplayName("점유를 풀 수 있도록 그 잡의 ID를 등록 경계로 넘긴다")
    void theStaleJobIsHandedToTheTransactionSoTheIndexCanBeReleased() {
        githubReturns("octocat/repo", 555L, false, "main");
        AnalysisJob stale = AnalysisJob.queue("an_stale", USER_ID, "555", "octocat/repo",
                "develop", SHA, Instant.now().minus(Duration.ofHours(49)), null);
        when(analysisJobs.findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
                USER_ID, "555", AnalysisJob.IN_PROGRESS_STATUSES)).thenReturn(Optional.of(stale));

        submitOne("octocat/repo", "main");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<String>> stales = ArgumentCaptor.forClass(List.class);
        verify(analysisRequestService).enqueueBatchAuthorized(
                eq(USER_ID), anyString(), any(), stales.capture(), anyString());
        assertEquals(List.of("an_stale"), stales.getValue());
    }

    @Test
    @DisplayName("묶음 전체가 하나의 Registry 버전을 공유한다")
    void everyMemberOfABatchJudgesAgainstTheSameRegistry() {
        githubReturnsPerRepository();

        service.submitBatch(USER_ID, List.of(
                new Target("octocat/a", "main"),
                new Target("octocat/b", "main"),
                new Target("octocat/c", "main")), "tr_1");

        // 항목마다 읽으면 해소가 도는 동안 CURRENT 가 바뀐 배치의 절반이 다른 기준으로
        // 판정된다. 한 번만 읽는 것이 그 가능성을 없앤다.
        verify(currentRegistryVersion, times(1)).resolve();
        assertEquals(3, capturePayloads().size());
    }

    /** 저장소마다 다른 id 를 주도록. 같은 id 면 두 번째부터 중복 검사에 걸린다. */
    private void githubReturnsPerRepository() {
        when(githubRepositoryClient.fetchRepository(eq(TOKEN), anyString(), anyString()))
                .thenAnswer(call -> {
                    String name = call.getArgument(2);
                    return new GithubRepositoryResponse(name.hashCode() & 0xFFFFL, name,
                            "octocat/" + name, false, "main", null, "Java",
                            "2026-09-08T00:00:00Z", null, false, false,
                            new GithubRepositoryResponse.Owner("octocat", null),
                            new GithubRepositoryResponse.Permissions(false, true, true));
                });
        when(githubRepositoryClient.fetchBranch(eq(TOKEN), anyString(), anyString(), anyString()))
                .thenReturn(new GithubBranchResponse(
                        "main", new GithubBranchResponse.Commit(SHA), false));
    }

    @Test
    @DisplayName("아카이브된 저장소는 그 항목만 실패한다")
    void archivedRepositoryFailsAsOneItem() {
        githubReturns("octocat/archived", 777L, true, "main");

        BatchSubmission submission = submitOne("octocat/archived", "main");

        assertEquals(ErrorCode.REPOSITORY_NOT_ANALYZABLE, submission.items().get(0).error());
    }

    @Test
    @DisplayName("브랜치 이름 형식이 틀리면 GitHub을 부르지 않고 그 항목만 실패한다")
    void malformedBranchFailsBeforeAnyGithubCall() {
        BatchSubmission submission = submitOne("octocat/repo", "../../etc/passwd");

        assertEquals(ErrorCode.INVALID_REQUEST_BODY, submission.items().get(0).error());
        verifyNoInteractions(githubRepositoryClient);
    }

    @Test
    @DisplayName("상한을 넘긴 요청은 GitHub을 한 번도 부르지 않고 거절한다")
    void rejectsBatchesLargerThanTheConfiguredMaximum() {
        List<Target> tooMany = java.util.stream.IntStream.rangeClosed(1, 11)
                .mapToObj(index -> new Target("octocat/repo" + index, "main"))
                .toList();

        CustomException thrown = assertThrows(CustomException.class,
                () -> service.submitBatch(USER_ID, tooMany, "tr_1"));

        assertEquals(ErrorCode.ANALYSIS_BATCH_TOO_LARGE, thrown.getErrorCode());
        verifyNoInteractions(githubRepositoryClient);
    }

    @Test
    @DisplayName("빈 요청은 400이다")
    void emptyRequestIsRejected() {
        CustomException thrown = assertThrows(CustomException.class,
                () -> service.submitBatch(USER_ID, List.of(), "tr_1"));

        assertEquals(ErrorCode.INVALID_REQUEST_BODY, thrown.getErrorCode());
    }

    @Test
    @DisplayName("traceId가 비면 새로 만들어 요청 자체는 살린다")
    void blankTraceIdIsReplacedRatherThanRejected() {
        githubReturns("octocat/GitJob", 555L, false, "main");

        service.submitBatch(USER_ID, List.of(new Target("octocat/GitJob", "main")), "  ");

        ArgumentCaptor<String> trace = ArgumentCaptor.forClass(String.class);
        verify(analysisRequestService).enqueueBatchAuthorized(
                eq(USER_ID), anyString(), any(), any(), trace.capture());
        assertTrue(trace.getValue().startsWith("tr_"));
    }
}
