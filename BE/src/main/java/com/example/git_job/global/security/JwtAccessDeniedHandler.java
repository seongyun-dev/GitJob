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
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/**
 * 인가 실패(403) 응답을 REST 공통 {@link ErrorResponse} 포맷으로 통일한다.
 *
 * <p>{@link JwtAuthenticationEntryPoint}의 짝이다. 인증은 됐지만 요구 권한이 없을 때
 * {@code ExceptionTranslationFilter}가 여기를 부른다. Security Filter 단계의 실패는
 * {@code GlobalExceptionHandler}에 도달하지 않으므로, 이 핸들러가 없으면 Spring 기본
 * 오류 본문({@code {timestamp, status, error, path}})이 나가고 클라이언트는 {@code code}로
 * 분기할 수 없다. 실제로 USER 세션으로 {@code /api/v1/admin/**}을 열면 FE가 서버 코드
 * 대신 {@code HTTP-403}이라는 대체 코드를 만들어 화면에 띄웠다.</p>
 *
 * <p>지금 {@code hasRole} 제한은 {@code /api/v1/admin/**} 하나뿐이라 코드도 하나
 * ({@link ErrorCode#ADMIN_ROLE_REQUIRED})로 답한다. 역할이 늘면 요청 경로로 코드를
 * 갈라야 한다. 메서드 수준 {@code @PreAuthorize}에서 난 {@link AccessDeniedException}은
 * 이 필터를 거치지 않고 MVC로 전파되므로 그때는 {@code GlobalExceptionHandler}에 별도
 * 핸들러가 필요하다 — 현재 그런 사용처는 없다.</p>
 *
 * <p>로그의 {@code errorCode} 필드는 EntryPoint와 같은 이유로 여기서 채운다. MDC에 넣으면
 * {@code TraceIdFilter}의 액세스 로그가 그 값을 함께 남기므로 403 한 건마다 별도 로그 줄을
 * 만들지 않는다. 어떤 권한이 부족했는지는 남기지 않는다 — 요청 경로가 이미 액세스 로그에
 * 있고, 그 이상은 공격자에게 권한 구조를 알려 줄 뿐이다.</p>
 */
@Component
@RequiredArgsConstructor
public class JwtAccessDeniedHandler implements AccessDeniedHandler {

    private final ObjectMapper objectMapper;

    @Override
    public void handle(
            HttpServletRequest request,
            HttpServletResponse response,
            AccessDeniedException accessDeniedException
    ) throws IOException {
        ErrorCode errorCode = ErrorCode.ADMIN_ROLE_REQUIRED;
        MDC.put(TraceIdFilter.ERROR_CODE, errorCode.getCode());
        response.setStatus(errorCode.getHttpStatus().value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), ErrorResponse.of(errorCode));
    }
}
