package com.example.git_job.compute.store;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
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

    @Test
    @DisplayName("계산 attempt는 lease, backoff, terminal 상태를 원자적으로 지킨다")
    void computeAttemptLifecycleIsBounded() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
            String target = "BACKEND|서울|신입";

            ComputeAttempt first = store.tryStartAttempt(userId, target, EVIDENCE_VERSION, now,
                    now.plusSeconds(30), 3).orElseThrow();
            assertThat(first.attemptCount()).isEqualTo(1);
            assertThat(store.tryStartAttempt(userId, target, EVIDENCE_VERSION, now.plusSeconds(1),
                    now.plusSeconds(31), 3)).isEmpty();
            assertThat(store.dueAttempts(now.plusSeconds(1), 20)).isEmpty();
            assertThat(store.dueAttempts(now.plusSeconds(31), 20))
                    .extracting(ComputeAttempt::userId)
                    .containsExactly(userId);

            store.markRetrying(first, "COMPUTE_RETRYING", now.plusSeconds(10), now);
            ComputeAttempt second = store.tryStartAttempt(userId, target, EVIDENCE_VERSION,
                    now.plusSeconds(11), now.plusSeconds(41), 3).orElseThrow();
            assertThat(second.attemptCount()).isEqualTo(2);

            store.markRetrying(second, "COMPUTE_RETRYING", now.plusSeconds(20),
                    now.plusSeconds(12));
            ComputeAttempt third = store.tryStartAttempt(userId, target, EVIDENCE_VERSION,
                    now.plusSeconds(21), now.plusSeconds(51), 3).orElseThrow();
            assertThat(third.attemptCount()).isEqualTo(3);

            // 세 번째 실행이 process 종료로 상태를 못 남겨도 lease가 끝난 다음 claim이
            // 그 행을 terminal로 닫고 네 번째 outbound는 시작하지 않는다.
            ComputeAttempt exhausted = store.tryStartAttempt(userId, target, EVIDENCE_VERSION,
                    now.plusSeconds(60), now.plusSeconds(90), 3).orElseThrow();
            assertThat(exhausted.failed()).isTrue();
            assertThat(exhausted.reason()).isEqualTo("COMPUTE_RETRY_EXHAUSTED");

            String terminalEvidence = "b".repeat(64);
            ComputeAttempt permanent = store.tryStartAttempt(userId, target, terminalEvidence,
                    now, now.plusSeconds(30), 3).orElseThrow();
            store.markFailed(permanent, "COMPUTE_INVALID_INPUT", now.plusSeconds(1));
            assertThat(store.tryStartAttempt(userId, target, terminalEvidence,
                    now.plusSeconds(60), now.plusSeconds(90), 3)).isEmpty();
            assertThat(store.findAttempt(userId, target, EVIDENCE_VERSION).orElseThrow().failed())
                    .isTrue();
            // 다른 identity의 terminal 상태를 현재 요청이 임의로 삭제하지 않는다.
            assertThat(store.findAttempt(userId, target, terminalEvidence)).isPresent();
        });
    }

    @Test
    @DisplayName("삭제 뒤 재생성된 같은 attempt를 이전 worker가 덮어쓰지 못한다")
    void staleWorkerCannotOverwriteRecreatedAttempt() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
            String target = "BACKEND|서울|신입";

            ComputeAttempt staleWorker = store.tryStartAttempt(userId, target, EVIDENCE_VERSION,
                    now, now.plusSeconds(30), 3).orElseThrow();
            jdbc.update("""
                    DELETE FROM user_c_compute_attempt
                    WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                    """, userId, target, EVIDENCE_VERSION);
            ComputeAttempt replacement = store.tryStartAttempt(userId, target, EVIDENCE_VERSION,
                    now.plusSeconds(1), now.plusSeconds(31), 3).orElseThrow();
            assertThat(replacement.attemptCount()).isEqualTo(staleWorker.attemptCount());

            store.deleteAttempt(staleWorker);
            assertThat(store.findAttempt(userId, target, EVIDENCE_VERSION)).contains(replacement);

            store.markFailed(staleWorker, "COMPUTE_UNAVAILABLE", now.plusSeconds(2));

            assertThat(store.findAttempt(userId, target, EVIDENCE_VERSION).orElseThrow().status())
                    .isEqualTo("RUNNING");
        });
    }

    @Test
    @DisplayName("기여 판정과 계보가 준비된 사용자만 복구하고 구형 사용자가 배치를 막지 않는다")
    void findsUsersMissingComputeState() throws Exception {
        withDatabase((jdbc, userId) -> {
            ComputeSnapshotStore store = new ComputeSnapshotStore(jdbc);
            UserTargetStore targets = new UserTargetStore(jdbc);
            Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
            String targetKey = targets.save(userId, "BACKEND", List.of("서울"),
                    List.of("신입"), now).targetKey();
            jdbc.update("""
                    INSERT INTO analysis_job
                        (analysis_id, user_id, repository_id, branch_name, commit_sha,
                         status, current_stage, requested_at, completed_at,
                         registry_version, rule_pack_version, compute_ready_at)
                    VALUES (?, ?, ?, 'main', ?, 'SUCCEEDED', 'DONE', ?, ?,
                            'registry-20260911.4', 'rule-pack-20260911.4', NULL)
                    """, "analysis-recovery", userId, "repository-1", "a".repeat(40),
                    java.sql.Timestamp.from(now.minusSeconds(60)), java.sql.Timestamp.from(now));

            // SUCCEEDED 저장과 기여 판정 사이에는 실제로 시간이 있다. 그 구간의 분석을
            // 먼저 계산하면 개인 판정 없는 Snapshot이 결정론적 event ID로 고정된다.
            assertThat(store.usersMissingComputeState(20)).isEmpty();
            jdbc.update("UPDATE analysis_job SET compute_ready_at = ? WHERE analysis_id = ?",
                    java.sql.Timestamp.from(now.plusSeconds(1)), "analysis-recovery");
            assertThat(store.usersMissingComputeState(20)).containsExactly(userId);

            // 사용자의 다른 저장소에 계보 없는 구형 분석이 남아 있어도, 조립기는 그
            // 저장소를 data gap으로 제외하고 계보가 있는 최신 분석으로 PARTIAL 계산한다.
            // 복구 조회도 같은 계약을 따라야 기존 사용자 하나가 영구 PREPARING에 갇히지
            // 않는다.
            jdbc.update("""
                    INSERT INTO analysis_job
                        (analysis_id, user_id, repository_id, branch_name, commit_sha,
                         status, current_stage, requested_at, completed_at, compute_ready_at)
                    VALUES (?, ?, ?, 'main', ?, 'SUCCEEDED', 'DONE', ?, ?, ?)
                    """, "analysis-legacy-sibling", userId, "repository-legacy",
                    "c".repeat(40), java.sql.Timestamp.from(now.minusSeconds(120)),
                    java.sql.Timestamp.from(now.minusSeconds(90)),
                    java.sql.Timestamp.from(now.minusSeconds(89)));
            assertThat(store.usersMissingComputeState(20)).containsExactly(userId);

            // 계보가 없는 v1 분석은 synchronize()가 attempt를 만들지 못한다. LIMIT 앞의
            // 20명을 이들이 차지해도 뒤의 정상 사용자가 영구 기아 상태가 되면 안 된다.
            for (int index = 0; index < 20; index++) {
                Long legacyUser = jdbc.queryForObject("""
                        INSERT INTO "user" (github_id, github_login, name)
                        VALUES (?, ?, ?) RETURNING user_id
                        """, Long.class, 10_000L + index, "legacy-" + index,
                        "Legacy " + index);
                targets.save(legacyUser, "BACKEND", List.of(), List.of(),
                        now.minusSeconds(3_600L + index));
                jdbc.update("""
                        INSERT INTO analysis_job
                            (analysis_id, user_id, repository_id, branch_name, commit_sha,
                             status, current_stage, requested_at, completed_at, compute_ready_at)
                        VALUES (?, ?, ?, 'main', ?, 'SUCCEEDED', 'DONE', ?, ?, ?)
                        """, "legacy-analysis-" + index, legacyUser,
                        "legacy-repository-" + index, "b".repeat(40),
                        java.sql.Timestamp.from(now.minusSeconds(7_200L + index)),
                        java.sql.Timestamp.from(now.minusSeconds(3_600L + index)),
                        java.sql.Timestamp.from(now.minusSeconds(3_599L + index)));
            }
            assertThat(store.usersMissingComputeState(20)).containsExactly(userId);

            ComputeAttempt attempt = store.tryStartAttempt(userId, targetKey, EVIDENCE_VERSION,
                    now, now.plusSeconds(30), 3).orElseThrow();
            assertThat(store.usersMissingComputeState(20)).isEmpty();

            store.clearAttempt(attempt);
            store.save(snapshot(userId, EVIDENCE_VERSION, "ev-recovered", now.plusSeconds(1)));
            assertThat(store.usersMissingComputeState(20)).isEmpty();
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
