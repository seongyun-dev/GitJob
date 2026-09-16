package com.example.git_job.analysis.credential;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AnalysisCredentialBrokerControllerTest {

    private static final String BODY = """
            {
              "schema_version":"repository-analysis-credential-request/v1",
              "analysis_id":"an_1",
              "analysis_repository_id":"ar_1",
              "github_repository_id":123,
              "repository_full_name":"octocat/private",
              "commit_sha":"0123456789abcdef0123456789abcdef01234567"
            }
            """;

    private AnalysisCredentialBrokerService service;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = mock(AnalysisCredentialBrokerService.class);
        mvc = MockMvcBuilders.standaloneSetup(
                        new AnalysisCredentialBrokerController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void returnsTheProjectEnvelopeAndSnakeCaseCredentialFields() throws Exception {
        when(service.exchange(
                org.mockito.ArgumentMatchers.eq("Bearer service-token"),
                org.mockito.ArgumentMatchers.any(AnalysisCredentialRequest.class)))
                .thenReturn(AnalysisCredentialResponse.github("github-token"));

        mvc.perform(post("/internal/v1/repository-analysis/credentials")
                        .header("Authorization", "Bearer service-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.data.schema_version")
                        .value("repository-analysis-credential-response/v1"))
                .andExpect(jsonPath("$.data.credential_type")
                        .value("GITHUB_OAUTH_ACCESS_TOKEN"))
                .andExpect(jsonPath("$.data.access_token").value("github-token"));
    }

    @Test
    void keepsWorkerAuthenticationFailuresInTheErrorEnvelope() throws Exception {
        when(service.exchange(
                org.mockito.ArgumentMatchers.isNull(),
                org.mockito.ArgumentMatchers.any(AnalysisCredentialRequest.class)))
                .thenThrow(new CustomException(ErrorCode.INTERNAL_WORKER_UNAUTHORIZED));

        mvc.perform(post("/internal/v1/repository-analysis/credentials")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INTERNAL-401-1"));
    }
}
