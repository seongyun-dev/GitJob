package com.example.git_job.global.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.git_job.global.logging.TraceIdFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.access.AccessDeniedException;
import tools.jackson.databind.ObjectMapper;

/**
 * 403이 공통 봉투로 나가는지 본다. 상태 코드만 확인하면 Spring 기본 본문도 통과하므로
 * {@code code} 필드까지 확인한다 — 이 핸들러가 없을 때 새던 것이 정확히 그 필드다.
 */
class JwtAccessDeniedHandlerTest {

    private final JwtAccessDeniedHandler handler = new JwtAccessDeniedHandler(new ObjectMapper());

    @AfterEach
    void clearMdc() {
        MDC.clear();
    }

    @Test
    void writesForbiddenInTheCommonEnvelope() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/admin/monitoring/overview");
        MockHttpServletResponse response = new MockHttpServletResponse();

        handler.handle(request, response, new AccessDeniedException("Access Denied"));

        assertThat(response.getStatus()).isEqualTo(HttpStatus.FORBIDDEN.value());
        assertThat(response.getContentType()).startsWith(MediaType.APPLICATION_JSON_VALUE);
        assertThat(response.getContentAsString())
                .contains("\"code\":\"AUTH-403-2\"")
                .contains("\"message\":\"관리자 권한이 필요합니다.\"")
                // Spring 기본 오류 본문의 흔적이 섞이면 안 된다.
                .doesNotContain("\"timestamp\"")
                .doesNotContain("\"path\"");
    }

    /** 액세스 로그가 errorCode 를 함께 남기려면 MDC 에 값이 있어야 한다. EntryPoint 와 같은 계약이다. */
    @Test
    void putsErrorCodeIntoMdcForTheAccessLog() throws Exception {
        handler.handle(new MockHttpServletRequest(), new MockHttpServletResponse(),
                new AccessDeniedException("Access Denied"));

        assertThat(MDC.get(TraceIdFilter.ERROR_CODE)).isEqualTo("AUTH-403-2");
    }
}
