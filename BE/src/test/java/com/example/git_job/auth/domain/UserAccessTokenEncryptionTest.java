package com.example.git_job.auth.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.example.git_job.auth.repository.UserRepository;
import jakarta.persistence.EntityManager;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.annotation.Transactional;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * 토큰이 정말로 암호화되어 저장되는지, 실제 PostgreSQL 에 써 보고 확인한다.
 *
 * <h2>왜 단위 테스트로 부족한가</h2>
 *
 * <p>{@code EncryptedStringConverterTest} 는 변환기를 직접 만들어 쓴다. 운영에서는
 * Hibernate 가 변환기 인스턴스를 만드는데, Spring 이 끼워 준 빈 컨테이너를 통해
 * 가져오지 못하면 생성자 주입이 안 된다. 그 경우 컨텍스트 기동이 실패하거나
 * 암호기 없이 동작하게 되는데, 어느 쪽이든 이 테스트가 잡는다.</p>
 *
 * <p>컬럼의 <b>원시 바이트</b>를 JDBC 로 직접 읽는 것이 이 테스트의 핵심이다.
 * 엔티티로만 확인하면 변환기가 양방향에서 아무것도 안 해도 통과한다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@SpringBootTest(properties = {
        "spring.kafka.listener.auto-startup=false",
        "encryption.symmetric-key=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "encryption.salt=5c0744940b5c369b"
})
@Transactional
class UserAccessTokenEncryptionTest {

    private static final String TOKEN = "gho_16C7e42F292c6912E7710c838347Ae178B4a";
    private static final long GITHUB_ID = 90_210L;

    private static final PostgreSQLContainer POSTGRES =
            new PostgreSQLContainer("postgres:16.4-alpine");

    static {
        POSTGRES.start();
    }

    /**
     * 개발용 DB 를 쓰지 않는다. 이 테스트는 사용자 행을 쓰고, Flyway 가 붙어 있어
     * 마이그레이션도 돌린다. 남의 데이터 위에서 할 일이 아니다.
     */
    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Autowired
    private UserRepository users;

    @Autowired
    private EntityManager entityManager;

    @Autowired
    private JdbcTemplate jdbc;

    private User saveUser(String accessToken) {
        User saved = users.save(User.register(
                GITHUB_ID, "octocat", "The Octocat", null, null, "read:user,repo", accessToken));
        // 영속성 컨텍스트에서 그대로 돌려받으면 변환기를 한 번도 거치지 않는다.
        entityManager.flush();
        entityManager.clear();
        return saved;
    }

    @Test
    @DisplayName("컬럼에는 암호문이 들어가고 엔티티로는 평문이 나온다")
    void theColumnHoldsCiphertextAndTheEntityHoldsPlaintext() {
        saveUser(TOKEN);

        byte[] stored = jdbc.queryForObject(
                "SELECT access_token_enc FROM \"user\" WHERE github_id = ?",
                byte[].class, GITHUB_ID);

        assertNotNull(stored);
        assertFalse(new String(stored, StandardCharsets.UTF_8).contains("gho_"),
                "평문이 컬럼에 남아 있다 -- 변환기가 동작하지 않았다");
        assertEquals(TOKEN, users.findByGithubId(GITHUB_ID).orElseThrow().getAccessToken());
    }

    @Test
    @DisplayName("난수 IV 만큼 길어진다")
    void theStoredValueIsLongerThanThePlaintext() {
        // AES-GCM 은 IV 16바이트와 인증 태그 16바이트를 함께 싣는다. 길이가 원문
        // 그대로면 무언가가 암호화를 건너뛴 것이다.
        saveUser(TOKEN);

        byte[] stored = jdbc.queryForObject(
                "SELECT access_token_enc FROM \"user\" WHERE github_id = ?",
                byte[].class, GITHUB_ID);

        assertEquals(TOKEN.getBytes(StandardCharsets.UTF_8).length + 32, stored.length);
    }

    @Test
    @DisplayName("토큰이 없는 사용자는 NULL 로 남는다")
    void aUserWithoutATokenStaysNull() {
        // GitHub 연결을 하지 않은 사용자는 빈 암호문 대신 NULL이어야 한다.
        saveUser(null);

        assertNull(jdbc.queryForObject(
                "SELECT access_token_enc FROM \"user\" WHERE github_id = ?",
                byte[].class, GITHUB_ID));
        assertNull(users.findByGithubId(GITHUB_ID).orElseThrow().getAccessToken());
    }
}
