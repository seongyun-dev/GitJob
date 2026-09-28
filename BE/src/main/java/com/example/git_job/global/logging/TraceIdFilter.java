package com.example.git_job.global.logging;

import com.example.git_job.global.security.AuthenticatedUser;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Duration;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 요청마다 traceId를 부여하고 HTTP 액세스 로그를 남긴다 (S15P11E207-1582).
 *
 * <p>필터 체인의 가장 앞에 둔다. 우리 서비스는 JWT 만료·위조 요청이
 * {@code JwtAuthenticationFilter}에서 차단되어 Controller에 도달하지 않으므로,
 * traceId를 그 뒤에 부여하면 인증 실패 로그에 상관관계 키가 없어 추적이 끊긴다.
 *
 * <p>액세스 로그를 체인 <b>이후</b>에 기록하는 덕분에 인증 필터가 나중에 채운
 * 사용자 정보와 최종 응답 상태를 한 줄에 함께 담을 수 있다.
 *
 * <p>본문(payload)은 절대 기록하지 않는다. 게임 요청·응답에는 개인 정보카드와
 * 자산 같은 비공개 상태가 담기므로 로그에 남기면 그 자체가 정보 유출이다.
 * 로그 필드 규약은 {@code infra/docs/logging-spec-1582.md}를 따른다.
 */
@Component
public class TraceIdFilter extends OncePerRequestFilter {

    /** 클라이언트·프록시와 traceId를 주고받는 헤더. 응답에도 같은 값을 실어 준다. */
    public static final String TRACE_ID_HEADER = "X-Trace-Id";

    public static final String TRACE_ID = "traceId";
    public static final String USER_ID = "userId";

    /**
     * 오류 코드 필드명. 예외 핸들러와 인증 EntryPoint가 채우고, 이 필터의 액세스
     * 로그가 같은 요청의 MDC에서 함께 남긴다. 정리는 이 필터가 일괄 수행한다.
     */
    public static final String ERROR_CODE = "errorCode";

    /**
     * 로그 유형 필드명. 액세스 로그는 {@code access}, DB 오류는 {@code db-error}처럼
     * 유형을 표시해 Loki에서 한 번에 걸러낸다(1582 규약 §3, 1678 파이프라인이 소비).
     */
    public static final String LOG_TYPE = "logType";

    private static final String ACCESS_LOG_TYPE = "access";
    private static final String ACTUATOR_PATH_PREFIX = "/actuator";

    /**
     * 외부에서 받은 traceId는 그대로 신뢰하지 않는다. 길이·문자를 제한해
     * 로그 위조(개행 삽입)와 비정상적으로 긴 값이 섞이는 것을 막는다.
     */
    private static final Pattern SAFE_TRACE_ID = Pattern.compile("[A-Za-z0-9_-]{1,64}");

    /**
     * 액세스 로그 전용 logger. 클래스명이 아닌 고정 이름을 쓰므로 Loki에서
     * {@code logger_name="http.access"} 하나로 트래픽만 골라낼 수 있고,
     * 필요하면 이 logger의 레벨만 따로 조절할 수 있다.
     */
    private static final Logger accessLog = LoggerFactory.getLogger("http.access");

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String traceId = resolveTraceId(request);
        MDC.put(TRACE_ID, traceId);
        // 응답이 커밋되기 전에 넣어야 오류 응답에도 traceId가 실린다.
        response.setHeader(TRACE_ID_HEADER, traceId);

        long startedAt = System.nanoTime();
        try {
            filterChain.doFilter(request, response);
        } finally {
            try {
                if (!isExcludedFromAccessLog(request)) {
                    writeAccessLog(request, response, startedAt);
                }
            } finally {
                // 톰캣이 스레드를 재사용하므로 지우지 않으면 다음 요청에 남의
                // traceId·userId가 섞인다. 액세스 로그 제외 경로에서도 반드시 실행한다.
                MDC.clear();
            }
        }
    }

    /**
     * healthcheck와 Prometheus scrape는 15초 주기로 반복되는 기계 트래픽이라
     * 액세스 로그로 남기면 Loki 보존 용량만 잠식하고 사람이 읽을 정보가 없다.
     * 단, MDC 정리는 이 경로에서도 수행한다.
     */
    private boolean isExcludedFromAccessLog(HttpServletRequest request) {
        return request.getRequestURI().startsWith(ACTUATOR_PATH_PREFIX);
    }

    private void writeAccessLog(
            HttpServletRequest request,
            HttpServletResponse response,
            long startedAt
    ) {
        long durationMs = Duration.ofNanos(System.nanoTime() - startedAt).toMillis();
        int status = response.getStatus();
        String method = request.getMethod();
        // Query String은 남기지 않는다. 경로 변수만으로 요청을 식별할 수 있고,
        // 쿼리에 민감한 값이 실려도 로그로 새지 않는다.
        String path = request.getRequestURI();

        // 인증은 체인 안에서 이뤄지므로 이 시점에야 사용자를 알 수 있다.
        if (MDC.get(USER_ID) == null) {
            String userId = resolveUserId();
            if (userId != null) {
                MDC.put(USER_ID, userId);
            }
        }
        MDC.put(LOG_TYPE, ACCESS_LOG_TYPE);
        MDC.put("method", method);
        MDC.put("path", path);
        MDC.put("status", String.valueOf(status));
        MDC.put("durationMs", String.valueOf(durationMs));

        String message = "%s %s -> %d (%dms)".formatted(method, path, status, durationMs);
        // 레벨 규약(1582): 5xx는 서버 결함이므로 ERROR, 4xx는 클라이언트 문제라 WARN.
        // 4xx를 ERROR로 올리면 잘못된 방 코드 입력만으로 장애 알림이 울린다.
        if (status >= 500) {
            accessLog.error(message);
        } else if (status >= 400) {
            accessLog.warn(message);
        } else {
            accessLog.info(message);
        }
    }

    private String resolveTraceId(HttpServletRequest request) {
        String candidate = request.getHeader(TRACE_ID_HEADER);
        if (candidate != null && SAFE_TRACE_ID.matcher(candidate).matches()) {
            return candidate;
        }
        return UUID.randomUUID().toString().replace("-", "");
    }

    private String resolveUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !(authentication.getPrincipal() instanceof AuthenticatedUser user)) {
            return null;
        }
        // 닉네임은 남기지 않는다. 운영 추적에는 식별자만 필요하다.
        return user.userId();
    }
}
