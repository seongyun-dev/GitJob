package com.example.git_job.auth.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

/**
 * GitHub 계정으로 식별되는 서비스 사용자 (GH-AUTH-001).
 *
 * <p>식별 키는 {@code githubId}다. {@code githubLogin}은 사용자가 GitHub에서
 * 변경할 수 있어 기준으로 쓸 수 없고, 표시·API 호출용으로만 보관한다.</p>
 *
 * <p>{@code user}는 PostgreSQL 예약어라 테이블명을 따옴표로 감싼다.</p>
 */
@Entity
@Table(name = "\"user\"")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "user_id")
    private Long userId;

    @Column(name = "github_id", nullable = false, unique = true)
    private Long githubId;

    @Column(name = "github_login", nullable = false, length = 100)
    private String githubLogin;

    @Column(name = "name", nullable = false, length = 100)
    private String name;

    /** GitHub 이메일을 비공개로 둔 사용자는 값이 없다. */
    @Column(name = "email", length = 100)
    private String email;

    @Column(name = "avatar_url", length = 255)
    private String avatarUrl;

    /** GitHub이 실제로 승인한 scope. 요청값과 다를 수 있으므로 응답값을 저장한다. */
    @Column(name = "granted_scopes", length = 255)
    private String grantedScopes;

    /**
     * TODO([BE] Access Token 암호화 저장 티켓): 현재 평문 컬럼이다.
     *  {@code access_token_enc}로 옮기고 AesBytesEncryptor를 적용하는 것은 별도 티켓이며,
     *  그때까지 이 값은 응답·로그·이벤트에 절대 싣지 않는다.
     */
    @Column(name = "access_token", columnDefinition = "TEXT")
    private String accessToken;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private Instant updatedAt;

    private User(
            Long githubId,
            String githubLogin,
            String name,
            String email,
            String avatarUrl,
            String grantedScopes,
            String accessToken
    ) {
        this.githubId = githubId;
        this.githubLogin = githubLogin;
        this.name = name;
        this.email = email;
        this.avatarUrl = avatarUrl;
        this.grantedScopes = grantedScopes;
        this.accessToken = accessToken;
    }

    public static User register(
            Long githubId,
            String githubLogin,
            String name,
            String email,
            String avatarUrl,
            String grantedScopes,
            String accessToken
    ) {
        return new User(githubId, githubLogin, name, email, avatarUrl, grantedScopes, accessToken);
    }

    /**
     * 재로그인 시 GitHub 쪽 최신 값으로 갱신한다. {@code githubId}는 불변이므로 받지 않는다.
     *
     * <p>{@code email}은 null로 덮어쓰지 않는다. 사용자가 로그인 후에 이메일을 비공개로
     * 바꾸면 GitHub이 null을 주는데, 그 때문에 이미 확보한 주소를 잃을 이유는 없다.</p>
     */
    public void syncFromGithub(
            String githubLogin,
            String name,
            String email,
            String avatarUrl,
            String grantedScopes,
            String accessToken
    ) {
        this.githubLogin = githubLogin;
        this.name = name;
        if (email != null && !email.isBlank()) {
            this.email = email;
        }
        this.avatarUrl = avatarUrl;
        this.grantedScopes = grantedScopes;
        this.accessToken = accessToken;
    }
}
