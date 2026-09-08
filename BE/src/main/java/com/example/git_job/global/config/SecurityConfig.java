package com.example.git_job.global.config;

import com.example.git_job.global.logging.TraceIdFilter;
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
            TraceIdFilter traceIdFilter
    ) throws Exception {
        return http
                // TODO(GH-AUTH-001 후속): 인증이 HttpOnly 쿠키 SESSION으로 전달되므로
                //  브라우저가 요청마다 자동으로 실어 보낸다. 지금은 공개 엔드포인트가
                //  OAuth 진입·콜백 GET 두 개뿐이고 SameSite=Lax가 cross-site 전송을
                //  막아 실질 표면이 없지만, 상태를 바꾸는 POST/PUT/DELETE API가 들어오면
                //  CookieCsrfTokenRepository로 CSRF를 활성화해야 한다.
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(exception ->
                        exception.authenticationEntryPoint(authenticationEntryPoint))
                .authorizeHttpRequests(authorize -> authorize
                        // GitHub OAuth 진입·콜백은 세션 발급 이전 단계이므로 공개한다.
                        // 토큰 없이 호출되는 유일한 경로이며, 그 외는 모두 인증을 요구한다.
                        // (B-FN-001 / GH-AUTH-001)
                        .requestMatchers(
                                HttpMethod.GET,
                                "/api/v1/auth/github",
                                "/api/v1/auth/github/callback"
                        ).permitAll()
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
                        .anyRequest().authenticated())
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)
                // traceId는 인증보다 먼저 부여한다. JWT 만료·위조 요청은 인증 필터에서
                // 끊기므로, 순서를 뒤집으면 그 실패 로그에 traceId가 없어 추적이 끊긴다.
                .addFilterBefore(traceIdFilter, JwtAuthenticationFilter.class)
                .build();
    }
}
