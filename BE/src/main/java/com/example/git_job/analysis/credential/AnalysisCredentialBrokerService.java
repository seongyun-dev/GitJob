package com.example.git_job.analysis.credential;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.outbox.AnalysisOutboxStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class AnalysisCredentialBrokerService {

    private static final String REQUEST_SCHEMA = "repository-analysis-credential-request/v1";
    private static final String BEARER_PREFIX = "Bearer ";
    private static final Set<String> CREDENTIAL_ACTIVE_STATUSES = Set.of(
            "QUEUED", "COLLECTING", "RUNNING", "ANALYZING", "RATE_LIMITED"
    );

    private final AnalysisJobRepository jobs;
    private final AnalysisOutboxStore outbox;
    private final GithubAccessTokenProvider accessTokens;
    private final AnalysisCredentialBrokerProperties properties;

    @Transactional(readOnly = true)
    public AnalysisCredentialResponse exchange(
            String authorization,
            AnalysisCredentialRequest request
    ) {
        authenticate(authorization);
        if (request == null || !request.hasValidShape()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        AnalysisJob job = jobs.findById(request.analysisId())
                .orElseThrow(() -> new CustomException(ErrorCode.ANALYSIS_CREDENTIAL_NOT_FOUND));

        if (!matches(job, request)
                || !outbox.containsAnalysisRepository(
                        request.analysisId(), request.analysisRepositoryId())) {
            throw new CustomException(ErrorCode.ANALYSIS_CREDENTIAL_NOT_FOUND);
        }
        // CANCEL_REQUESTED remains an in-progress status for duplicate-request
        // suppression, but it must not authorize a new credential exchange.
        if (!CREDENTIAL_ACTIVE_STATUSES.contains(job.getStatus())) {
            throw new CustomException(ErrorCode.ANALYSIS_CREDENTIAL_NOT_ACTIVE);
        }

        try {
            return AnalysisCredentialResponse.github(
                    accessTokens.accessTokenOf(job.getUserId())
            );
        } catch (CustomException error) {
            if (error.getErrorCode() == ErrorCode.GITHUB_TOKEN_INVALID) {
                throw new CustomException(ErrorCode.GITHUB_RECONNECT_REQUIRED);
            }
            throw error;
        }
    }

    private void authenticate(String authorization) {
        if (!properties.enabled() || authorization == null
                || !authorization.startsWith(BEARER_PREFIX)) {
            throw new CustomException(ErrorCode.INTERNAL_WORKER_UNAUTHORIZED);
        }
        byte[] supplied = authorization.substring(BEARER_PREFIX.length())
                .getBytes(StandardCharsets.UTF_8);
        byte[] expected = properties.serviceToken().getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(supplied, expected)) {
            throw new CustomException(ErrorCode.INTERNAL_WORKER_UNAUTHORIZED);
        }
    }

    private boolean matches(AnalysisJob job, AnalysisCredentialRequest request) {
        return REQUEST_SCHEMA.equals(request.schemaVersion())
                && Long.toString(request.githubRepositoryId()).equals(job.getRepositoryId())
                && request.repositoryFullName().equals(job.getRepositoryFullName())
                && request.commitSha().equals(job.getCommitSha());
    }
}
