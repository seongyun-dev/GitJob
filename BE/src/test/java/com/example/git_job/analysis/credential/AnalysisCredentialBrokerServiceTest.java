package com.example.git_job.analysis.credential;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.outbox.AnalysisOutboxStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AnalysisCredentialBrokerServiceTest {

    private static final String AUTHORIZATION = "Bearer worker-service-token";
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";

    @Mock
    private AnalysisJobRepository jobs;
    @Mock
    private AnalysisOutboxStore outbox;
    @Mock
    private GithubAccessTokenProvider accessTokens;

    private AnalysisCredentialBrokerService service;
    private AnalysisCredentialRequest request;
    private AnalysisJob job;

    @BeforeEach
    void setUp() {
        service = new AnalysisCredentialBrokerService(
                jobs,
                outbox,
                accessTokens,
                new AnalysisCredentialBrokerProperties(true, "worker-service-token")
        );
        request = new AnalysisCredentialRequest(
                "repository-analysis-credential-request/v1",
                "an_1",
                "ar_1",
                123456789L,
                "octocat/private",
                SHA
        );
        job = AnalysisJob.queue(
                "an_1", 42L, "123456789", "octocat/private", "main", SHA, Instant.now()
        );
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));
        when(outbox.containsAnalysisRepository("an_1", "ar_1")).thenReturn(true);
    }

    @Test
    void returnsOnlyTheCredentialForTheExactActiveRequestTuple() {
        when(accessTokens.accessTokenOf(42L)).thenReturn("github-user-token");

        assertThat(service.exchange(AUTHORIZATION, request).accessToken())
                .isEqualTo("github-user-token");
    }

    @Test
    void rejectsAnInvalidWorkerTokenBeforeLookingUpTheAnalysis() {
        assertThatThrownBy(() -> service.exchange("Bearer wrong", request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.INTERNAL_WORKER_UNAUTHORIZED));

        verify(jobs, never()).findById("an_1");
    }

    @Test
    void rejectsEveryRequestWhenTheBrokerFeatureIsDisabled() {
        service = new AnalysisCredentialBrokerService(
                jobs,
                outbox,
                accessTokens,
                new AnalysisCredentialBrokerProperties(false, "")
        );

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.INTERNAL_WORKER_UNAUTHORIZED));

        verify(jobs, never()).findById("an_1");
    }

    @Test
    void rejectsARepositoryOrCommitMismatchWithoutReadingTheUserToken() {
        var mismatched = new AnalysisCredentialRequest(
                request.schemaVersion(), request.analysisId(), request.analysisRepositoryId(),
                request.githubRepositoryId(), request.repositoryFullName(), "f".repeat(40)
        );

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, mismatched))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.ANALYSIS_CREDENTIAL_NOT_FOUND));

        verify(accessTokens, never()).accessTokenOf(42L);
    }

    @Test
    void rejectsAnAnalysisRepositoryIdThatWasNotInTheOutbox() {
        when(outbox.containsAnalysisRepository("an_1", "ar_1")).thenReturn(false);

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.ANALYSIS_CREDENTIAL_NOT_FOUND));
    }

    @Test
    void rejectsATerminalAnalysisBeforeReadingTheUserToken() {
        job.succeed(Instant.now());

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.ANALYSIS_CREDENTIAL_NOT_ACTIVE));

        verify(accessTokens, never()).accessTokenOf(42L);
    }

    @Test
    void rejectsACancelRequestedAnalysisBeforeReadingTheUserToken() {
        ReflectionTestUtils.setField(job, "status", "CANCEL_REQUESTED");

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.ANALYSIS_CREDENTIAL_NOT_ACTIVE));

        verify(accessTokens, never()).accessTokenOf(42L);
    }

    @Test
    void mapsAMissingGithubConnectionToTheWorkerReconnectContract() {
        when(accessTokens.accessTokenOf(42L))
                .thenThrow(new CustomException(ErrorCode.GITHUB_TOKEN_INVALID));

        assertThatThrownBy(() -> service.exchange(AUTHORIZATION, request))
                .isInstanceOf(CustomException.class)
                .satisfies(error -> assertThat(((CustomException) error).getErrorCode())
                        .isEqualTo(ErrorCode.GITHUB_RECONNECT_REQUIRED));
    }
}
