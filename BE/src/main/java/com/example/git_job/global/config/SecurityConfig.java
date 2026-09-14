package com.example.git_job.global.config;

import com.example.git_job.global.logging.TraceIdFilter;
import com.example.git_job.global.security.JwtAccessDeniedHandler;
import com.example.git_job.global.security.JwtAuthenticationEntryPoint;
import com.example.git_job.global.security.JwtAuthenticationFilter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {

    @Bean
    public SecurityFilterChain securityFilterChain(
            HttpSecurity http,
            JwtAuthenticationFilter jwtAuthenticationFilter,
            JwtAuthenticationEntryPoint authenticationEntryPoint,
            JwtAccessDeniedHandler accessDeniedHandler,
            TraceIdFilter traceIdFilter
    ) throws Exception {
        return http
                // TODO(GH-AUTH-001 후속): 인증이 HttpOnly 쿠키 SESSION으로 전달되므로
                //  브라우저가 요청마다 자동으로 실어 보낸다. 지금 공개 엔드포인트는
                //  OAuth 진입·콜백 GET 두 개와 모니터링 조회 GET이며 모두 읽기 전용이고,
                //  SameSite=Lax가 cross-site 전송을 막아 실질 표면이 없지만, 상태를
                //  바꾸는 POST/PUT/DELETE API가 들어오면 CookieCsrfTokenRepository로
                //  CSRF를 활성화해야 한다.
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                // 401(인증 없음)과 403(권한 없음)을 각각 공통 봉투로 내린다. 둘 중 하나만
                // 등록하면 나머지는 Spring 기본 본문으로 새어 나가 클라이언트가 code로
                // 분기하지 못한다 — 실제로 403이 그랬다.
                .exceptionHandling(exception -> exception
                        .authenticationEntryPoint(authenticationEntryPoint)
                        .accessDeniedHandler(accessDeniedHandler))
                .authorizeHttpRequests(authorize -> authorize
                        // GitHub OAuth 진입·콜백은 세션 발급 이전 단계이므로 공개한다.
                        // 토큰 없이 호출되는 유일한 경로이며, 그 외는 모두 인증을 요구한다.
                        // (B-FN-001 / GH-AUTH-001)
                        .requestMatchers(
                                HttpMethod.GET,
                                "/api/v1/auth/github",
                                "/api/v1/auth/github/callback"
                        ).permitAll()
                        // 로그아웃은 인증 없이도 동작해야 한다. 만료·무효 쿠키를 든 사용자가
                        // 쿠키를 정리하려는 상황이 정상이고, 하는 일은 SESSION 쿠키 만료뿐이다.
                        // (/api/v1/auth/me 는 인증이 필요하므로 아래 anyRequest 규칙을 따른다.)
                        .requestMatchers(HttpMethod.POST, "/api/v1/auth/logout").permitAll()
                        // Spring MVC가 오류를 forward하는 내부 경로.
                        .requestMatchers("/error").permitAll()
                        // Docker 내부 네트워크 전용 (Nginx 비라우팅): healthcheck
                        .requestMatchers("/actuator/health", "/actuator/health/**")
                        .permitAll()
                        .requestMatchers(
                                "/v3/api-docs/**",
                                "/swagger-ui.html",
                                "/swagger-ui/**"
                        ).permitAll()
                        // 시스템 모니터링 대시보드는 로그인 없이 URL만으로 연다(2026-09-11 결정).
                        // 읽기 전용 GET이고 아래 Registry 규칙보다 먼저 와야 매칭된다 —
                        // Spring Security는 첫 일치 규칙을 적용한다.
                        //
                        // 공개되는 것: 서버 호스트명·CPU/메모리/디스크/네트워크 수치·target UP/DOWN·
                        // node-exporter instance(Tailscale 100.x, 외부 라우팅 불가)·Grafana/Prometheus
                        // 링크. 파괴적 동작은 없지만 인프라 형상이 드러나므로, 공개 범위를 되돌릴 때는
                        // 이 줄만 지우면 Registry와 같은 ADMIN 규칙으로 돌아간다.
                        .requestMatchers(HttpMethod.GET, "/api/v1/admin/monitoring/**").permitAll()
                        // 관리자 전용. 여기서 하는 일은 Registry 변경이고, Registry는
                        // 모든 사용자의 기술 프로필이 판정되는 기준이다. 로그인한
                        // 아무나 후보를 승격하면 한 사람이 전체 판정을 바꾼다.
                        // 모니터링과 달리 이 규칙은 열지 않는다 — 쓰기 API다.
                        .requestMatchers("/api/v1/admin/**").hasRole("ADMIN")
                        .anyRequest().authenticated())
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)
                // traceId는 인증보다 먼저 부여한다. JWT 만료·위조 요청은 인증 필터에서
                // 끊기므로, 순서를 뒤집으면 그 실패 로그에 traceId가 없어 추적이 끊긴다.
                .addFilterBefore(traceIdFilter, JwtAuthenticationFilter.class)
                .build();
    }
}
