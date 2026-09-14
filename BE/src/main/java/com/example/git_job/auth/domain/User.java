package com.example.git_job.auth.domain;

import com.example.git_job.global.crypto.EncryptedStringConverter;
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.EnumType;
import jakarta.persistence.Entity;
import jakarta.persistence.Enumerated;
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

    /**
     * GitHub 프로필의 사람 이름. 프로필에 없으면 <b>빈 문자열</b>이다.
     *
     * <p>GitHub은 프로필 이름을 선택 항목으로 두어 미설정 계정에 {@code null}을 준다.
     * 그때 {@code githubLogin}으로 때우지 않는다 — B조 API 명세서 {@code GET /api/v1/me}가
     * {@code githubLogin}과 {@code name}을 별도 필드로 내려주므로, 핸들을 여기 넣으면
     * 명세가 구분해 둔 두 값이 같아진다.</p>
     *
     * <p>{@code null}이 아니라 빈 문자열인 것은 스키마를 바꾸지 않기 위해서다. 컬럼이
     * {@code NOT NULL}인데 그 제약은 V1 baseline이 정한 것이고, 마이그레이션을 하나 더
     * 쌓는 것보다 빈 값으로 두는 편이 싸다. 표시용 대체는 FE가 정한다 — FE는
     * {@code githubLogin}을 함께 받으므로 falsy 판정 한 번이면 된다.</p>
     */
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
     * GitHub Access Token. 컬럼에는 AES-GCM 암호문이 들어간다(V12).
     *
     * <p>필드는 평문 {@code String}이고 변환은 {@link EncryptedStringConverter}가
     * 저장·조회 시점에만 한다. 그래서 이 값을 쓰는 코드는 달라지지 않는다.</p>
     *
     * <p>암호화했다고 해서 노출해도 되는 값이 아니다. 메모리 위에서는 평문이므로
     * <b>응답·로그·이벤트에 절대 싣지 않는다.</b> 분석 요청 이벤트가 토큰 대신
     * {@code analysis_repository_id}를 싣는 것도 같은 이유다.</p>
     *
     * <p>암호문은 매번 달라지므로 이 컬럼으로 조회할 수 없다.</p>
     *
     * <p><b>V12 이전의 평문은 디스크에서 지워지지 않았다.</b> PostgreSQL 의 DROP
     * COLUMN 은 논리적 삭제라 힙 튜플의 바이트가 그대로 남고, 그 튜플이 다시
     * 쓰이기 전까지(UPDATE · VACUUM FULL · CLUSTER) 회수할 수 있다. 이미 만들어진
     * WAL 세그먼트와 베이스 백업에도 남아 있다. 즉 V12 가 없앤 것은 "애플리케이션
     * 경로로 읽히는 평문"이지 "디스크 위의 평문"이 아니다.</p>
     *
     * <p>완전히 지우려면 {@code VACUUM FULL "user"} 후 기존 백업과 WAL 을 폐기해야
     * 한다. 마이그레이션에 넣지 않은 것은 VACUUM FULL 이 트랜잭션 안에서 실행될 수
     * 없고(Flyway 가 마이그레이션을 트랜잭션으로 감싼다) ACCESS EXCLUSIVE 락을
     * 잡기 때문이다 -- 운영 절차로 다룰 일이다.</p>
     */
    @Convert(converter = EncryptedStringConverter.class)
    @Column(name = "access_token_enc")
    private String accessToken;

    /**
      * 권한. DB 에서만 바뀐다 -- 로그인 흐름은 이 값을 읽기만 하고, 승격은
      * 운영자가 직접 UPDATE 한다. 설정 파일의 허용 목록으로 하면 누가 관리자인지가
      * 배포 산출물에 박히고 사람이 바뀔 때마다 재배포해야 한다.
      */
    @Enumerated(EnumType.STRING)
    @Column(name = "role", nullable = false, length = 16)
    private Role role = Role.USER;

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
        this.name = blankIfMissing(name);
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
     *
     * <p><b>{@code name}은 재로그인에서 덮어쓰지 않는다.</b> 콜백 명세는 "사용자를
     * 생성·연결한 뒤 세션을 발급한다"까지만 규정한다. 최초 연동이 회원가입이고 그 뒤
     * 로그인은 식별과 세션 발급이므로, 가입 때 정해진 이름을 매번 GitHub 값으로
     * 되돌리지 않는다.</p>
     *
     * <p>예외는 비어 있을 때뿐이다. GitHub 프로필에 이름이 없는 상태로 가입한 뒤
     * 나중에 채운 경우인데, 이건 있던 값을 바꾸는 게 아니라 빈칸을 메우는 것이다.</p>
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
        if (this.name.isBlank()) {
            this.name = blankIfMissing(name);
        }
        if (email != null && !email.isBlank()) {
            this.email = email;
        }
        this.avatarUrl = avatarUrl;
        this.grantedScopes = grantedScopes;
        this.accessToken = accessToken;
    }

    /**
     * 컬럼이 {@code NOT NULL}이라 null을 넣을 수 없다. GitHub이 프로필 이름을 주지
     * 않았다는 사실을 빈 문자열로 표현한다. {@code githubLogin}으로 때우지 않는 것이
     * 핵심이다 — 그러면 명세가 나눈 두 필드가 같은 값이 된다.
     */
    private static String blankIfMissing(String name) {
        return name == null || name.isBlank() ? "" : name;
    }
}
