package com.example.git_job.analysis.outbox;

import com.example.git_job.analysis.event.TechnologyCandidate;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * Records what one analysis saw, then recomputes the counts it affected.
 *
 * <h2>Why observations exist at all</h2>
 *
 * <p>Incrementing a counter cannot be undone. There is no way to tell whether
 * an analysis was already counted, nothing to subtract when one is deleted, and
 * once a total drifts the real value is unrecoverable. Keeping the observation
 * rows means the counts are always derivable again.</p>
 *
 * <h2>Why distinct users, not occurrences</h2>
 *
 * <p>The question an administrator answers is "how many people would this
 * serve", not "how many lines mention it". Ranking by occurrences lets one
 * monorepo decide the order.</p>
 */
@Repository
public class TechnologyCandidateStore {

    private static final RowMapper<Ranked> RANKED = (rs, row) -> new Ranked(
            rs.getLong("candidate_id"),
            rs.getString("ecosystem"),
            rs.getString("coordinate"),
            rs.getString("scope"),
            rs.getString("status"),
            rs.getInt("distinct_user_count"),
            rs.getInt("distinct_repository_count"),
            rs.getInt("occurrence_count"),
            rs.getTimestamp("first_seen_at").toInstant(),
            rs.getTimestamp("last_seen_at").toInstant());

    private final JdbcTemplate jdbc;

    public TechnologyCandidateStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * @return how many candidates this analysis touched
     */
    public int record(String analysisId, long userId, String repositoryId,
            List<TechnologyCandidate> candidates, Instant observedAt) {
        if (candidates.isEmpty()) {
            return 0;
        }
        Timestamp seen = Timestamp.from(observedAt);
        for (TechnologyCandidate candidate : candidates) {
            long candidateId = upsert(candidate, seen);
            insertObservation(candidateId, analysisId, userId, repositoryId, candidate, seen);
            recount(candidateId);
        }
        return candidates.size();
    }

    /**
     * Creates the candidate on first sight, otherwise only moves {@code last_seen_at}.
     *
     * <p>The status and the decision fields are never touched here. A candidate
     * an administrator rejected keeps accumulating observations — that is how
     * they see it growing — but a later sighting must not quietly reopen the
     * decision.</p>
     */
    private long upsert(TechnologyCandidate candidate, Timestamp seen) {
        return jdbc.queryForObject("""
                INSERT INTO technology_candidate
                    (ecosystem, coordinate, scope, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (ecosystem, coordinate) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at,
                    -- Only while every sighting agrees. Once two disagree the
                    -- column stays NULL rather than flapping between them.
                    scope = CASE
                        WHEN technology_candidate.scope IS NOT DISTINCT FROM EXCLUDED.scope
                        THEN technology_candidate.scope
                        ELSE NULL
                    END
                RETURNING candidate_id
                """, Long.class,
                candidate.ecosystem().name(), candidate.coordinate(), candidate.scope(),
                seen, seen);
    }

    private void insertObservation(long candidateId, String analysisId, long userId,
            String repositoryId, TechnologyCandidate candidate, Timestamp seen) {
        jdbc.update("""
                INSERT INTO technology_candidate_observation
                    (candidate_id, analysis_id, user_id, repository_id, scope,
                     occurrence_count, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (candidate_id, analysis_id) DO NOTHING
                """, candidateId, analysisId, userId, repositoryId,
                candidate.scope(), candidate.occurrenceCount(), seen);
    }

    /**
     * Recomputes from the observations rather than adding to what is there.
     *
     * <p>Costs one grouped read per candidate per analysis, which is cheap
     * because a candidate is only touched when it appears. In exchange the
     * totals are a function of the rows, so a replay, a correction or a deleted
     * analysis all leave them right.</p>
     */
    private void recount(long candidateId) {
        jdbc.update("""
                UPDATE technology_candidate c
                SET distinct_user_count = totals.users,
                    distinct_repository_count = totals.repositories,
                    occurrence_count = totals.occurrences
                FROM (
                    SELECT count(DISTINCT user_id) AS users,
                           count(DISTINCT repository_id) AS repositories,
                           coalesce(sum(occurrence_count), 0) AS occurrences
                    FROM technology_candidate_observation
                    WHERE candidate_id = ?
                ) AS totals
                WHERE c.candidate_id = ?
                """, candidateId, candidateId);
    }

    /** The admin screen's default list: most people affected first, rejected hidden. */
    public List<Ranked> topCandidates(int limit) {
        return jdbc.query("""
                SELECT candidate_id, ecosystem, coordinate, scope, status,
                       distinct_user_count, distinct_repository_count, occurrence_count,
                       first_seen_at, last_seen_at
                FROM technology_candidate
                WHERE status <> 'REJECTED'
                ORDER BY distinct_user_count DESC, distinct_repository_count DESC,
                         coordinate
                LIMIT ?
                """, RANKED, limit);
    }

    public Optional<Ranked> findById(long candidateId) {
        return jdbc.query("""
                SELECT candidate_id, ecosystem, coordinate, scope, status,
                       distinct_user_count, distinct_repository_count, occurrence_count,
                       first_seen_at, last_seen_at
                FROM technology_candidate WHERE candidate_id = ?
                """, RANKED, candidateId).stream().findFirst();
    }

    /**
     * Records the administrator's decision.
     *
     * <p>Only an undecided candidate moves. A second click, or two
     * administrators acting at once, must not overwrite the first decision or
     * its note -- and the count of who is affected keeps growing either way,
     * because that is what makes a past rejection reviewable later.</p>
     *
     * @return false when the candidate was already decided
     */
    public boolean decide(long candidateId, String status, String promotedTechId,
            long decidedBy, String note, Instant decidedAt) {
        return jdbc.update("""
                UPDATE technology_candidate
                SET status = ?, promoted_tech_id = ?, decided_by = ?, decided_at = ?,
                    decision_note = ?
                WHERE candidate_id = ? AND status IN ('NEW', 'REVIEWING')
                """, status, promotedTechId, decidedBy, Timestamp.from(decidedAt), note,
                candidateId) == 1;
    }

    public record Ranked(long candidateId, String ecosystem, String coordinate, String scope,
            String status, int distinctUserCount, int distinctRepositoryCount,
            int occurrenceCount, Instant firstSeenAt, Instant lastSeenAt) {
    }
}
