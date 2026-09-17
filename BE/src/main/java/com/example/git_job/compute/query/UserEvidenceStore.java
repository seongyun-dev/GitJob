package com.example.git_job.compute.query;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * C에 보낼 사용자 Evidence를 읽는다 (S15P21E102-279).
 *
 * <p>읽기 전용이고 판정을 하지 않는다. 여기서 하는 일은 "저장소별 최신 성공 분석"이라는
 * 같은 집합을 화면 조회({@code analysis.query.TechnologyProfileStore})와 똑같이 잡아
 * 주는 것뿐이다. 두 곳이 다른 집합을 보면 화면의 기술 목록과 C가 계산한 매칭이 서로
 * 다른 근거 위에 서게 된다.</p>
 *
 * <p>행을 조립하지 않고 평평하게 돌려준다. 저장소·기술로 묶는 것은 계약을 아는
 * {@code CEvidenceAssembler}의 일이고, SQL에서 묶으면 근거 하나하나의 정체성
 * ({@code analysis_evidence_id})이 사라져 C가 요구하는 근거 행을 만들 수 없다.</p>
 */
@Repository
public class UserEvidenceStore {

    /**
     * 저장소별 최신 성공 분석. {@code TechnologyProfileStore}와 같은 정의다.
     *
     * <p>{@code NULLS LAST}가 필요하다. {@code completed_at}은 nullable이고 PostgreSQL의
     * {@code DESC} 기본값은 {@code NULLS FIRST}라, 끝난 시각이 없는 SUCCEEDED 행이
     * 하나라도 있으면 그 행이 '최신'으로 뽑힌다.</p>
     */
    private static final String LATEST_PER_REPOSITORY = """
            WITH latest AS (
                SELECT DISTINCT ON (repository_id)
                       analysis_id, repository_id, repository_full_name, commit_sha, completed_at,
                       registry_version, rule_pack_version, rule_pack_content_sha256,
                       skipped_reasons
                FROM analysis_job
                WHERE user_id = ? AND status = 'SUCCEEDED'
                ORDER BY repository_id, completed_at DESC NULLS LAST
            )
            """;

    private final JdbcTemplate jdbc;

    public UserEvidenceStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 판정에 들어갈 저장소들. 근거가 0건인 저장소도 포함한다.
     *
     * <p>빼면 안 된다. "분석했는데 아는 기술이 없었다"와 "분석하지 않았다"는 다른
     * 사실이고, C는 판정 범위를 저장소 목록으로 정한다.</p>
     */
    public List<RepositoryAnalysis> latestAnalyses(long userId) {
        return jdbc.query(LATEST_PER_REPOSITORY + """
                SELECT analysis_id, repository_id, repository_full_name, commit_sha, completed_at,
                       registry_version, rule_pack_version, rule_pack_content_sha256,
                       skipped_reasons IS NOT NULL AS reported_skips,
                       coalesce(skipped_reasons, '{}'::jsonb) <> '{}'::jsonb AS skipped_anything
                FROM latest
                ORDER BY repository_id
                """, (rs, row) -> new RepositoryAnalysis(
                        rs.getString("analysis_id"),
                        rs.getString("repository_id"),
                        rs.getString("repository_full_name"),
                        rs.getString("commit_sha"),
                        instantOrNull(rs.getTimestamp("completed_at")),
                        rs.getString("registry_version"),
                        rs.getString("rule_pack_version"),
                        rs.getString("rule_pack_content_sha256"),
                        rs.getBoolean("reported_skips"),
                        rs.getBoolean("skipped_anything")),
                userId);
    }

    /**
     * 그 저장소들의 근거 전부. 기여 판정은 있으면 붙이고 없으면 {@code null}이다.
     *
     * <p>{@code LEFT JOIN}인 것이 중요하다. {@code INNER JOIN}으로 바꾸면 기여 판정이
     * 아직 안 붙은 근거가 통째로 사라지고, C는 그 기술을 "근거 없음"으로 본다. 판정이
     * 없는 것은 근거가 없는 것이 아니라 <em>작성자를 확인하지 못한 것</em>이다.</p>
     *
     * <p>{@code e.commit_sha}는 blame이 지목한 커밋이고 {@code l.commit_sha}는 분석 대상
     * 커밋이다. 이름이 같아 섞이기 쉬워 별칭을 다르게 둔다.</p>
     */
    public List<EvidenceRow> evidence(long userId) {
        return evidence(userId, null);
    }

