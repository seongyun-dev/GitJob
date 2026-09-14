package com.example.git_job.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.auth.service.GithubOAuthService;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.global.web.CookieUtil;
import jakarta.servlet.http.Cookie;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/**
 * 진입·콜백의 HTTP 계약을 검증한다. 302 Location과 Set-Cookie는 FE가 의존하는
 * 계약이라 서비스 단위 테스트만으로는 확인되지 않는다.
 *
 * <p>Spring 컨텍스트를 띄우지 않고 컨트롤러만 세운다. {@code @WebMvcTest} 슬라이스는
 * {@code SecurityConfig}를 함께 로드하면서 검증 대상과 무관한 필터 빈들을 요구하고,
 * 그 배선을 따라가면 AES 키까지 필요해진다. 여기서 확인할 것은 컨트롤러가 만드는
 * 응답 자체이므로 의존성을 직접 주입하는 편이 단순하고 빠르다.</p>
 */
class AuthControllerTest {

    private static final String ENTER_PATH = "/api/v1/auth/github";
    private static final String CALLBACK_PATH = "/api/v1/auth/github/callback";
    private static final String FRONTEND_CALLBACK = "http://localhost:8080/auth/callback";
    private static final String STATE = "st_abcdefghijklmnop";
    private static final String AUTHORIZE_URL =
            "https://github.com/login/oauth/authorize?client_id=test-client-id&state=" + STATE;

    private MockMvc mockMvc;
    private GithubOAuthService githubOAuthService;

    @BeforeEach
    void setUp() {
        githubOAuthService = mock(GithubOAuthService.class);
        GithubOAuthProperties properties = new GithubOAuthProperties(
                "test-client-id", "test-client-secret",
                "http://localhost:8080/api/v1/auth/github/callback",
                "https://api.github.com",
                FRONTEND_CALLBACK,
                List.of("/onboarding/repositories", "/repos")
        );
        AuthController controller = new AuthController(
                githubOAuthService,
                mock(com.example.git_job.auth.service.AuthQueryService.class),
                properties,
                new CookieUtil(false));

        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private static List<String> setCookies(MvcResult result) {
        return result.getResponse().getHeaders(HttpHeaders.SET_COOKIE);
    }

    private static void assertHasCookie(MvcResult result, String expectedFragment) {
        assertThat(setCookies(result))
                .as("Set-Cookie 헤더에 %s 가 있어야 한다", expectedFragment)
                .anySatisfy(cookie -> assertThat(cookie).contains(expectedFragment));
    }

    @Nested
    @DisplayName("GET /api/v1/auth/github")
    class EnterGithubLogin {

        @Test
        @DisplayName("GitHub 인증 URL로 302하고 state·복귀경로 쿠키를 함께 내린다")
        void redirectsToGithubWithCookies() throws Exception {
            when(githubOAuthService.startLogin(null)).thenReturn(
                    new GithubOAuthService.AuthorizeRedirect(AUTHORIZE_URL, STATE, "/repos"));

            MvcResult result = mockMvc.perform(get(ENTER_PATH))
                    .andExpect(status().isFound())
                    .andReturn();

            assertThat(result.getResponse().getRedirectedUrl()).isEqualTo(AUTHORIZE_URL);
            assertHasCookie(result, "OAUTH_STATE=" + STATE);
            assertHasCookie(result, "OAUTH_REDIRECT=/repos");
        }

        @Test
        @DisplayName("state 쿠키는 HttpOnly·SameSite=Lax·Max-Age=600으로 나간다")
        void stateCookieAttributes() throws Exception {
            when(githubOAuthService.startLogin(null)).thenReturn(
                    new GithubOAuthService.AuthorizeRedirect(AUTHORIZE_URL, STATE, "/repos"));

            MvcResult result = mockMvc.perform(get(ENTER_PATH)).andReturn();

            String stateCookie = setCookies(result).stream()
                    .filter(cookie -> cookie.startsWith("OAUTH_STATE="))
                    .findFirst()
                    .orElseThrow();
            assertThat(stateCookie)
                    .contains("HttpOnly")
                    .contains("SameSite=Lax")
                    .contains("Max-Age=600")
                    .contains("Path=/");
        }

        @Test
        @DisplayName("redirectTo를 그대로 서비스에 넘긴다")
        void passesRedirectToThrough() throws Exception {
            when(githubOAuthService.startLogin("/repos")).thenReturn(
                    new GithubOAuthService.AuthorizeRedirect(AUTHORIZE_URL, STATE, "/repos"));

            mockMvc.perform(get(ENTER_PATH).param("redirectTo", "/repos"))
                    .andExpect(status().isFound());

            verify(githubOAuthService).startLogin("/repos");
        }

        @Test
        @DisplayName("허용되지 않은 redirectTo는 AUTH-400-1 JSON으로 응답한다")
        void rejectsUnlistedRedirect() throws Exception {
            when(githubOAuthService.startLogin("//evil.com"))
                    .thenThrow(new CustomException(ErrorCode.OAUTH_REDIRECT_NOT_ALLOWED));

            mockMvc.perform(get(ENTER_PATH).param("redirectTo", "//evil.com"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("AUTH-400-1"));
        }
    }

    @Nested
    @DisplayName("GET /api/v1/auth/github/callback")
    class GithubCallback {

        private GithubOAuthService.LoginSession session() {
            return new GithubOAuthService.LoginSession("session-jwt", Duration.ofMinutes(30));
        }

        @Test
        @DisplayName("성공하면 FE 콜백 화면으로 302하고 SESSION 쿠키를 내린다")
        void redirectsToFrontendOnSuccess() throws Exception {
            when(githubOAuthService.completeLogin("code", STATE, STATE)).thenReturn(session());

            MvcResult result = mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE)
                            .cookie(new Cookie(CookieUtil.OAUTH_STATE, STATE))
                            .cookie(new Cookie(CookieUtil.OAUTH_REDIRECT, "/repos")))
                    .andExpect(status().isFound())
                    .andReturn();

            assertThat(result.getResponse().getRedirectedUrl())
                    .startsWith(FRONTEND_CALLBACK)
                    .contains("status=success")
                    .contains("redirectTo=/repos");
            assertHasCookie(result, "SESSION=session-jwt");
        }

        @Test
        @DisplayName("성공 시 state·복귀경로 쿠키를 Max-Age=0으로 지운다")
        void clearsOauthCookiesOnSuccess() throws Exception {
            when(githubOAuthService.completeLogin("code", STATE, STATE)).thenReturn(session());

            MvcResult result = mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE)
                            .cookie(new Cookie(CookieUtil.OAUTH_STATE, STATE))
                            .cookie(new Cookie(CookieUtil.OAUTH_REDIRECT, "/repos")))
                    .andReturn();

