package com.example.git_job.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.auth.client.GithubOAuthClient;
import com.example.git_job.auth.client.GithubUserClient;
import com.example.git_job.auth.client.dto.GithubTokenResponse;
import com.example.git_job.auth.client.dto.GithubUserResponse;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.JwtTokenProvider;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class GithubOAuthServiceTest {

    private static final String STATE = "st_abcdefghijklmnop";
    private static final long GITHUB_ID = 583231L;
    private static final String TOKEN = "gho_token";

    @Mock
    private GithubOAuthClient githubOAuthClient;
    @Mock
    private GithubUserClient githubUserClient;
    @Mock
    private UserRepository userRepository;
    @Mock
    private JwtTokenProvider jwtTokenProvider;

    private GithubOAuthService service;

    @BeforeEach
    void setUp() {
        GithubOAuthProperties properties = new GithubOAuthProperties(
                "client-id", "client-secret",
                "http://localhost:8080/api/v1/auth/github/callback",
                "https://api.github.com",
                "http://localhost:8080/auth/callback",
                List.of("/onboarding/repositories", "/repos")
        );
        service = new GithubOAuthService(
                githubOAuthClient, githubUserClient, userRepository, properties, jwtTokenProvider
        );
        when(jwtTokenProvider.createToken(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenReturn("session-jwt");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(Duration.ofMinutes(30));
        when(userRepository.save(any(User.class))).thenAnswer(call -> call.getArgument(0));
    }

    private void givenGithubUser(String scope, String name, String email) {
        when(githubOAuthClient.exchangeCode("code"))
                .thenReturn(new GithubTokenResponse(TOKEN, "bearer", scope, null, null));
        when(githubUserClient.fetchUser(TOKEN))
                .thenReturn(new GithubUserResponse(GITHUB_ID, "octocat", name,
                        "https://avatars.githubusercontent.com/u/583231?v=4", email));
    }

    private static ErrorCode errorCodeOf(Throwable thrown) {
        return ((CustomException) thrown).getErrorCode();
    }

    @Nested
    @DisplayName("로그인 진입")
    class StartLogin {

        @BeforeEach
        void stubAuthorizeUrl() {
            when(githubOAuthClient.buildAuthorizeUrl(anyString()))
                    .thenReturn("https://github.com/login/oauth/authorize");
        }

        @Test
        @DisplayName("state는 st_ 접두사를 가지며 매 요청마다 새로 생성된다")
        void generatesFreshState() {
            String first = service.startLogin(null).state();
            String second = service.startLogin(null).state();

            assertThat(first).startsWith("st_");
            assertThat(first).isNotEqualTo(second);
        }

        @Test
        @DisplayName("redirectTo가 없으면 허용 목록의 첫 항목을 기본 목적지로 쓴다")
        void fallsBackToDefaultRedirect() {
            assertThat(service.startLogin(null).redirectTo()).isEqualTo("/onboarding/repositories");
            assertThat(service.startLogin("/repos").redirectTo()).isEqualTo("/repos");
        }

        @Test
        @DisplayName("허용 목록에 없는 redirectTo는 AUTH-400-1로 거부한다")
        void rejectsUnlistedRedirect() {
            assertThatThrownBy(() -> service.startLogin("//evil.com"))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_REDIRECT_NOT_ALLOWED));
        }
    }

    @Nested
    @DisplayName("콜백 · state 검증")
    class StateVerification {

        @Test
        @DisplayName("쿠키가 없으면 우리가 시작한 흐름이 아니므로 CSRF로 간주한다")
        void rejectsMissingCookie() {
            assertThatThrownBy(() -> service.completeLogin("code", STATE, null))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_INVALID_STATE));

            verify(githubOAuthClient, never()).exchangeCode(anyString());
        }

        @Test
        @DisplayName("쿼리와 쿠키의 state가 다르면 거부하고 code 교환을 시도하지 않는다")
        void rejectsMismatchedState() {
            assertThatThrownBy(() -> service.completeLogin("code", STATE, "st_other"))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_INVALID_STATE));

            verify(githubOAuthClient, never()).exchangeCode(anyString());
        }

        @Test
        @DisplayName("code가 없으면 거부한다")
        void rejectsMissingCode() {
            assertThatThrownBy(() -> service.completeLogin(null, STATE, STATE))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_INVALID_STATE));
        }
    }

    @Nested
    @DisplayName("콜백 · 승인된 scope 검증")
    class ScopeVerification {

        @Test
        @DisplayName("repo를 승인하지 않으면 AUTH-403-4로 거부하고 사용자를 만들지 않는다")
        void rejectsPartialGrant() {
            givenGithubUser("read:user", "The Octocat", "octocat@github.com");

            assertThatThrownBy(() -> service.completeLogin("code", STATE, STATE))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_SCOPE_NOT_GRANTED));

            verify(userRepository, never()).save(any(User.class));
        }

        @Test
        @DisplayName("scope가 비어 있으면 거부한다")
        void rejectsEmptyScope() {
            givenGithubUser(null, "The Octocat", "octocat@github.com");

            assertThatThrownBy(() -> service.completeLogin("code", STATE, STATE))
                    .isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(errorCodeOf(thrown))
                            .isEqualTo(ErrorCode.OAUTH_SCOPE_NOT_GRANTED));
        }

        @Test
        @DisplayName("순서와 공백이 달라도 필요한 scope가 모두 있으면 통과한다")
        void acceptsAnyOrder() {
            givenGithubUser("repo, read:user", "The Octocat", "octocat@github.com");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.empty());

            assertThat(service.completeLogin("code", STATE, STATE).sessionToken())
                    .isEqualTo("session-jwt");
        }
    }

    @Nested
    @DisplayName("콜백 · 사용자 등록과 식별")
    class UserUpsert {

        @Test
        @DisplayName("신규 사용자는 github_id 기준으로 등록된다")
        void registersNewUser() {
            givenGithubUser("read:user,repo", "The Octocat", "octocat@github.com");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.empty());

            GithubOAuthService.LoginSession session = service.completeLogin("code", STATE, STATE);

            assertThat(session.sessionToken()).isEqualTo("session-jwt");
            assertThat(session.maxAge()).isEqualTo(Duration.ofMinutes(30));
            verify(userRepository).save(any(User.class));
        }

        @Test
        @DisplayName("기존 사용자는 새로 만들지 않고 최신 정보로 갱신한다")
        void updatesExistingUser() {
            givenGithubUser("read:user,repo", "The Octocat", "new@github.com");
            User existing = User.register(GITHUB_ID, "old-login", "Old Name",
                    "old@github.com", "https://old", "read:user", "old-token");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.of(existing));

            service.completeLogin("code", STATE, STATE);

            verify(userRepository, never()).save(any(User.class));
            assertThat(existing.getGithubLogin()).isEqualTo("octocat");
            assertThat(existing.getEmail()).isEqualTo("new@github.com");
            assertThat(existing.getGrantedScopes()).isEqualTo("read:user,repo");
            assertThat(existing.getAccessToken()).isEqualTo(TOKEN);
        }

        @Test
        @DisplayName("GitHub name이 없으면 login으로 채운다 — user.name은 NOT NULL이다")
        void fallsBackToLoginWhenNameMissing() {
            givenGithubUser("read:user,repo", null, "octocat@github.com");
            User existing = User.register(GITHUB_ID, "octocat", "Old",
                    null, null, "read:user,repo", "old-token");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.of(existing));

            service.completeLogin("code", STATE, STATE);

            assertThat(existing.getName()).isEqualTo("octocat");
        }
    }

    @Nested
    @DisplayName("콜백 · 이메일 확보")
    class EmailResolution {

        @Test
        @DisplayName("GitHub이 email을 주지 않으면 /user/emails에서 primary·verified를 찾는다")
        void fallsBackToEmailsApi() {
            givenGithubUser("read:user,repo", "The Octocat", null);
            when(githubUserClient.fetchPrimaryVerifiedEmail(TOKEN)).thenReturn("primary@github.com");
            User existing = User.register(GITHUB_ID, "octocat", "The Octocat",
                    null, null, "read:user,repo", "old-token");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.of(existing));

            service.completeLogin("code", STATE, STATE);

            assertThat(existing.getEmail()).isEqualTo("primary@github.com");
        }

        @Test
        @DisplayName("이메일을 끝까지 못 구해도 로그인은 성공한다 — email은 nullable이다")
        void succeedsWithoutEmail() {
            givenGithubUser("read:user,repo", "The Octocat", null);
            when(githubUserClient.fetchPrimaryVerifiedEmail(TOKEN)).thenReturn(null);
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.empty());

            assertThat(service.completeLogin("code", STATE, STATE).sessionToken())
                    .isEqualTo("session-jwt");
        }

        @Test
        @DisplayName("email이 이미 있으면 /user/emails를 호출하지 않는다")
        void skipsEmailsApiWhenPresent() {
            givenGithubUser("read:user,repo", "The Octocat", "octocat@github.com");
            when(userRepository.findByGithubId(GITHUB_ID)).thenReturn(Optional.empty());

            service.completeLogin("code", STATE, STATE);

            verify(githubUserClient, never()).fetchPrimaryVerifiedEmail(anyString());
        }
    }
}
