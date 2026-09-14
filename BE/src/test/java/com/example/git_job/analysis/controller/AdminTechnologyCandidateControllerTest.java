package com.example.git_job.analysis.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.analysis.store.TechnologyCandidateStore.Ranked;
import com.example.git_job.analysis.service.TechnologyCandidateAdminService;
import com.example.git_job.analysis.service.TechnologyCandidateAdminService.RegistryStatus;
import com.example.git_job.auth.domain.Role;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * 관리자 화면이 실제로 받는 HTTP 응답을 고정한다.
 *
 * <p>서비스 단위 테스트가 확인하지 못하는 것이 두 가지다. 하나는 승격 응답이
 * {@code techId}와 레지스트리 상태를 함께 싣는다는 것 — 화면이 "무엇으로
 * 등록됐는지"를 그 필드로 보여준다. 다른 하나는 거절 사유가 상태 코드로
 * 내려온다는 것이다. 이미 처리된 후보는 409여야 하고, 500이면 화면은 그것을
 * 서버 장애로 표시한다.</p>
 *
 * <p>{@code SecurityConfig}는 올리지 않는다. 이 슬라이스에서 보안 필터까지
 * 세우면 검증 대상과 무관한 빈들이 줄줄이 필요해진다. ADMIN 제한 자체는
 * {@code SecurityConfig}의 매처가 담당하며 여기서 확인하지 않는다.</p>
 */
class AdminTechnologyCandidateControllerTest {

    private static final String BASE = "/api/v1/admin/technology-candidates";
    private static final Instant SEEN = Instant.parse("2026-09-10T00:00:00Z");

    private MockMvc mockMvc;
    private TechnologyCandidateAdminService admin;

    @BeforeEach
    void setUp() {
        admin = mock(TechnologyCandidateAdminService.class);
        when(admin.registryStatus())
                .thenReturn(new RegistryStatus("registry-20260910.2", "registry-20260910.3"));

        mockMvc = MockMvcBuilders.standaloneSetup(new AdminTechnologyCandidateController(admin))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new FixedPrincipal())
                .build();
    }

    @Test
    @DisplayName("목록은 후보의 판단 근거를 그대로 내려준다")
    void theListCarriesTheNumbersTheDecisionTurnsOn() throws Exception {
        when(admin.list(50)).thenReturn(List.of(new Ranked(
                7L, "MAVEN", "com.h2database:h2", "TEST", "NEW", 9, 12, 30, SEEN, SEEN)));

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].candidateId").value(7))
                .andExpect(jsonPath("$.data[0].coordinate").value("com.h2database:h2"))
                .andExpect(jsonPath("$.data[0].distinctUserCount").value(9));
    }

    @Test
    @DisplayName("승격 응답은 등록된 식별자와 초안 버전을 함께 싣는다")
    void promotionAnswersWithTheIdAndTheDraft() throws Exception {
        // 식별자는 대개 관리자가 넘기지 않고 좌표에서 만들어진다. 화면은
        // 무엇으로 등록됐는지를 이 값으로만 알 수 있다.
        when(admin.promote(eq(7L), any(), any(), any(), eq(1L), any())).thenReturn("h2database");

        mockMvc.perform(post(BASE + "/7/promote")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"jobDomains\":[\"BACKEND\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.techId").value("h2database"))
                .andExpect(jsonPath("$.data.registry.draft").value("registry-20260910.3"));
    }

    @Test
    @DisplayName("본문 없는 승격도 받는다")
    void promotionWithoutABodyIsAccepted() throws Exception {
        // 좌표가 곧 답인 경우가 많아 화면이 빈 요청을 보낼 수 있어야 한다.
        when(admin.promote(anyLong(), any(), any(), any(), anyLong(), any()))
                .thenReturn("caffeine");

        mockMvc.perform(post(BASE + "/7/promote"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.techId").value("caffeine"));
    }

    @Test
    @DisplayName("이미 처리된 후보는 409와 코드로 답한다")
    void anAlreadyDecidedCandidateIsAConflict() throws Exception {
        // 관리자 둘이 같은 행을 누르는 것은 정상이다. 500으로 내려가면 화면은
        // 서버 장애를 알리고, 관리자는 실제로 일어난 일을 알 수 없다.
        when(admin.promote(anyLong(), any(), any(), any(), anyLong(), any()))
                .thenThrow(new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED));

        mockMvc.perform(post(BASE + "/7/promote"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ADMIN-409-1"));
    }

    @Test
    @DisplayName("없는 후보는 404다")
    void anUnknownCandidateIsNotFound() throws Exception {
        doThrow(new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND))
                .when(admin).reject(anyLong(), anyLong(), any());

        mockMvc.perform(post(BASE + "/99/reject")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"note\":\"빌드 도구\"}"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ADMIN-404-1"));
    }

    @Test
    @DisplayName("식별자 형식 오류는 400이다")
    void anIllFormedIdIsABadRequest() throws Exception {
        when(admin.promote(anyLong(), any(), any(), any(), anyLong(), any()))
                .thenThrow(new CustomException(ErrorCode.INVALID_TECHNOLOGY_ID));

        mockMvc.perform(post(BASE + "/7/promote")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"techId\":\"Spring Boot!\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("ADMIN-400-1"));
    }

    @Test
    @DisplayName("발행할 초안이 없으면 409다")
    void publishingNothingIsAConflict() throws Exception {
        when(admin.publishDraft())
                .thenThrow(new CustomException(ErrorCode.REGISTRY_DRAFT_EMPTY));

        mockMvc.perform(post(BASE + "/registry/publish"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ADMIN-409-2"));
    }

    @Test
    @DisplayName("레지스트리 상태는 적용 중인 버전과 초안을 알린다")
    void theRegistryStatusNamesBothVersions() throws Exception {
        mockMvc.perform(get(BASE + "/registry"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.current").value("registry-20260910.2"))
                .andExpect(jsonPath("$.data.draft").value("registry-20260910.3"));
    }

    /**
     * {@code @AuthenticationPrincipal}은 보안 필터가 채우는 값이라 standalone
     * 세팅에서는 비어 있다. 결정을 누가 했는지는 감사 기록에 남으므로 고정한 값을
     * 넣어 컨트롤러가 그것을 서비스로 넘기는지까지 확인한다.
     */
    private static final class FixedPrincipal implements HandlerMethodArgumentResolver {

        @Override
        public boolean supportsParameter(org.springframework.core.MethodParameter parameter) {
            return AuthenticatedUser.class.equals(parameter.getParameterType());
        }

        @Override
        public Object resolveArgument(org.springframework.core.MethodParameter parameter,
                ModelAndViewContainer container,
                org.springframework.web.context.request.NativeWebRequest request,
                org.springframework.web.bind.support.WebDataBinderFactory factory) {
            return new AuthenticatedUser("1", "octocat", "jti", SEEN, Role.ADMIN);
        }
    }
}
