package com.example.git_job.analysis.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.analysis.service.AnalysisStatusService;
import com.example.git_job.analysis.service.AnalysisSubmissionService;
import com.example.git_job.analysis.service.AnalysisSubmissionService.BatchSubmission;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Item;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Outcome;
import com.example.git_job.analysis.service.AnalysisSubmissionService.Target;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * {@code POST /api/v1/analyses}의 계약. 이 경로에는 그동안 MockMvc 커버리지가 없었다.
 */
class AnalysisBatchControllerTest {

    private static final Instant NOW = Instant.parse("2026-09-20T00:00:00Z");
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";

    private AnalysisSubmissionService submission;
    private AuthenticatedUser principal;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        submission = mock(AnalysisSubmissionService.class);
        principal = new AuthenticatedUser("42", "tester", "jti", NOW.plusSeconds(3600));
        mvc = MockMvcBuilders
                .standaloneSetup(new AnalysisController(submission,
                        new AnalysisStatusService(mock(
                                com.example.git_job.analysis.repository.AnalysisJobRepository.class))))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new HandlerMethodArgumentResolver() {
                    @Override
                    public boolean supportsParameter(org.springframework.core.MethodParameter p) {
                        return p.getParameterType() == AuthenticatedUser.class;
                    }

                    @Override
                    public Object resolveArgument(org.springframework.core.MethodParameter p,
                            ModelAndViewContainer c,
                            org.springframework.web.context.request.NativeWebRequest r,
                            org.springframework.web.bind.support.WebDataBinderFactory f) {
                        return principal;
                    }
                }).build();
    }

    private static Item accepted(String requested, String analysisId) {
        return new Item(requested, Outcome.ACCEPTED, analysisId, "QUEUED",
                requested, "main", SHA, null);
    }

    private static Item failed(String requested, ErrorCode error) {
        return new Item(requested, Outcome.FAILED, null, null, null, null, null, error);
    }

    @Test
    @DisplayName("하나라도 새로 만들면 202와 묶음 ID를 준다")
    void acceptedBatchIs202() throws Exception {
        when(submission.submitBatch(anyLong(), any(), any())).thenReturn(new BatchSubmission(
                "ab_1", List.of(accepted("octocat/a", "an_1"), accepted("octocat/b", "an_2")), 2));

        mvc.perform(post("/api/v1/analyses")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"repositories":[
                                  {"repositoryFullName":"octocat/a","branchName":"main"},
                                  {"repositoryFullName":"octocat/b","branchName":"main"}]}"""))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.data.batchId").value("ab_1"))
                .andExpect(jsonPath("$.data.totalCount").value(2))
                .andExpect(jsonPath("$.data.acceptedCount").value(2))
                .andExpect(jsonPath("$.data.pollAfterSeconds").value(2))
                .andExpect(jsonPath("$.data.statusUrl").value("/api/v1/me/analyses/latest-batch"))
                .andExpect(jsonPath("$.data.items[0].outcome").value("ACCEPTED"))
                .andExpect(jsonPath("$.data.items[0].statusUrl").value("/api/v1/analyses/an_1"));
    }

    @Test
    @DisplayName("고른 저장소 전부가 한 번의 호출로 넘어간다")
    void everySelectedRepositoryTravelsInOneCall() throws Exception {
        when(submission.submitBatch(anyLong(), any(), any()))
                .thenReturn(new BatchSubmission("ab_1", List.of(accepted("octocat/a", "an_1")), 2));

        mvc.perform(post("/api/v1/analyses")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {"repositories":[
                          {"repositoryFullName":"octocat/a","branchName":"main"},
                          {"repositoryFullName":"octocat/b","branchName":"develop"}]}"""));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Target>> targets = ArgumentCaptor.forClass(List.class);
        verify(submission).submitBatch(anyLong(), targets.capture(), any());
        assertEqualsTargets(targets.getValue());
    }

    private static void assertEqualsTargets(List<Target> targets) {
        org.junit.jupiter.api.Assertions.assertEquals(
                List.of(new Target("octocat/a", "main"), new Target("octocat/b", "develop")),
                targets);
    }

    @Test
    @DisplayName("전부 실패해도 항목별 사유를 200 본문으로 돌려준다")
    void nothingCreatedIs200WithPerItemReasons() throws Exception {
        when(submission.submitBatch(anyLong(), any(), any())).thenReturn(new BatchSubmission(
                null,
                List.of(failed("octocat/a", ErrorCode.REPOSITORY_NOT_FOUND),
                        failed("octocat/b", ErrorCode.REPOSITORY_NOT_ANALYZABLE)),
                2));

        mvc.perform(post("/api/v1/analyses")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"repositories":[
                                  {"repositoryFullName":"octocat/a","branchName":"main"},
                                  {"repositoryFullName":"octocat/b","branchName":"main"}]}"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batchId").doesNotExist())
                .andExpect(jsonPath("$.data.failedCount").value(2))
                .andExpect(jsonPath("$.data.pollAfterSeconds").doesNotExist())
                // 사유가 둘이라 오류 봉투 하나로는 표현할 수 없다.
                .andExpect(jsonPath("$.data.items[0].errorCode").value("REPO-404-1"))
                .andExpect(jsonPath("$.data.items[1].errorCode").value("REPO-409-1"))
                .andExpect(jsonPath("$.data.items[0].message").isNotEmpty());
    }

    @Test
    @DisplayName("진행 중인 분석이 있으면 409 AN-409-1이다")
    void blockedSubmissionIs409() throws Exception {
        when(submission.submitBatch(anyLong(), any(), any()))
                .thenThrow(new CustomException(ErrorCode.ANALYSIS_BATCH_IN_PROGRESS));

        mvc.perform(post("/api/v1/analyses")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"repositories":[
                                  {"repositoryFullName":"octocat/a","branchName":"main"}]}"""))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("AN-409-1"));
    }

    @Test
    @DisplayName("구 화면의 단건 본문도 저장소 하나짜리 배치로 받는다")
    void stillAcceptsTheSingleRepositoryBodyDuringRollout() throws Exception {
        when(submission.submitBatch(anyLong(), any(), any()))
                .thenReturn(new BatchSubmission("ab_1", List.of(accepted("octocat/a", "an_1")), 2));

        mvc.perform(post("/api/v1/analyses")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"repositoryFullName":"octocat/a","branchName":"main"}"""))
                .andExpect(status().isAccepted());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Target>> targets = ArgumentCaptor.forClass(List.class);
        // MDC 가 비어 traceId 는 null 로 온다. anyString() 은 null 을 받지 않는다.
        verify(submission).submitBatch(anyLong(), targets.capture(), any());
        org.junit.jupiter.api.Assertions.assertEquals(
                List.of(new Target("octocat/a", "main")), targets.getValue());
    }
}
