package com.example.git_job.compute.store;

import java.time.Instant;
import java.util.Optional;
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

    private static final RowMapper<ComputeSnapshot> MAPPER = (rs, row) -> new ComputeSnapshot(
            rs.getLong("user_id"),
            rs.getString("evidence_version"),
            rs.getString("cohort_snapshot_id"),
            rs.getString("demand_snapshot_id"),
            rs.getString("recommendation_snapshot_id"),
            rs.getString("event_id"),
            rs.getString("target_key"),
            rs.getTimestamp("computed_at").toInstant());

    private static final String COLUMNS = """
            user_id, evidence_version, cohort_snapshot_id, demand_snapshot_id,
            recommendation_snapshot_id, event_id, target_key, computed_at
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
                    demand_snapshot_id, recommendation_snapshot_id, event_id, target_key, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                snapshot.userId(), snapshot.evidenceVersion(), snapshot.cohortSnapshotId(),
                snapshot.demandSnapshotId(), snapshot.recommendationSnapshotId(),
                snapshot.eventId(), snapshot.targetKey(),
                java.sql.Timestamp.from(snapshot.computedAt()));
        return inserted > 0;
    }

    public record ComputeSnapshot(long userId, String evidenceVersion, String cohortSnapshotId,
            String demandSnapshotId, String recommendationSnapshotId, String eventId,
            String targetKey, Instant computedAt) {
    }
}