    /** 처음 선택한 분석 ID 집합의 근거만 읽는다. */
    public List<EvidenceRow> evidence(long userId, Set<String> analysisIds) {
        if (analysisIds != null && analysisIds.isEmpty()) {
            return List.of();
        }
        List<Object> args = new ArrayList<>();
        String selectedAnalyses = selectedAnalyses(userId, analysisIds, args);
        // LEFT JOIN contribution의 사용자 조건.
        args.add(userId);
        return jdbc.query(selectedAnalyses + """
                SELECT l.analysis_id,
                       l.repository_id,
                       l.commit_sha            AS analyzed_commit_sha,
                       e.analysis_evidence_id,
                       e.registry_version,
                       l.rule_pack_version,
                       e.rule_id,
                       e.fact_type,
                       e.file_path,
                       e.start_line,
                       e.end_line,
                       e.commit_sha            AS blame_commit_sha,
                       r.tech_id,
                       r.rule_type,
                       c.contribution_type
                FROM latest l
                JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                JOIN evidence_rule r
                  ON r.rule_id = e.rule_id AND r.registry_version = e.registry_version
                LEFT JOIN analysis_evidence_commit c
                  ON c.analysis_evidence_id = e.analysis_evidence_id AND c.user_id = ?
                ORDER BY l.repository_id, r.tech_id, e.analysis_evidence_id
                """, (rs, row) -> new EvidenceRow(
                        rs.getString("analysis_id"),
                        rs.getString("repository_id"),
                        rs.getString("analyzed_commit_sha"),
                        rs.getLong("analysis_evidence_id"),
                        rs.getString("registry_version"),
                        rs.getString("rule_pack_version"),
                        rs.getString("rule_id"),
                        rs.getString("rule_type"),
                        rs.getString("tech_id"),
                        rs.getString("fact_type"),
                        rs.getString("file_path"),
                        rs.getInt("start_line"),
                        rs.getInt("end_line"),
                        rs.getString("blame_commit_sha"),
                        rs.getString("contribution_type")),
                args.toArray());
    }

    /**
     * 최신 분석이 실패로 끝난 저장소.
     *
     * <p>이 목록이 비어 있지 않으면 사용자 분석 전체를 {@code COMPLETE}로 보내지 않는다.
     * 일부 저장소를 못 읽고도 완전한 판정이라고 말하면, C가 "그 기술을 쓰지 않는다"까지
     * 결론지을 수 있게 된다. 못 본 저장소가 있다는 사실이 판정 범위의 일부다.</p>
     */
    public List<String> failedRepositoryIds(long userId) {
        return jdbc.queryForList("""
                WITH latest AS (
                    SELECT DISTINCT ON (repository_id) repository_id, status
                    FROM analysis_job
                    WHERE user_id = ?
                    ORDER BY repository_id, completed_at DESC NULLS LAST, requested_at DESC
                )
                SELECT repository_id FROM latest WHERE status = 'FAILED' ORDER BY repository_id
                """, String.class, userId);
    }

    /**
     * 그 분석이 실제로 평가할 수 있었던 기술과 그 상한 (S15P21E102-279 후속).
     *
     * <p>Registry 전체가 아니라 <b>분석 단위</b>로 읽는다. 같은 기술이라도 Rule Pack 이
     * 바뀌면 상한이 달라지므로, 과거 분석의 판정을 지금 Rule Pack 의 상한으로 다시
     * 읽으면 안 된다.</p>
     *
     * <p>{@code UNSUPPORTED} 는 빼지 않고 함께 준다. 평가 범위에서는 빠지지만, 그
     * 기술을 "보지 못했다"는 사실 자체가 판정 상한의 근거이기 때문이다.</p>
     */
    public List<TechnologySupport> technologySupport(long userId) {
        return technologySupport(userId, null);
    }

    /** 처음 선택한 분석 ID 집합이 사용한 Rule Pack 범위만 읽는다. */
    public List<TechnologySupport> technologySupport(long userId, Set<String> analysisIds) {
        if (analysisIds != null && analysisIds.isEmpty()) {
            return List.of();
        }
        List<Object> args = new ArrayList<>();
        String selectedAnalyses = selectedAnalyses(userId, analysisIds, args);
        return jdbc.query(selectedAnalyses + """
                SELECT s.analysis_id, s.tech_id, s.max_supported_level, s.coverage
                FROM latest l
                JOIN analysis_technology_support s ON s.analysis_id = l.analysis_id
                ORDER BY s.analysis_id, s.tech_id
                """, (rs, row) -> new TechnologySupport(
                        rs.getString("analysis_id"),
                        rs.getString("tech_id"),
                        rs.getString("max_supported_level"),
                        rs.getString("coverage")),
                args.toArray());
    }

