package com.example.git_job.compute.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.query.UserEvidenceStore;
import com.example.git_job.compute.service.CComputeSyncService;
import com.example.git_job.compute.service.ComputeResultReader;
import com.example.git_job.compute.service.ComputeRetryScheduler;
import com.example.git_job.compute.service.JobMatchService;
import com.example.git_job.compute.service.SkillGapService;
import com.example.git_job.compute.service.TargetService;
import com.example.git_job.compute.service.WhatIfService;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * HTTP 표면을 고정한다 (S15P21E102-279).
 *
 * <p>확인하는 것은 셋이다. URI와 봉투가 FE와 합의한 모양인지, 사용자 ID가 <b>요청이 아니라
 * 세션</b>에서만 오는지, 그리고 목표 직무가 없을 때 오류 코드가 화면을 CTA로 보내는지.</p>
 *
 * <p>Snapshot ID가 응답에 없는 것도 여기서 확인한다. 내려보내면 FE가 그것을 다시 보내는
 * 경로가 생기고, 그 경로는 곧 남의 Snapshot ID를 넣어 보는 시도가 된다.</p>
 */
class MeMatchingControllerTest {

    private static final long USER_ID = 7L;
    private static final String RECOMMENDATION = "c-" + "3".repeat(64);

    private CComputeApi compute;
    private UserTargetStore targets;
    private ComputeSnapshotStore snapshots;
    private CComputeSyncService sync;
    private ComputeRetryScheduler scheduler;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        targets = mock(UserTargetStore.class);
        snapshots = mock(ComputeSnapshotStore.class);
        sync = mock(CComputeSyncService.class);
        scheduler = mock(ComputeRetryScheduler.class);
        UserEvidenceStore evidence = mock(UserEvidenceStore.class);

        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.of(
                new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2", RECOMMENDATION,
                        "ev-1", "BACKEND|서울|신입", Instant.EPOCH)));
        when(compute.recommendation(anyString(), anyLong())).thenReturn(recommendation());

        ComputeResultReader reader = reader(targets, snapshots);
        mvc = MockMvcBuilders.standaloneSetup(new MeMatchingController(
                        new TargetService(targets, scheduler),
                        new JobMatchService(compute, reader),
                        new SkillGapService(compute, reader),
                        new WhatIfService(compute, reader)))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    private static CSnapshot recommendation() {
        CSnapshot.Gap gap = new CSnapshot.Gap("technology-gap/v2", List.of(), List.of(
                new CSnapshot.GapTechnology("kafka", "UNKNOWN", List.of(), List.of())), List.of());
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-1", "READY", 87,
                Map.of("target_role", "BACKEND_ENGINEER"), List.of());
        return new CSnapshot(RECOMMENDATION, "RECOMMENDATION",
                new CSnapshot.Recommendation("7", "u7-x", "cohort-1", "READY", 12, List.of(),
                        demand, gap, Map.of(), Map.of(), List.of(), null));
    }

    @Test
    @DisplayName("목표 직무를 고른 적이 없으면 data가 null이다")
    void targetIsNullBeforeSelection() throws Exception {
        when(targets.find(USER_ID)).thenReturn(Optional.empty());

        mvc.perform(get("/api/v1/me/target"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    @Test
    @DisplayName("목표 직무를 저장하면 캐시 키를 함께 준다")
    void saveTargetReturnsCacheKey() throws Exception {
        when(targets.save(anyLong(), anyString(), any(), any(), any())).thenReturn(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH));

        mvc.perform(put("/api/v1/me/target")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"targetRole\":\"BACKEND\",\"regions\":[\"서울\"],"
                                + "\"careerLevels\":[\"신입\"]}"))
                .andExpect(status().isOk())
                // FE 가 직무·필터에서 직접 키를 만들면 공백·순서 차이로 캐시가 두 벌 생긴다.
                .andExpect(jsonPath("$.data.targetKey").value("BACKEND|서울|신입"));

        // 저장 요청 안에서 C를 기다리지 않고 scheduler가 다음 tick에 계산한다.
        verify(scheduler).requestInitialSync(USER_ID);
        verify(sync, never()).synchronize(USER_ID);
    }

    @Test
    @DisplayName("목표 직무가 없으면 매칭은 404 MATCH-404-1이다")
    void matchingRequiresTarget() throws Exception {
        when(targets.find(USER_ID)).thenReturn(Optional.empty());

        mvc.perform(get("/api/v1/me/job-matches"))
                .andExpect(status().isNotFound())
                // FE 는 이 코드를 "목표 직무를 먼저 고르세요" CTA 로 처리한다.
                .andExpect(jsonPath("$.code").value("MATCH-404-1"));
    }

    @Test
    @DisplayName("사용자 ID는 세션에서만 오고 요청 파라미터를 신뢰하지 않는다")
    void ignoresUserIdFromRequest() throws Exception {
        mvc.perform(get("/api/v1/me/skill-gap").param("userId", "999"))
                .andExpect(status().isOk());

        // 999 가 아니라 세션의 7 로 C 를 부른다.
        verify(compute).recommendation(RECOMMENDATION, USER_ID);
        verify(compute, never()).recommendation(anyString(), eq(999L));
    }

    @Test
    @DisplayName("응답에 C Snapshot ID를 내려보내지 않는다")
    void hidesSnapshotIdentifiers() throws Exception {
        mvc.perform(get("/api/v1/me/skill-gap"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.snapshotId").doesNotExist())
                .andExpect(jsonPath("$.data.basis.targetRole").value("BACKEND_ENGINEER"))
                .andExpect(jsonPath("$.data.basis.jobCount").value(87));
    }

    @Test
    @DisplayName("미판정 기술을 부족으로 세지 않는다")
    void doesNotCountUnknownAsGap() throws Exception {
        mvc.perform(get("/api/v1/me/skill-gap"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.rows[0].verdict").value("UNDETERMINED"))
                .andExpect(jsonPath("$.data.summary.gapCount").value(0))
                .andExpect(jsonPath("$.data.summary.undeterminedCount").value(1));
    }

    @Test
    @DisplayName("페이징 상한을 넘겨도 C가 받는 범위로 자른다")
    void clampsPageSize() throws Exception {
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), any(Boolean.class)))
                .thenReturn(new com.example.git_job.compute.client.dto.CMatching(
                        RECOMMENDATION, "calc-1", "cohort-1", 0, 0, 0, 0, 50, false,
                        List.of(), List.of()));

        mvc.perform(get("/api/v1/me/job-matches").param("perPage", "500"))
                .andExpect(status().isOk());

        // C 의 size 상한은 50 이다. 넘겨 보내면 422 가 나는데 사용자 잘못이 아니다.
        verify(compute).matching(RECOMMENDATION, USER_ID, 0, 50, false);
    }

    /** 세션 사용자 주입. 실제 배포에서는 JWT 필터가 같은 자리를 채운다. */
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