            assertThat(setCookies(result))
                    .anySatisfy(cookie -> assertThat(cookie)
                            .startsWith("OAUTH_STATE=").contains("Max-Age=0"))
                    .anySatisfy(cookie -> assertThat(cookie)
                            .startsWith("OAUTH_REDIRECT=").contains("Max-Age=0"));
        }

        @Test
        @DisplayName("조작된 복귀경로 쿠키는 무시하고 기본 목적지로 보낸다")
        void ignoresTamperedRedirectCookie() throws Exception {
            when(githubOAuthService.completeLogin("code", STATE, STATE)).thenReturn(session());

            MvcResult result = mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE)
                            .cookie(new Cookie(CookieUtil.OAUTH_STATE, STATE))
                            .cookie(new Cookie(CookieUtil.OAUTH_REDIRECT, "//evil.com")))
                    .andExpect(status().isFound())
                    .andReturn();

            assertThat(result.getResponse().getRedirectedUrl())
                    .doesNotContain("evil.com")
                    .contains("redirectTo=/onboarding/repositories");
        }

        @Test
        @DisplayName("권한 거부는 오류가 아니라 안내 화면으로 302한다 (AUTH-403-3)")
        void redirectsToDeniedScreen() throws Exception {
            MvcResult result = mockMvc.perform(get(CALLBACK_PATH)
                            .param("error", "access_denied")
                            .param("error_description", "The user denied the request"))
                    .andExpect(status().isFound())
                    .andReturn();

            assertThat(result.getResponse().getRedirectedUrl())
                    .startsWith(FRONTEND_CALLBACK)
                    .contains("status=denied")
                    .contains("code=AUTH-403-3");

            // 권한 거부 시 사용자 Row와 세션을 만들지 않는다 (GH-AUTH-001 인수 조건).
            verify(githubOAuthService, never()).completeLogin(anyString(), anyString(), anyString());
            assertThat(setCookies(result)).noneSatisfy(
                    cookie -> assertThat(cookie).startsWith("SESSION=session-jwt"));
        }

        @Test
        @DisplayName("state 검증 실패는 AUTH-400-2 JSON으로 응답한다 — FE 주소를 신뢰할 수 없는 단계다")
        void returnsJsonOnStateMismatch() throws Exception {
            when(githubOAuthService.completeLogin(any(), any(), any()))
                    .thenThrow(new CustomException(ErrorCode.OAUTH_INVALID_STATE));

            mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("AUTH-400-2"));
        }

        @Test
        @DisplayName("scope 미승인은 AUTH-403-4로 응답한다")
        void returnsJsonOnScopeNotGranted() throws Exception {
            when(githubOAuthService.completeLogin(any(), any(), any()))
                    .thenThrow(new CustomException(ErrorCode.OAUTH_SCOPE_NOT_GRANTED));

            mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE)
                            .cookie(new Cookie(CookieUtil.OAUTH_STATE, STATE)))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.code").value("AUTH-403-4"));
        }

        @Test
        @DisplayName("state 쿠키가 없으면 null로 서비스까지 전달되어 거절된다")
        void passesNullCookieToService() throws Exception {
            when(githubOAuthService.completeLogin(any(), any(), any()))
                    .thenThrow(new CustomException(ErrorCode.OAUTH_INVALID_STATE));

            mockMvc.perform(get(CALLBACK_PATH)
                            .param("code", "code")
                            .param("state", STATE))
                    .andExpect(status().isBadRequest());

            verify(githubOAuthService).completeLogin("code", STATE, null);
        }
    }
}
