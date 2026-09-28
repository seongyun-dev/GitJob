package com.example.git_job.compute.controller;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.JobDemandResponse;
import com.example.git_job.compute.service.JobDemandService;
import com.example.git_job.compute.service.TrendService;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * 같은 URI가 두 질문에 답한다 (S15P21E102-338).
 *
 * <p>{@code targetRole}이 있으면 그 직무의 활성 수요, 없으면 현재 시장 전체다. 새 경로를
 * 만들지 않은 이유는 응답이 같은 모양이기 때문이다 — 경로가 둘이면 FE도 상태 분기도
 * 두 벌이 된다.</p>
 *
 * <p>여기서 고정하는 것은 HTTP 표면뿐이다. 어느 모집단을 고르는지는 service의 몫이고,
 * 이 테스트는 직무가 그대로 전달되는지와 없을 때 {@code null}이 되는지만 본다.</p>
 */
class MarketControllerTest {

    private static final long USER_ID = 7L;

    private JobDemandService demands;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        demands = mock(JobDemandService.class);
        when(demands.demand(anyLong(), any(), any(), any(), anyInt()))
                .thenReturn(marketResponse());
        mvc = MockMvcBuilders.standaloneSetup(
                        new MarketController(demands, mock(TrendService.class)))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    private static JobDemandResponse marketResponse() {
        Basis basis = new Basis(null, List.of(), List.of(), "2026-09-18T03:00:00Z",
                1_621, 1_700, 12, 67, 0, 747);
        return JobDemandResponse.of(ComputeState.ready(), basis, List.of());
    }

    @Test
    @DisplayName("목표 직무를 주면 그대로 전달한다")
    void forwardsTheRequestedRole() throws Exception {
        mvc.perform(get("/api/v1/job-demands").param("targetRole", "BACKEND"))
                .andExpect(status().isOk());

        verify(demands).demand(eq(USER_ID), eq("BACKEND"), any(), any(), anyInt());
    }

    @Test
    @DisplayName("목표 직무 없이도 호출할 수 있고 직무는 null로 간다")
    void allowsTheRequestWithoutARole() throws Exception {
        mvc.perform(get("/api/v1/job-demands").param("limit", "20"))
                .andExpect(status().isOk());

        verify(demands).demand(eq(USER_ID), isNull(), any(), any(), eq(20));
    }

    @Test
    @DisplayName("기준 직무가 비어 있어도 응답 모양은 그대로다")
    void keepsTheResponseShapeWithoutARole() throws Exception {
        mvc.perform(get("/api/v1/job-demands"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.dataStatus").value("READY"))
                // 키는 남긴다. 빼면 FE의 기존 DTO가 필드를 잃는다.
                .andExpect(jsonPath("$.data.basis.targetRole").value(nullValue()))
                .andExpect(jsonPath("$.data.basis.jobCount").value(1_621))
                .andExpect(jsonPath("$.data.basis.matchingJobCount").value(747))
                .andExpect(jsonPath("$.data.technologies").isArray());
    }

    private static final class PrincipalResolver implements HandlerMethodArgumentResolver {

        @Override
        public boolean supportsParameter(MethodParameter parameter) {
            return parameter.getParameterType() == AuthenticatedUser.class;
        }

        @Override
        public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer container,
                                      NativeWebRequest request, WebDataBinderFactory factory) {
            return new AuthenticatedUser(String.valueOf(USER_ID), "tester", "jti",
                    Instant.now().plusSeconds(3600));
        }
    }
}
