package com.example.git_job.compute.store;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * V15의 두 테이블과 그 위의 SQL을 실제 PostgreSQL로 확인한다 (S15P21E102-279).
 *
 * <p>H2로는 검증되지 않는 것들이 있다. {@code ON CONFLICT DO NOTHING}이 어느 제약까지
 * 덮는지, {@code CHECK} 정규식이 실제로 거는지, upsert가 기대한 열만 바꾸는지가 그렇다.
 * 그리고 이 테이블의 존재 이유가 <b>중복 계산 방지</b>이므로, 제약이 실제로 두 번째
 * 저장을 막는지는 문서가 아니라 DB에 물어야 한다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
class ComputeStoreIntegrationTest {

    private static final String EVIDENCE_VERSION = "a".repeat(64);
    private static final String COHORT = "c-" + "1".repeat(64);
    private static final String DEMAND = "c-" + "2".repeat(64);
    private static final String RECOMMENDATION = "c-" + "3".repeat(64);

    @Test
    @DisplayName("목표 직무는 전량 교체되고 같은 조건이면 같은 캐시 키를 만든다")
    void savesAndNormalizesTarget() throws Exception {
        withDatabase((jdbc, userId) -> {
            UserTargetStore store = new UserTargetStore(jdbc);

            // timestamptz 는 마이크로초까지만 담는다. 나노초를 그대로 넣으면 읽은 값이
            // 쓴 값과 달라져, 정규화 검증이 아니라 정밀도 차이로 테스트가 깨진다.
            Target saved = store.save(userId, " BACKEND ", List.of("서울", " 서울 ", ""),
                    List.of("신입"), Instant.now().truncatedTo(ChronoUnit.MICROS));

            // 공백과 중복이 살아 있으면 같은 조건이 다른 캐시 키를 만들어 결과가 두 벌 생긴다.
            assertThat(saved.targetRole()).isEqualTo("BACKEND");
            assertThat(saved.regions()).containsExactly("서울");
            assertThat(saved.targetKey()).isEqualTo("BACKEND|서울|신입");
            assertThat(store.find(userId)).contains(saved);

            // 필터를 지우는 것도 선택이다. 부분 갱신이면 지울 방법이 없다.
            Target replaced = store.save(userId, "FRONTEND", List.of(), List.of(),
                    Instant.now().truncatedTo(ChronoUnit.MICROS));
            assertThat(store.find(userId).orElseThrow().targetKey())
                    .isEqualTo("FRONTEND||")
                    .isEqualTo(replaced.targetKey());
        });
    }

    @Test
    @DisplayName("같은 event는 두 번 저장되지 않는다")
    void eventIdIsUnique() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            ComputeSnapshot snapshot = snapshot(userId, EVIDENCE_VERSION, "ev-1", Instant.now());

            assertThat(store.save(snapshot)).isTrue();
            // Kafka 재배달과 서버 재시작이 정상 경로다. 두 번째 저장은 조용히 무시돼야 한다.
            assertThat(store.save(snapshot)).isFalse();
            assertThat(store.findByEventId("ev-1")).contains(snapshot);
        });
    }

    @Test
    @DisplayName("Evidence가 달라도 event ID가 같으면 저장되지 않는다")
    void uniqueEventIdCoversDifferentRows() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            store.save(snapshot(userId, EVIDENCE_VERSION, "ev-1", Instant.now()));

            // 기본키는 다르지만 event ID 가 같다. ON CONFLICT DO NOTHING 이 대상 제약을
            // 지정하지 않으므로 UNIQUE(event_id) 위반도 예외가 아니라 무시로 끝난다.
            boolean inserted = store.save(snapshot(userId, "b".repeat(64), "ev-1", Instant.now()));

            assertThat(inserted).isFalse();
        });
    }

    @Test
    @DisplayName("같은 목표 직무의 최신 결과를 고른다")
    void findsLatestPerTarget() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            Instant earlier = Instant.now().minus(1, ChronoUnit.HOURS);
            store.save(snapshot(userId, EVIDENCE_VERSION, "ev-old", earlier));
            ComputeSnapshot newer = snapshot(userId, "b".repeat(64), "ev-new", Instant.now());
            store.save(newer);

            // 저장소를 하나 더 분석하면 evidence_version 이 바뀌어 행이 하나 더 생긴다.
            // 화면은 그중 최신을 봐야 한다.
            assertThat(store.findLatest(userId, "BACKEND|서울|신입").orElseThrow().eventId())
                    .isEqualTo("ev-new");
            assertThat(store.findLatest(userId, "FRONTEND||")).isEmpty();
        });
    }

    private static ComputeSnapshot snapshot(long userId, String evidenceVersion, String eventId,
                                            Instant computedAt) {
        return new ComputeSnapshot(userId, evidenceVersion, COHORT, DEMAND, RECOMMENDATION,
                eventId, "BACKEND|서울|신입", computedAt.truncatedTo(ChronoUnit.MICROS));
    }

    /** 마이그레이션을 전부 적용한 빈 DB와 사용자 한 명을 만들어 준다. */
    private static void withDatabase(DatabaseTest test) throws Exception {
        try (var postgres = new PostgreSQLContainer("postgres:16.4-alpine")) {
            postgres.start();
            Flyway.configure()
                    .dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                    .locations("classpath:db/migration")
                    .load()
                    .migrate();

            DataSource dataSource = new DriverManagerDataSource(postgres.getJdbcUrl(),
                    postgres.getUsername(), postgres.getPassword());
            JdbcTemplate jdbc = new JdbcTemplate(dataSource);
            // 두 테이블 모두 user 를 참조한다. 없는 사용자로 저장하려 하면 FK 가 막는다.
            Long userId = jdbc.queryForObject("""
                    INSERT INTO "user" (github_id, github_login, name)
                    VALUES (4242, 'compute-user', 'Compute User')
                    RETURNING user_id
                    """, Long.class);
            test.run(jdbc, userId);
        }
    }

    @FunctionalInterface
    private interface DatabaseTest {
        void run(JdbcTemplate jdbc, long userId) throws Exception;
    }
}
