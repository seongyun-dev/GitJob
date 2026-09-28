package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubCommitResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.Authorship;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.CachedCommit;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.EvidenceCommitRef;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 근거 한 줄을 누가 썼는지 확정하는 경로.
 *
 * <h2>왜 이 테스트가 뒤늦게 생겼는가</h2>
 *
 * <p>이 서비스는 운영에서 한 번도 돌지 않았다. {@code ANALYSIS_ATTRIBUTE_AUTHORS}
 * 가 꺼져 있어 워커가 blame 을 하지 않았고, 그래서 근거의 {@code commit_sha} 가
 * 전부 비어 첫 줄에서 그대로 빠져나왔다. 읽는 쪽({@code TechnologyProfileStore},
 * {@code UserEvidenceAssembler})은 테스트가 있는데 <b>쓰는 쪽만 없었다</b> --
 * 스위치를 켜기 전에 덮어 둔다.</p>
 *
 * <p>GitHub 호출과 저장은 목이다. 여기서 검사할 것은 SQL 이 아니라 판정이다 --
 * 어떤 라벨을 붙이는지, 커밋을 몇 번 묻는지, 못 물었을 때 무엇을 쓰는지.</p>
 */
class EvidenceAuthorshipServiceTest {

    private static final String ANALYSIS = "an_1";
    private static final long USER_ID = 7L;
    private static final String LOGIN = "octocat";
    private static final String REPO_ID = "repo_1";
    private static final String FULL_NAME = "gitjob-example/card-service";

    private EvidenceAuthorshipStore store;
    private GithubRepositoryClient github;
    private GithubAccessTokenProvider accessTokens;
    private UserRepository users;
    private EvidenceAuthorshipService service;
    private ListAppender<ILoggingEvent> logs;

    @BeforeEach
    void setup() {
        store = mock(EvidenceAuthorshipStore.class);
        github = mock(GithubRepositoryClient.class);
        accessTokens = mock(GithubAccessTokenProvider.class);
        users = mock(UserRepository.class);
        service = new EvidenceAuthorshipService(store, github, accessTokens, users);

        // 상한에 걸렸다는 사실은 저장된 행이 아니라 로그에만 남는다.
        // 그래서 로그가 이 동작의 검사 대상이다.
        logs = new ListAppender<>();
        logs.start();
        serviceLogger().addAppender(logs);

        when(store.findCommit(anyString(), anyString())).thenReturn(Optional.empty());
        when(store.insertAll(any())).thenAnswer(call -> ((List<?>) call.getArgument(0)).size());
        when(accessTokens.accessTokenOf(anyLong())).thenReturn("gho_token");
        when(users.findById(USER_ID)).thenReturn(Optional.of(
                User.register(1L, LOGIN, "Octo Cat", null, null, "repo", "gho_token")));
    }

    @AfterEach
    void detachAppender() {
        serviceLogger().detachAppender(logs);
    }

    private static ch.qos.logback.classic.Logger serviceLogger() {
        return (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(EvidenceAuthorshipService.class);
    }

    private List<String> warnings() {
        return logs.list.stream()
                .filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }

    @Test
    @DisplayName("워커가 blame 하지 않은 분석은 GitHub 을 부르지 않는다")
    void doesNothingWhenTheWorkerAttributedNoCommits() {
        // 지금 운영이 정확히 이 상태다. 오류가 아니라 스위치가 꺼진 것이다.
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of());

        assertEquals(0, service.attribute(job()));

        verify(github, never()).fetchCommit(any(), any(), any(), any());
        verify(store, never()).insertAll(any());
    }

