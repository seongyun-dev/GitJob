package com.example.git_job.compute.store;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * C 계산 결과 Snapshot의 pointer (S15P21E102-279).
 *
 * <p>ID만 보관한다. 계산 결과 본문은 C가 소유하고 조회할 때마다 C에 묻는다. 여기에
 * 복제하면 두 곳이 어긋나는 순간 화면이 어느 쪽을 믿어야 할지 알 수 없어진다.</p>
 *
 * <h2>중복 계산을 막는 자리</h2>
 *
 * <p>{@code event_id}는 결정론적이라 같은 상황이면 같은 값이 나온다. 계산 전에
 * {@link #findByEventId(String)}로 한 번 막고, 경합해서 둘 다 통과하더라도 UNIQUE 제약이
 * 두 번째 저장을 무시한다. Kafka 재배달과 서버 재시작이 정상 경로이므로 두 겹이 필요하다.</p>
 */
@Repository
public class ComputeSnapshotStore {

    /**
     * 이 값이 바뀌면 저장된 Snapshot을 가진 사용자가 다시 계산 대상이 된다.
     * {@link #usersMissingComputeState(String, int)}가 이 문자열로 걸러내기 때문이다.
     *
     * <p>{@code recommendation-vN}은 C의 {@code RECOMMENDATION_ALGORITHM_VERSION}을
     * 따라간다. S15P21E102-294에서 이 상수가 생길 때 C가 v6이었고 그때부터 같이
     * 움직인다. S15P21E102-354가 후보 자격 판정을 바꾸면서 C는 v7이 됐는데 이 값이
     * v6에 남아 있었다 -- 그러면 이미 v6으로 계산된 사용자는 스케줄러가 다시 집어
     * 올리지 않아 새 판정이 영영 반영되지 않는다. eventId에 C 버전이 들어가는 것은
     * 409 충돌을 막을 뿐, 이미 행이 있는 사용자를 다시 큐에 넣지는 않는다.</p>
     */
    public static final String CURRENT_COMPUTE_CONTRACT_VERSION =
            "active-matching/job-demand-v4+recommendation-v7";

    private static final RowMapper<ComputeSnapshot> MAPPER = (rs, row) -> new ComputeSnapshot(
            rs.getLong("user_id"),
            rs.getString("evidence_version"),
            rs.getString("cohort_snapshot_id"),
            rs.getString("demand_snapshot_id"),
            rs.getString("recommendation_snapshot_id"),
            rs.getString("event_id"),
            rs.getString("target_key"),
            rs.getString("compute_contract_version"),
            rs.getTimestamp("computed_at").toInstant());

    private static final RowMapper<ComputeAttempt> ATTEMPT_MAPPER = (rs, row) ->
            new ComputeAttempt(
                    rs.getLong("user_id"),
                    rs.getString("target_key"),
                    rs.getString("evidence_version"),
                    rs.getString("status"),
                    rs.getString("reason"),
                    rs.getInt("attempt_count"),
                    rs.getObject("run_token", UUID.class),
                    instantOrNull(rs.getTimestamp("next_retry_at")),
                    rs.getTimestamp("updated_at").toInstant());

    private static final String COLUMNS = """
            user_id, evidence_version, cohort_snapshot_id, demand_snapshot_id,
            recommendation_snapshot_id, event_id, target_key, compute_contract_version,
            computed_at
            """;

    private final JdbcTemplate jdbc;

    public ComputeSnapshotStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<ComputeSnapshot> findByEventId(String eventId) {
        return jdbc.query("SELECT " + COLUMNS + " FROM user_c_snapshot WHERE event_id = ?",
                MAPPER, eventId).stream().findFirst();
    }

    /**
     * 이 사용자의 이 목표 직무에서 가장 최근 결과.
     *
     * <p>공개 API가 읽는 경로다. Evidence가 늘어나면 행이 하나 더 생기므로 최신을 고른다.
     * 목표 직무를 바꿨다가 되돌린 경우, 이전 결과가 남아 있어 재계산 없이 바로 보인다.</p>
     */
    public Optional<ComputeSnapshot> findLatest(long userId, String targetKey) {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM user_c_snapshot
                WHERE user_id = ? AND target_key = ?
                ORDER BY computed_at DESC
                LIMIT 1
                """, MAPPER, userId, targetKey).stream().findFirst();
    }

    /**
     * 저장한다. 이미 있으면 아무것도 하지 않는다.
     *
     * @return 실제로 새 행이 생겼으면 {@code true}. 로그에서 "계산했다"와 "이미 있었다"를
     *         구분하는 데 쓴다.
     */
    public boolean save(ComputeSnapshot snapshot) {
        int inserted = jdbc.update("""
                INSERT INTO user_c_snapshot (user_id, evidence_version, cohort_snapshot_id,
                    demand_snapshot_id, recommendation_snapshot_id, event_id, target_key,
                    compute_contract_version, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                snapshot.userId(), snapshot.evidenceVersion(), snapshot.cohortSnapshotId(),
                snapshot.demandSnapshotId(), snapshot.recommendationSnapshotId(),
                snapshot.eventId(), snapshot.targetKey(), snapshot.computeContractVersion(),
                java.sql.Timestamp.from(snapshot.computedAt()));
        return inserted > 0;
    }

    public Optional<ComputeAttempt> findAttempt(long userId, String targetKey,
                                                String evidenceVersion) {
        return jdbc.query("""
                SELECT user_id, target_key, evidence_version, status, reason,
                       attempt_count, run_token, next_retry_at, updated_at
                FROM user_c_compute_attempt
                WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                """, ATTEMPT_MAPPER, userId, targetKey, evidenceVersion).stream().findFirst();
    }

    /** lease 또는 backoff가 끝난 정확한 실행. 실제 claim은 {@link #tryStartAttempt}가 한다. */
    public List<ComputeAttempt> dueAttempts(Instant now, int limit) {
        return jdbc.query("""
                SELECT user_id, target_key, evidence_version, status, reason,
                       attempt_count, run_token, next_retry_at, updated_at
                FROM user_c_compute_attempt
                WHERE status IN ('RUNNING', 'RETRYING') AND next_retry_at <= ?
                ORDER BY updated_at, user_id
                LIMIT ?
                """, ATTEMPT_MAPPER, java.sql.Timestamp.from(now), limit);
    }

    /**
     * 분석 완료 event를 놓쳐 계산 결과도 attempt도 생기지 않은 사용자.
     *
     * <p>V22 배포 전에 이미 분석이 끝난 사용자나, 분석 결과 저장 직후 프로세스가
     * 종료된 사용자가 대상이다. 최신 성공 분석의 기여 판정은 모두 끝나야 하지만,
     * 계보가 없는 구형 저장소는 조립기가 data gap으로 제외하므로 복구를 막지 않는다.
     * 대신 계보가 있는 최신 분석이 하나 이상이고 모두 같은 Rule Pack이어야 한다.
     * 계산 불가능한 v1 전용 사용자나 혼합 Rule Pack 사용자를 SQL에서 제외해야 LIMIT
     * 앞의 20명이 매 주기 같은 자리를 차지하지 않는다. snapshot 또는 attempt가 하나라도
     * 있으면 기존 결과 조회·재시도 경로가 소유하므로 여기서 다시 시작하지 않는다.</p>
     */
    public List<Long> usersMissingComputeState(int limit) {
        return usersMissingComputeState(CURRENT_COMPUTE_CONTRACT_VERSION, limit);
    }

    public List<Long> usersMissingComputeState(String computeContractVersion, int limit) {
        return jdbc.queryForList("""
                SELECT ut.user_id
                FROM user_target ut
                WHERE EXISTS (
                    SELECT 1
                    FROM analysis_job aj
                    WHERE aj.user_id = ut.user_id AND aj.status = 'SUCCEEDED'
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM analysis_job latest
                    WHERE latest.user_id = ut.user_id
                      AND latest.status = 'SUCCEEDED'
                      AND latest.analysis_id = (
                        SELECT candidate.analysis_id
                        FROM analysis_job candidate
                        WHERE candidate.user_id = latest.user_id
                          AND candidate.repository_id = latest.repository_id
                          AND candidate.status = 'SUCCEEDED'
                        ORDER BY candidate.completed_at DESC NULLS LAST
                        LIMIT 1
                      )
                      AND latest.compute_ready_at IS NULL
                  )
                  AND 1 = (
                    SELECT count(DISTINCT
                        (latest.registry_version, latest.rule_pack_version))
                    FROM analysis_job latest
                    WHERE latest.user_id = ut.user_id
                      AND latest.status = 'SUCCEEDED'
                      AND latest.analysis_id = (
                        SELECT candidate.analysis_id
                        FROM analysis_job candidate
                        WHERE candidate.user_id = latest.user_id
                          AND candidate.repository_id = latest.repository_id
                          AND candidate.status = 'SUCCEEDED'
                        ORDER BY candidate.completed_at DESC NULLS LAST
                        LIMIT 1
                      )
                      AND nullif(btrim(latest.registry_version), '') IS NOT NULL
                      AND nullif(btrim(latest.rule_pack_version), '') IS NOT NULL
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_c_snapshot snapshot
                    WHERE snapshot.user_id = ut.user_id
                      AND snapshot.target_key = ut.target_role || '|' || ut.regions || '|'
                                                || ut.career_levels
                      AND snapshot.compute_contract_version = ?
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_c_compute_attempt attempt
                    WHERE attempt.user_id = ut.user_id
                      AND attempt.target_key = ut.target_role || '|' || ut.regions || '|'
                                               || ut.career_levels
                )
                ORDER BY CASE WHEN EXISTS (
                    SELECT 1
                    FROM user_c_snapshot any_snapshot
                    WHERE any_snapshot.user_id = ut.user_id
                      AND any_snapshot.target_key = ut.target_role || '|' || ut.regions || '|'
                                                    || ut.career_levels
                ) THEN 1 ELSE 0 END,
                ut.updated_at, ut.user_id
                LIMIT ?
                """, Long.class, computeContractVersion, limit);
    }

    /** 스케줄러가 읽은 정확한 실행만 지운다. 이후 재생성된 행은 token이 달라 보존된다. */
    public void deleteAttempt(ComputeAttempt attempt) {
        jdbc.update("""
                DELETE FROM user_c_compute_attempt
                WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                  AND run_token = ?
                """, attempt.userId(), attempt.targetKey(), attempt.evidenceVersion(),
                attempt.runToken());
    }

    /**
     * backoff가 끝난 계산 하나를 원자적으로 claim한다.
     *
     * <p>분석 완료와 목표 변경이 동시에 들어와도 {@code RETURNING}을 받은 호출 하나만
     * C를 부른다. 영구 실패와 시도 상한을 넘은 행은 다시 열지 않는다.</p>
     */
    public Optional<ComputeAttempt> tryStartAttempt(long userId, String targetKey,
            String evidenceVersion, Instant now, Instant leaseUntil, int maxAttempts) {
        UUID runToken = UUID.randomUUID();
        return jdbc.query("""
                INSERT INTO user_c_compute_attempt
                    (user_id, target_key, evidence_version, status, reason, attempt_count,
                     run_token, next_retry_at, updated_at)
                VALUES (?, ?, ?, 'RUNNING', 'COMPUTING', 1, ?, ?, ?)
                ON CONFLICT (user_id, target_key, evidence_version) DO UPDATE SET
                    status = CASE WHEN user_c_compute_attempt.attempt_count >= ?
                                  THEN 'FAILED' ELSE 'RUNNING' END,
                    reason = CASE WHEN user_c_compute_attempt.attempt_count >= ?
                                  THEN 'COMPUTE_RETRY_EXHAUSTED' ELSE 'COMPUTING' END,
                    attempt_count = CASE WHEN user_c_compute_attempt.attempt_count >= ?
                                         THEN user_c_compute_attempt.attempt_count
                                         ELSE user_c_compute_attempt.attempt_count + 1 END,
                    run_token = CASE WHEN user_c_compute_attempt.attempt_count >= ?
                                     THEN user_c_compute_attempt.run_token
                                     ELSE EXCLUDED.run_token END,
                    next_retry_at = CASE WHEN user_c_compute_attempt.attempt_count >= ?
                                         THEN NULL ELSE EXCLUDED.next_retry_at END,
                    updated_at = EXCLUDED.updated_at
                WHERE user_c_compute_attempt.status <> 'FAILED'
                  AND (user_c_compute_attempt.next_retry_at IS NULL
                       OR user_c_compute_attempt.next_retry_at <= ?)
                RETURNING user_id, target_key, evidence_version, status, reason,
                          attempt_count, run_token, next_retry_at, updated_at
                """, ATTEMPT_MAPPER,
                userId, targetKey, evidenceVersion,
                runToken,
                java.sql.Timestamp.from(leaseUntil), java.sql.Timestamp.from(now),
                maxAttempts, maxAttempts, maxAttempts, maxAttempts, maxAttempts,
                java.sql.Timestamp.from(now)).stream().findFirst();
    }

    public void markRetrying(ComputeAttempt attempt, String reason, Instant nextRetryAt,
                             Instant now) {
        jdbc.update("""
                UPDATE user_c_compute_attempt
                SET status = 'RETRYING', reason = ?, next_retry_at = ?, updated_at = ?
                WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                  AND run_token = ? AND status = 'RUNNING'
                """, reason, java.sql.Timestamp.from(nextRetryAt), java.sql.Timestamp.from(now),
                attempt.userId(), attempt.targetKey(), attempt.evidenceVersion(),
                attempt.runToken());
    }

    public void markFailed(ComputeAttempt attempt, String reason, Instant now) {
        jdbc.update("""
                UPDATE user_c_compute_attempt
                SET status = 'FAILED', reason = ?, next_retry_at = NULL, updated_at = ?
                WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                  AND run_token = ? AND status = 'RUNNING'
                """, reason, java.sql.Timestamp.from(now), attempt.userId(), attempt.targetKey(),
                attempt.evidenceVersion(), attempt.runToken());
    }

    public void clearAttempt(ComputeAttempt attempt) {
        jdbc.update("""
                DELETE FROM user_c_compute_attempt
                WHERE user_id = ? AND target_key = ? AND evidence_version = ?
                  AND run_token = ? AND status = 'RUNNING'
                """, attempt.userId(), attempt.targetKey(), attempt.evidenceVersion(),
                attempt.runToken());
    }

    private static Instant instantOrNull(java.sql.Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    public record ComputeSnapshot(long userId, String evidenceVersion, String cohortSnapshotId,
            String demandSnapshotId, String recommendationSnapshotId, String eventId,
            String targetKey, String computeContractVersion, Instant computedAt) {

        public ComputeSnapshot(long userId, String evidenceVersion, String cohortSnapshotId,
                String demandSnapshotId, String recommendationSnapshotId, String eventId,
                String targetKey, Instant computedAt) {
            this(userId, evidenceVersion, cohortSnapshotId, demandSnapshotId,
                    recommendationSnapshotId, eventId, targetKey,
                    CURRENT_COMPUTE_CONTRACT_VERSION, computedAt);
        }
    }

    public record ComputeAttempt(long userId, String targetKey, String evidenceVersion,
            String status, String reason, int attemptCount, UUID runToken, Instant nextRetryAt,
            Instant updatedAt) {

        public boolean failed() {
            return "FAILED".equals(status);
        }
    }
}
