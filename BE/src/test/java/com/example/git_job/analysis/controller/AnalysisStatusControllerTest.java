package com.example.git_job.analysis.controller;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisStatusService;
import com.example.git_job.analysis.service.AnalysisSubmissionService;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

class AnalysisStatusControllerTest {
    private static final Instant NOW = Instant.parse("2026-09-10T00:00:00Z");
    private AnalysisJobRepository jobs;
    private AnalysisSubmissionService submission;
    private AuthenticatedUser principal;
    private AnalysisJob job;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        jobs = mock(AnalysisJobRepository.class);
        submission = mock(AnalysisSubmissionService.class);
        principal = new AuthenticatedUser("42", "tester", "jti", NOW.plusSeconds(3600));
        job = AnalysisJob.queue("an_test", 42L, "123", "main", "a".repeat(40), NOW);
        when(jobs.findById("an_test")).thenReturn(Optional.of(job));
        mvc = MockMvcBuilders.standaloneSetup(new AnalysisController(submission, new AnalysisStatusService(jobs)))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new HandlerMethodArgumentResolver() {
                    public boolean supportsParameter(org.springframework.core.MethodParameter p) {
                        return p.getParameterType() == AuthenticatedUser.class;
                    }
                    public Object resolveArgument(org.springframework.core.MethodParameter p,
                            ModelAndViewContainer c, org.springframework.web.context.request.NativeWebRequest r,
                            org.springframework.web.bind.support.WebDataBinderFactory f) {
                        return principal;
                    }
                }).build();
    }

    @ParameterizedTest
    @CsvSource({"QUEUED,QUEUED,0", "RUNNING,RUNNING,0", "COLLECTING,RUNNING,0",
            "ANALYZING,RUNNING,0", "SUCCEEDED,SUCCEEDED,1", "COMPLETED,SUCCEEDED,1",
            "PARTIAL,PARTIAL_SUCCEEDED,1", "PARTIAL_SUCCEEDED,PARTIAL_SUCCEEDED,1",
            "FAILED,FAILED,1", "RATE_LIMITED,RUNNING,0", "CANCELLED,FAILED,1",
            "CANCELED,FAILED,1", "CANCEL_REQUESTED,RUNNING,0"})
    void exposesStoredProgressWithoutStartingAnotherJob(String stored, String expected, int completed) throws Exception {
        ReflectionTestUtils.setField(job, "status", stored);
        ReflectionTestUtils.setField(job, "currentStage", "MANIFEST_PARSE");
        var result = mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.analysisId").value("an_test"))
                .andExpect(jsonPath("$.data.analysisStatus").value(expected))
                .andExpect(jsonPath("$.data.currentStage").value("MANIFEST_PARSE"))
                .andExpect(jsonPath("$.data.totalCount").value(1))
                .andExpect(jsonPath("$.data.completedCount").value(completed))
                .andExpect(jsonPath("$.data.progressPercent").value(completed * 100))
                .andExpect(jsonPath("$.data.stages[0].processed").value(completed))
                .andExpect(jsonPath("$.data.repositories[0].repositoryId").value("123"));
        if (completed == 1) result.andExpect(jsonPath("$.data.pollAfterSeconds").value(org.hamcrest.Matchers.nullValue()));
        else result.andExpect(jsonPath("$.data.pollAfterSeconds").value(5));
        verify(jobs).findById("an_test");
        verifyNoMoreInteractions(jobs);
        verifyNoInteractions(submission);
    }

    @Test
    void omitsRepositoryDetailsOnRequest() throws Exception {
        mvc.perform(get("/api/v1/analyses/an_test?includeRepositories=false"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.repositories").isEmpty());
    }

    @Test
    void returnsFailureAndStoredCompletionTime() throws Exception {
        job.fail("CLONE_FAILED", NOW.plusSeconds(30));
        mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.errorCode").value("CLONE_FAILED"))
                .andExpect(jsonPath("$.data.finishedAt").value("2026-09-10T00:00:30Z"));
    }

    @Test
    void unknownAnalysisIs404() throws Exception {
        mvc.perform(get("/api/v1/analyses/missing"))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("AN-404-1"));
    }

    @Test
    void otherUsersAnalysisIs403() throws Exception {
        ReflectionTestUtils.setField(job, "userId", 99L);
        mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value("AUTH-403-1"));
    }

    @Test
    void missingPrincipalIs401BeforeLookup() throws Exception {
        principal = null;
        mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.code").value("AUTH-401-1"));
        verifyNoInteractions(jobs);
    }

    /** 상태 코드만 보면 프로젝트 응답 봉투를 벗어나도 통과한다. code까지 확인한다. */
    @Test
    void invalidBooleanIs400() throws Exception {
        mvc.perform(get("/api/v1/analyses/an_test?includeRepositories=invalid"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("G-400-2"));
    }

    /**
     * 계약은 다섯 상태만 정의한다. 저장된 값이 그 밖이면 그대로 내보내지 않는다.
     *
     * <p>{@code RATE_LIMITED}는 가상의 값이 아니라 {@code IN_PROGRESS_STATUSES}에
     * 실제로 들어 있고, 워커가 새 값을 쓰기 시작하면 오타·미지의 문자열도 같은
     * 경로로 들어온다. 이전 구현은 이것들을 통과시켜 클라이언트가 분기할 수 없는
     * 값을 받았다.</p>
     */
    @ParameterizedTest
    @CsvSource({"RATE_LIMITED,RUNNING", "CANCEL_REQUESTED,RUNNING",
            "CANCELED,FAILED", "CANCELLED,FAILED",
            "WEIRD_VALUE,FAILED", "queued,FAILED", "'',FAILED"})
    void foldsUnknownStatusIntoTheContractSet(String stored, String expected) throws Exception {
        ReflectionTestUtils.setField(job, "status", stored);
        mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.analysisStatus").value(expected));
    }

    /** 다섯 값 밖이 하나라도 새면 화면이 분기하지 못한다. 전수로 막는다. */
    @ParameterizedTest
    @CsvSource({"QUEUED", "RUNNING", "COLLECTING", "ANALYZING", "RATE_LIMITED",
            "CANCEL_REQUESTED", "SUCCEEDED", "COMPLETED", "PARTIAL", "PARTIAL_SUCCEEDED",
            "FAILED", "CANCELED", "CANCELLED", "WEIRD_VALUE", "''"})
    void neverReturnsAStatusOutsideTheContract(String stored) throws Exception {
        ReflectionTestUtils.setField(job, "status", stored);
        mvc.perform(get("/api/v1/analyses/an_test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.analysisStatus").value(
                        org.hamcrest.Matchers.in(new String[] {
                                "QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL_SUCCEEDED", "FAILED"})));
    }
}