    @Test
    @DisplayName("본인 커밋은 SOLE_AUTHOR 로, 근거 줄 수까지 남는다")
    void labelsTheUsersOwnCommit() {
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 10, 12)));
        givenCommit("a", LOGIN);

        assertEquals(1, service.attribute(job()));

        Authorship row = captured().getFirst();
        assertEquals("SOLE_AUTHOR", row.contributionType());
        assertEquals(3, row.matchedLineCount());
        assertEquals(USER_ID, row.userId());
    }

    @Test
    @DisplayName("login 대소문자가 달라도 본인으로 본다")
    void matchesTheLoginCaseInsensitively() {
        // GitHub 의 login 은 대소문자를 보존하지만 비교는 구분하지 않는다.
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 5, 5)));
        givenCommit("a", "OctoCat");

        service.attribute(job());

        assertEquals("SOLE_AUTHOR", captured().getFirst().contributionType());
    }

    @Test
    @DisplayName("남이 쓴 커밋과 계정을 붙이지 못한 커밋을 다른 값으로 저장한다")
    void tellsAnotherAuthorApartFromAnUnlinkedCommit() {
        // 이 둘을 합치면 나중에 되살릴 수 없다. Level 판정만 보면 어차피 둘 다
        // 제외되지만, 기술 요약 계약의 authorship 은 MOSTLY_OTHERS("본인 근거가
        // 소수다")와 NOT_VERIFIED("판정 자체가 없다")를 다른 값으로 요구한다.
        when(store.evidenceWithCommits(ANALYSIS))
                .thenReturn(List.of(ref(1, "someone-else", 1, 1), ref(2, "unlinked", 2, 2)));
        givenCommit("someone-else", "teammate");
        givenCommit("unlinked", null);

        service.attribute(job());

        Map<Long, Authorship> rows = captured().stream()
                .collect(Collectors.toMap(Authorship::analysisEvidenceId, Function.identity()));
        // 물어봤더니 남이 썼다.
        assertEquals("OTHER_AUTHOR", rows.get(1L).contributionType());
        // 물어보지 못했다. 등록하지 않은 이메일로 커밋하면 본인 코드여도 여기다.
        assertEquals("UNVERIFIED", rows.get(2L).contributionType());
        // 어느 쪽이든 본인 것이 아니면 줄 수는 세지 않는다.
        assertEquals(0, rows.get(1L).matchedLineCount());
        assertEquals(0, rows.get(2L).matchedLineCount());
    }

    @Test
    @DisplayName("force push 로 사라진 커밋 하나가 나머지 근거를 버리지 않는다")
    void keepsGoingWhenOneCommitIsGone() {
        when(store.evidenceWithCommits(ANALYSIS))
                .thenReturn(List.of(ref(1, "gone", 1, 1), ref(2, "mine", 2, 4)));
        when(github.fetchCommit(anyString(), anyString(), anyString(), eq("gone")))
                .thenReturn(null);
        givenCommit("mine", LOGIN);

        assertEquals(2, service.attribute(job()));

        Map<Long, Authorship> rows = captured().stream()
                .collect(Collectors.toMap(Authorship::analysisEvidenceId, Function.identity()));
        assertEquals("UNVERIFIED", rows.get(1L).contributionType());
        assertEquals("SOLE_AUTHOR", rows.get(2L).contributionType());
    }

    @Test
    @DisplayName("같은 커밋은 근거가 몇 건이든 한 번만 묻는다")
    void asksAboutEachCommitOnce() {
        // 커밋 하나가 API 호출 하나다. 근거는 한 커밋에 수십 건씩 몰린다.
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(
                ref(1, "a", 1, 1), ref(2, "a", 2, 2), ref(3, "b", 3, 3)));
        givenCommit("a", LOGIN);
        givenCommit("b", LOGIN);

        service.attribute(job());

        verify(github, times(1)).fetchCommit(anyString(), anyString(), anyString(), eq("a"));
        verify(github, times(1)).fetchCommit(anyString(), anyString(), anyString(), eq("b"));
        // 토큰도 한 번만 꺼낸다. 첫 조회 전까지는 아예 꺼내지 않는다.
        verify(accessTokens, times(1)).accessTokenOf(USER_ID);
    }

    @Test
    @DisplayName("이미 캐시된 커밋은 GitHub 을 부르지 않는다")
    void reusesACachedCommit() {
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 1, 1)));
        when(store.findCommit(REPO_ID, "a")).thenReturn(Optional.of(
                new CachedCommit(LOGIN, "Octo Cat", null, Instant.parse("2026-09-01T00:00:00Z"))));

        service.attribute(job());

        verify(github, never()).fetchCommit(any(), any(), any(), any());
        verify(accessTokens, never()).accessTokenOf(anyLong());
        assertEquals("SOLE_AUTHOR", captured().getFirst().contributionType());
    }

    @Test
    @DisplayName("커밋 조회 상한을 넘은 근거는 미확인으로 남는다")
    void stopsLookingUpAfterTheBudget() {
        // 한 분석이 사용자의 시간당 한도를 다 쓰면 그다음 저장소 분석이 전부 막힌다.
        // 상한 자체는 타당하지만, 걸렸다는 사실이 행에 남지 않는다는 점은 알고 있어야
        // 한다 -- 그 근거들은 "남이 썼다"가 아니라 "묻지 못했다"이다.
        List<EvidenceCommitRef> refs = new ArrayList<>();
        for (int i = 0; i < 120; i++) {
            refs.add(ref(i + 1, "sha-" + i, 1, 1));
        }
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(refs);
        when(github.fetchCommit(anyString(), anyString(), anyString(), anyString()))
                .thenAnswer(call -> commit(call.getArgument(3), LOGIN));

        assertEquals(120, service.attribute(job()));

        verify(github, times(100)).fetchCommit(anyString(), anyString(), anyString(), anyString());
        List<Authorship> rows = captured();
        long attributed = rows.stream()
                .filter(row -> "SOLE_AUTHOR".equals(row.contributionType())).count();
        assertEquals(100, attributed);
        assertEquals(20, rows.size() - attributed);

        // 저장된 행에는 "묻지 못했다"가 남지 않는다. 운영자가 알 수 있는 곳은 여기뿐이다.
        List<String> warnings = warnings();
        assertEquals(1, warnings.size(), () -> "warnings=" + warnings);
        assertTrue(warnings.getFirst().contains("skipped=20"), warnings::getFirst);
        assertTrue(warnings.getFirst().contains("limit=100"), warnings::getFirst);
        assertTrue(warnings.getFirst().contains(ANALYSIS), warnings::getFirst);
    }

    @Test
    @DisplayName("상한에 걸리지 않으면 경고하지 않는다")
    void staysQuietWhenEveryCommitWasAsked() {
        // 경고가 상시로 나오면 아무도 안 본다.
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 1, 1)));
        givenCommit("a", LOGIN);

        service.attribute(job());

        assertEquals(List.of(), warnings());
    }

    @Test
    @DisplayName("저장소 이름을 모르면 판정하지 않는다")
    void skipsWhenTheRepositoryNameIsUnknown() {
        // owner/repo 로 쪼갤 수 없으면 GitHub 을 부를 수 없다. 이름 없이도 분석은
        // 성립하므로(AnalysisJob.queue) 실패가 아니라 건너뛴다.
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 1, 1)));

        assertEquals(0, service.attribute(jobWithoutFullName()));

        verify(github, never()).fetchCommit(any(), any(), any(), any());
    }

    @Test
    @DisplayName("사용자를 찾지 못하면 판정하지 않는다")
    void skipsWhenTheUserHasNoLogin() {
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 1, 1)));
        when(users.findById(USER_ID)).thenReturn(Optional.empty());

        assertEquals(0, service.attribute(job()));

        verify(github, never()).fetchCommit(any(), any(), any(), any());
    }

    @Test
    @DisplayName("새로 조회한 커밋은 캐시에 남는다")
    void cachesWhatItLookedUp() {
        when(store.evidenceWithCommits(ANALYSIS)).thenReturn(List.of(ref(1, "a", 1, 1)));
        givenCommit("a", LOGIN);

        service.attribute(job());

        verify(store).cacheCommit(eq(REPO_ID), eq("a"), eq(LOGIN), anyString(), any(), any());
    }

    // --- helpers ------------------------------------------------------------

    private List<Authorship> captured() {
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Authorship>> rows = ArgumentCaptor.forClass(List.class);
        verify(store).insertAll(rows.capture());
        List<Authorship> captured = rows.getValue();
        assertTrue(captured.stream().allMatch(row -> ANALYSIS.equals(row.analysisId())));
        return captured;
    }

    private void givenCommit(String sha, String login) {
        when(github.fetchCommit(anyString(), eq("gitjob-example"), eq("card-service"), eq(sha)))
                .thenReturn(commit(sha, login));
    }

    private static GithubCommitResponse commit(String sha, String login) {
        return new GithubCommitResponse(
                sha,
                login == null ? null : new GithubCommitResponse.Author(1L, login),
                new GithubCommitResponse.Commit(
                        new GithubCommitResponse.GitIdentity(
                                "Octo Cat", "octo@example.invalid",
                                OffsetDateTime.of(2026, 9, 1, 0, 0, 0, 0, ZoneOffset.UTC)),
                        "commit message"));
    }

    private static EvidenceCommitRef ref(long evidenceId, String sha, int start, int end) {
        return new EvidenceCommitRef(evidenceId, sha, start, end);
    }

    private static AnalysisJob job() {
        return AnalysisJob.queue(ANALYSIS, USER_ID, REPO_ID, FULL_NAME, "main",
                "818c4136ea971c21674525f9053de0d9c7ad8cfe", Instant.parse("2026-09-16T00:00:00Z"), null);
    }

    private static AnalysisJob jobWithoutFullName() {
        return AnalysisJob.queue(ANALYSIS, USER_ID, REPO_ID, null, "main",
                "818c4136ea971c21674525f9053de0d9c7ad8cfe", Instant.parse("2026-09-16T00:00:00Z"), null);
    }
}