    private static String selectedAnalyses(long userId, Set<String> analysisIds,
                                           List<Object> args) {
        args.add(userId);
        if (analysisIds == null) {
            return LATEST_PER_REPOSITORY;
        }
        List<String> ids = new ArrayList<>(new TreeSet<>(analysisIds));
        ids.forEach(args::add);
        return """
                WITH latest AS (
                    SELECT analysis_id, repository_id, repository_full_name, commit_sha,
                           completed_at, registry_version, rule_pack_version,
                           rule_pack_content_sha256, skipped_reasons
                    FROM analysis_job
                    WHERE user_id = ? AND status = 'SUCCEEDED'
                      AND analysis_id IN (%s)
                )
                """.formatted(String.join(", ",
                java.util.Collections.nCopies(ids.size(), "?")));
    }

    /**
     * 그 Registry에서 Rule Pack이 실제로 평가할 수 있는 기술.
     *
     * <p>C의 판정 범위가 이 목록이다. 근거가 나온 기술만 넣으면 사용자가 쓰지 않는
     * 기술이 전부 "미판정"이 되어 Skill Gap이 빈 표가 되고, Registry 전체를 넣으면
     * 규칙조차 없는 기술을 "안 쓴다"고 단정하게 된다.</p>
     *
     * <p>{@code UNSUPPORTED}를 빼는 이유가 그것이다. 규칙이 없어서 못 본 기술은 판정한
     * 것이 아니다.</p>
     */
    public List<String> evaluatedTechIds(String registryVersion) {
        return jdbc.queryForList("""
                SELECT tech_id FROM technology_rule_support
                WHERE registry_version = ? AND coverage IN ('SUPPORTED', 'PARTIAL')
                ORDER BY tech_id
                """, String.class, registryVersion);
    }

    private static Instant instantOrNull(java.sql.Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    /**
     * 저장소 하나의 최신 성공 분석과 그 판정 기준.
     *
     * @param rulePackVersion {@code null} 이면 v1 결과라 Rule Pack 계보가 없다. C 는
     *        이 값으로 근거의 범위를 검사하므로 Registry 버전으로 대신할 수 없다.
     * @param reportedSkips   건너뛴 사유를 보고받았는지. 받지 못한 것(v1)과 0건을
     *        구분한다 -- 앞은 저장소 전체를 봤다고 말할 수 없다.
     */
    public record RepositoryAnalysis(String analysisId, String repositoryId,
            String repositoryFullName, String commitSha, Instant completedAt,
            String registryVersion, String rulePackVersion, String rulePackContentSha256,
            boolean reportedSkips, boolean skippedAnything) {

        /** Rule Pack 계보를 아는 분석인지. 모르면 C 에 보낼 수 없다. */
        public boolean hasLineage() {
            return rulePackVersion != null && !rulePackVersion.isBlank()
                    && registryVersion != null && !registryVersion.isBlank();
        }

        /**
         * 저장소 전체를 봤다고 말할 수 있는지.
         *
         * <p>성공만으로는 부족하다. 워커가 파일을 건너뛰고도 완료로 끝날 수 있고,
         * 보고를 받지 못한 계약이면 건너뛰었는지조차 모른다. 둘 다 완전 판정이 아니다.</p>
         */
        public boolean coverageComplete() {
            return reportedSkips && !skippedAnything;
        }
    }

    /**
     * 근거 한 줄과 그 줄에 붙은 기여 판정.
     *
     * @param contributionType {@code null}이면 작성자 미확인이다. "본인이 아니다"가 아니다.
     * @param blameCommitSha   {@code null}이면 blame을 읽지 못한 것이다.
     */
    /** 분석 하나가 기술 하나를 어디까지 판정할 수 있었는지. */
    public record TechnologySupport(String analysisId, String techId,
            String maxSupportedLevel, String coverage) {

        /** 규칙이 있어 실제로 본 기술인지. 없는 기술은 판정한 것이 아니다. */
        public boolean evaluated() {
            return !"UNSUPPORTED".equals(coverage);
        }
    }

    public record EvidenceRow(String analysisId, String repositoryId, String analyzedCommitSha,
            long evidenceId, String registryVersion, String rulePackVersion, String ruleId,
            String ruleType,
            String techId, String factType, String filePath, int startLine, int endLine,
            String blameCommitSha, String contributionType) {
    }
}
