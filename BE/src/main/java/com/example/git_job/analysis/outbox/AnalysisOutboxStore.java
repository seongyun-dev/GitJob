package com.example.git_job.analysis.outbox;

import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** All methods participate in the caller's transaction and use the same datasource as jobs. */
@Repository
public class AnalysisOutboxStore {
    private final JdbcTemplate jdbc;

    public AnalysisOutboxStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(RepositoryAnalysisRequestedEvent event, String topic, String json) {
        jdbc.update("""
                INSERT INTO analysis_outbox
                    (event_id, analysis_id, analysis_repository_id, topic, event_json,
                     status, attempts, created_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
                """, event.eventId(), event.payload().analysisId(),
                event.payload().analysisRepositoryId(), topic, json,
                Timestamp.from(event.occurredAt()), Timestamp.from(event.occurredAt()));
    }

    /**
     * 자격증명 교환 요청의 repository-scoped ID가 실제로 발행된 분석 요청에 속하는지 본다.
     * 재발행은 같은 ID를 여러 행에 둘 수 있으므로 unique 조회가 아니라 존재 여부만 확인한다.
     */
    public boolean containsAnalysisRepository(String analysisId, String analysisRepositoryId) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*)
                FROM analysis_outbox
                WHERE analysis_id = ? AND analysis_repository_id = ?
                """, Integer.class, analysisId, analysisRepositoryId);
        return count != null && count > 0;
    }

    /** Caller must hold this transaction open until marking success/failure. */
    public Optional<Entry> lockNext() {
        return jdbc.query("""
                SELECT event_id, topic, event_json, attempts
                FROM analysis_outbox
                WHERE status = 'PENDING' AND next_attempt_at <= CURRENT_TIMESTAMP
                ORDER BY next_attempt_at, created_at, event_id
                LIMIT 1 FOR UPDATE SKIP LOCKED
                """, (rs, row) -> new Entry(rs.getString("event_id"), rs.getString("topic"),
                rs.getString("event_json"), rs.getInt("attempts"))).stream().findFirst();
    }

    public void published(String eventId) {
        jdbc.update("""
                UPDATE analysis_outbox
                SET status = 'PUBLISHED', attempts = attempts + 1,
                    published_at = CURRENT_TIMESTAMP, last_error_code = NULL
                WHERE event_id = ?
                """, eventId);
    }

    public void failed(String eventId, String errorCode, boolean exhausted, Instant nextAttempt) {
        jdbc.update("""
                UPDATE analysis_outbox
                SET status = ?, attempts = attempts + 1, last_error_code = ?, next_attempt_at = ?
                WHERE event_id = ?
                """, exhausted ? "FAILED" : "PENDING", errorCode,
                Timestamp.from(nextAttempt), eventId);
    }

    public record Entry(String eventId, String topic, String json, int attempts) {
    }
}
