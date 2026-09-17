package com.example.git_job.analysis.store;

import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * 마이페이지 분석 이력 조회 (B-FN-009, 화면 14).
 *
 * <p>한 사람의 분석 기록을 최근 순으로 읽는다. 결과 요약에 쓰는 기술 수와 근거 수는
 * 여기서 함께 센다 — 목록 한 줄마다 따로 조회하면 스무 줄에 마흔 번 질의한다.</p>
 *
 * <p>기술 수는 근거에서 센다. {@code analysis_technology_support}는 "이 분석이 어떤
 * 기술을 판정할 수 있었는가"이지 "무엇을 찾았는가"가 아니라서, 찾은 것이 없어도 행이
 * 남고 반대로 근거만 있고 그 행이 없는 분석도 있다. 화면이 묻는 것은 찾은 쪽이다.</p>
 */
@Repository
public class AnalysisHistoryStore {

    private final JdbcTemplate jdbc;

    public AnalysisHistoryStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 분석 한 건.
     *
     * @param analyzedAt         끝난 시각. 아직 끝나지 않았으면 요청 시각이다.
     * @param repositoryFullName 대상 저장소 이름. 본인 소유면 {@code owner/} 를 뗀 이름이고,
     *                           남의 저장소를 분석했다면 소유자까지 남는다. 이 열이 생기기
     *                           전 기록은 {@code null} 이다.
     */
    public record Row(String analysisId, Instant analyzedAt, String repositoryFullName,
            String status, List<String> technologies, String maxLevel, int evidenceCount) {
    }

    private static final RowMapper<Row> ROW = (rs, rowNum) -> new Row(
            rs.getString("analysis_id"),
            rs.getTimestamp("analyzed_at").toInstant(),
            rs.getString("repository_full_name"),
            rs.getString("status"),
            names(rs.getArray("technologies")),
            rs.getString("max_level"),
            rs.getInt("evidence_count"));

    /** {@code text[]} 를 목록으로. 근거가 없는 분석은 배열 자체가 {@code null} 이다. */
    private static List<String> names(java.sql.Array array) throws java.sql.SQLException {
        if (array == null) {
            return List.of();
        }
        return List.of((String[]) array.getArray());
    }

    /**
     * 최근 분석부터 한 쪽.
     *
     * <p>정렬은 요청 시각 내림차순이다. 끝난 시각으로 정렬하면 아직 돌고 있는 분석이
     * 목록 맨 아래로 가는데, 사용자가 방금 시작한 그것을 가장 먼저 찾는다.</p>
     */
    public List<Row> page(long userId, int offset, int size) {
        return jdbc.query("""
                SELECT j.analysis_id,
                       coalesce(j.completed_at, j.requested_at) AS analyzed_at,
                       CASE WHEN j.repository_full_name LIKE u.github_login || '/%'
                            THEN substring(j.repository_full_name
                                           FROM length(u.github_login) + 2)
                            ELSE j.repository_full_name END AS repository_full_name,
                       j.status,
                       c.technologies,
                       c.max_level,
                       coalesce(c.evidence_count, 0) AS evidence_count
                  FROM analysis_job j
                  JOIN "user" u ON u.user_id = j.user_id
                  LEFT JOIN (
                        SELECT e.analysis_id,
                               count(*) AS evidence_count,
                               array_agg(DISTINCT coalesce(t.display_name, r.tech_id))
                                   AS technologies,
                               max(r.rule_type) AS max_level
                          FROM analysis_evidence e
                          JOIN evidence_rule r
                            ON r.rule_id = e.rule_id
                           AND r.registry_version = e.registry_version
                          LEFT JOIN technology t
                            ON t.tech_id = r.tech_id
                           AND t.registry_version = r.registry_version
                         GROUP BY e.analysis_id
                  ) c ON c.analysis_id = j.analysis_id
                 WHERE j.user_id = ?
                 ORDER BY j.requested_at DESC
                 LIMIT ? OFFSET ?
                """, ROW, userId, size, offset);
    }

    public int count(long userId) {
        Integer total = jdbc.queryForObject(
                "SELECT count(*) FROM analysis_job WHERE user_id = ?", Integer.class, userId);
        return total == null ? 0 : total;
    }
}
