package com.example.git_job.global.security;

import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.logging.TraceIdFilter;
import com.example.git_job.global.response.ErrorResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import lombok.RequiredArgsConstructor;
import org.slf4j.MDC;
import org.springframework.http.MediaType;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import tools.jackson.databind.ObjectMapper;

/**
 * 인증 실패(401) 응답을 REST 공통 {@link ErrorResponse} 포맷으로 통일한다.
 * Security Filter 단계의 실패는 GlobalExceptionHandler에 도달하지 않으므로
 * 이 EntryPoint가 없으면 클라이언트가 파싱할 수 없는 기본 응답이 나간다.
 *
 * <p>같은 이유로 로그의 {@code errorCode} 필드도 여기서 채운다. MDC에 넣으면
 * {@code TraceIdFilter}의 액세스 로그가 그 값을 함께 남기므로 401 한 건마다
 * 별도 로그 줄을 만들지 않아도 된다(S15P11E207-1582 로그량 제어).</p>
 */
@Component
@RequiredArgsConstructor
public class JwtAuthenticationEntryPoint implements AuthenticationEntryPoint {

    private final ObjectMapper objectMapper;

    @Override
    public void commence(
            HttpServletRequest request,
            HttpServletResponse response,
            AuthenticationException authException
    ) throws IOException {

        ErrorCode errorCode = ErrorCode.UNAUTHORIZED;
        // 인증 실패 원인(만료·위조·blacklist)은 남기지 않는다. 토큰 내용이 섞일 수 있고,
        // 공격자에게 어떤 검증에서 걸렸는지 알려 줄 이유도 없다.
        MDC.put(TraceIdFilter.ERROR_CODE, errorCode.getCode());

        response.setStatus(errorCode.getHttpStatus().value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), ErrorResponse.of(errorCode));
    }
}
