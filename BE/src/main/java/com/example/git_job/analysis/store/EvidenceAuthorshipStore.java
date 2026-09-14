package com.example.git_job.analysis.store;

import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * 근거 한 줄을 쓴 사람과, 그 판단의 재료가 된 커밋.
 *
 * <h2>커밋을 캐시하는 이유</h2>
 *
 * <p>커밋 하나를 GitHub 에 묻는 데 API 호출 한 번이 든다. 같은 저장소를 다시
 * 분석하면 대부분의 근거가 같은 커밋을 가리키므로, 캐시가 없으면 같은 질문을
 * 매번 되묻는다. 커밋은 불변이라 한 번 받아 두면 틀릴 일도 없다.</p>
 *
 * <h2>Level 을 저장하지 않는다</h2>
 *
 * <p>여기 쌓이는 것은 관찰된 사실뿐이다. Personal Level 은 조회 시점에 이 행들을
 * 걸러 규칙을 다시 평가해 만든다. 저장해 두면 규칙이 바뀌었을 때 둘을 맞출 책임이
 * 생기고, 근거는 그대로인데 판정만 낡는다.</p>
 */
@Repository
public class EvidenceAuthorshipStore {

    private final JdbcTemplate jdbc;

    public EvidenceAuthorshipStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** 이미 물어본 커밋인지. 저장소 안에서 SHA 는 유일하다. */
    public Optional<CachedCommit> findCommit(String repositoryId, String commitSha) {
        return jdbc.query("""
                SELECT github_login, author_name, author_email, authored_at
                FROM repository_commit
                WHERE repository_id = ? AND commit_sha = ?
                """, (rs, row) -> new CachedCommit(
                        rs.getString("github_login"),
                        rs.getString("author_name"),
                        rs.getString("author_email"),
                        rs.getTimestamp("authored_at").toInstant()),
                repositoryId, commitSha).stream().findFirst();
    }

    /**
     * 커밋 메타를 남긴다. 같은 커밋을 두 분석이 동시에 물어도 한 행만 남는다.
     *
     * <p>{@code github_login} 이 {@code null} 인 것은 "본인이 아니다"가 아니라
     * "GitHub 이 계정을 연결하지 못했다"는 뜻이다. 계정에 등록하지 않은 이메일로
     * 커밋하면 그렇게 된다.</p>
     */
    public void cacheCommit(String repositoryId, String commitSha, String githubLogin,
            String authorName, String authorEmail, OffsetDateTime authoredAt) {
        jdbc.update("""
                INSERT INTO repository_commit
                    (repository_id, commit_sha, author_name, author_email, github_login,
                     authored_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (repository_id, commit_sha) DO NOTHING
                """, repositoryId, commitSha,
                authorName == null ? "" : authorName, authorEmail, githubLogin,
                Timestamp.from(authoredAt.toInstant()));
    }

    /**
     * 근거별 기여 판정을 적재한다.
     *
     * <p>같은 분석을 두 번 처리해도 행이 늘지 않는다. 결과 이벤트는 at-least-once 라
     * 재배달이 정상 경로이고, 그때마다 기여가 두 배로 세어지면 안 된다.</p>
     *
     * @return 실제로 쓰인 행 수
     */
    public int insertAll(List<Authorship> rows) {
        if (rows.isEmpty()) {
            return 0;
        }
        int written = 0;
        for (Authorship row : rows) {
            written += jdbc.update("""
                    INSERT INTO analysis_evidence_commit
                        (analysis_evidence_id, analysis_id, repository_id, commit_sha,
                         user_id, contribution_type, matched_line_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (analysis_evidence_id, user_id) DO NOTHING
                    """, row.analysisEvidenceId(), row.analysisId(), row.repositoryId(),
                    row.commitSha(), row.userId(), row.contributionType(),
                    row.matchedLineCount());
        }
        return written;
    }

    /** 이 분석의 근거 중 커밋이 붙은 것. 적재 대상을 찾는 데 쓴다. */
    public List<EvidenceCommitRef> evidenceWithCommits(String analysisId) {
        return jdbc.query("""
                SELECT analysis_evidence_id, commit_sha, start_line, end_line
                FROM analysis_evidence
                WHERE analysis_id = ? AND commit_sha IS NOT NULL
                """, (rs, row) -> new EvidenceCommitRef(
                        rs.getLong("analysis_evidence_id"),
                        rs.getString("commit_sha"),
                        rs.getInt("start_line"),
                        rs.getInt("end_line")),
                analysisId);
    }

    public record CachedCommit(String githubLogin, String authorName, String authorEmail,
            java.time.Instant authoredAt) {
    }

    public record EvidenceCommitRef(long analysisEvidenceId, String commitSha,
            int startLine, int endLine) {
    }

    public record Authorship(long analysisEvidenceId, String analysisId, String repositoryId,
            String commitSha, long userId, String contributionType, int matchedLineCount) {
    }
}
