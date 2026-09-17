package com.example.git_job.analysis.query;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * 사용자의 분석 결과를 화면이 읽을 수 있는 모양으로 집계한다.
 *
 * <p>읽기 전용이다. 이 패키지에는 쓰기가 없다 -- 판정은 조회 시점에 만들어지고
 * 어디에도 저장되지 않는다. 쓰는 쪽은 {@code analysis.store} 다.</p>
 *
 * <h2>집계 단위: 저장소마다 최신 성공 분석 한 건</h2>
 *
 * <p>분석은 저장소 하나에 대해 한 건씩 만들어진다. 같은 저장소를 두 번 분석하면
 * 행이 둘 생기는데, 둘을 합치면 지운 코드가 근거로 남는다. 그래서 저장소별로
 * <b>가장 최근 성공 분석</b>만 본다.</p>
 *
 * <h2>Level 은 최고치를 채택한다</h2>
 *
 * <p>한 기술이 저장소 A 에서는 import 만(L1), B 에서는 호출까지(L2) 확인될 수
 * 있다. 이때 답은 "이 사람은 L2 를 해 봤다"이다. 평균을 내면 실제로 한 일이
 * 사라지고, 최저치를 쓰면 안 쓴 저장소가 판정을 끌어내린다.</p>
 *
 * <p>{@code rule_type} 은 L0..L3 문자열이라 사전순 최대가 곧 최고 Level 이다.</p>
 *
 * <h2>Personal Level 은 따로 구한다</h2>
 *
 * <p>{@link #personalLevels(long)} 가 본인이 쓴 근거만으로 같은 규칙을 다시
 * 평가한다. 한 질의로 합치지 않는 이유는 두 판정의 대상이 다르기 때문이다 --
 * Repository 는 모든 근거, Personal 은 본인 근거만이다.</p>
 *
 * <p>본인 근거는 {@code analysis_evidence_commit} 에서 오고, 그 테이블은 이 경로가
 * 전부 살아 있을 때만 채워진다.</p>
 *
 * <ol>
 *   <li>워커의 {@code ANALYSIS_ATTRIBUTE_AUTHORS} 가 켜져 있어야 한다. 그래야 전체
 *       히스토리를 클론하고 {@code git blame} 이 답을 낸다. 꺼져 있으면 결과의
 *       {@code commit_sha} 가 전부 비어 온다.</li>
 *   <li>{@code EvidenceAuthorshipService} 가 그 커밋의 작성자를 GitHub 에 물어
 *       {@code analysis_evidence_commit} 에 쓴다. 근거 적재와 다른 트랜잭션이라,
 *       GitHub 이 느리면 근거는 남고 이 행만 비는 상태가 정상적으로 생긴다.</li>
 * </ol>
 *
 * <p>그래서 Personal 이 비는 경우는 흔하다. 그것은 "본인이 안 썼다"가 아니라
 * "확인되지 않았다"이며, Repository Level 로 대신 채우면 화면이 "본인이 썼다"고
 * 말하게 된다 -- 확인하지 못한 것과 확인해 보니 아닌 것은 다른 사실이다.</p>
 */
@Repository
public class TechnologyProfileStore {

    /** 저장소별 최신 성공 분석. 뒤의 모든 집계가 이 집합 위에서 이뤄진다. */
    private static final String LATEST_PER_REPOSITORY = """
            WITH latest AS (
                SELECT DISTINCT ON (repository_id)
                       analysis_id, repository_id, repository_full_name, commit_sha, completed_at
                FROM analysis_job
                WHERE user_id = ? AND status = 'SUCCEEDED'
                -- NULLS LAST 가 필요하다. completed_at 은 nullable 이고 PostgreSQL 의
                -- DESC 기본값은 NULLS FIRST 라, 끝난 시각이 없는 SUCCEEDED 행이
                -- 하나라도 있으면 그 행이 '최신'으로 뽑힌다.
                ORDER BY repository_id, completed_at DESC NULLS LAST
            )
            """;

    private static final RowMapper<TechnologyVerdict> VERDICT = (rs, row) -> new TechnologyVerdict(
            rs.getString("tech_id"),
            rs.getString("display_name"),
            rs.getString("repository_level"),
            rs.getInt("evidence_count"),
            rs.getInt("repository_count"),
            rs.getString("registry_version"));

    private final JdbcTemplate jdbc;

    public TechnologyProfileStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 기술별 판정 목록. 높은 Level 이 먼저, 같으면 근거가 많은 순이다.
     *
     * <p>{@code display_name} 은 근거를 만든 그 버전의 레지스트리에서 가져온다.
     * 지금 CURRENT 에서 찾으면, 그 사이 이름이 바뀌었거나 기술이 빠졌을 때 판정과
     * 이름이 어긋난다.</p>
     */
    public List<TechnologyVerdict> verdicts(long userId) {
        return verdicts(userId, null);
    }

    /**
     * 기술 하나의 판정.
     *
     * <p>{@link #verdicts(long)} 를 부른 뒤 하나만 고르는 것과 결과는 같지만, 그
     * 경로는 사용자의 모든 기술을 집계한다. 요약은 카드 한 장마다 이 값을 필요로
     * 하므로 열두 장이면 전체 집계를 열두 번 하게 된다.</p>
     */
    public Optional<TechnologyVerdict> verdict(long userId, String techId) {
        return verdicts(userId, techId).stream().findFirst();
    }

    /**
     * @param techId {@code null} 이면 모든 기술. 필터는 SQL 로 건다 -- 가져와서
     *               버리면 집계 비용이 그대로 남는다.
     */
    private List<TechnologyVerdict> verdicts(long userId, String techId) {
        String filter = techId == null ? "" : "WHERE r.tech_id = ?\n";
        Object[] args = techId == null
                ? new Object[] {userId}
                : new Object[] {userId, techId};
        return jdbc.query(LATEST_PER_REPOSITORY + """
                -- 기술은 근거가 아니라 규칙에 붙어 있다. analysis_evidence 에는
                -- rule_id 만 있고 tech_id 가 없다.
                SELECT r.tech_id,
                       max(t.display_name)      AS display_name,
                       max(r.rule_type)         AS repository_level,
                       count(*)                 AS evidence_count,
                       count(DISTINCT l.repository_id) AS repository_count,
                       max(e.registry_version)  AS registry_version
                FROM latest l
                JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                JOIN evidence_rule r
                  ON r.rule_id = e.rule_id AND r.registry_version = e.registry_version
                JOIN technology t
                  ON t.tech_id = r.tech_id AND t.registry_version = e.registry_version
                """ + filter + """
                GROUP BY r.tech_id
                ORDER BY max(r.rule_type) DESC, count(*) DESC, r.tech_id
                """, VERDICT, args);
    }

    /**
     * 한 기술의 근거. Level 마다 따로 잘라서 가져온다.
     *
     * <p>전체에 하나의 LIMIT 을 걸면 안 된다. 정렬이 Level 내림차순이라 L2 가 상한을
     * 채우는 순간 L0 와 L1 이 통째로 사라지고, 화면은 "의존성 선언이 없다"로 읽힌다.
     * 실제로 Spring Security 한 기술이 L2 40 건 · L1 40 건을 낸다.</p>
     *
     * <p>{@code total_in_level} 은 잘리기 전의 개수다. 화면이 "40 건 중 20 건"이라고
     * 말할 수 있어야 잘렸다는 사실이 드러난다.</p>
     */
    public List<EvidenceLine> evidence(long userId, String techId, int perLevelLimit) {
        return jdbc.query(LATEST_PER_REPOSITORY + """
                , matched AS (
                    SELECT l.repository_full_name, l.commit_sha, e.file_path,
                           e.start_line, e.end_line, e.fact_type, e.rule_id,
                           r.rule_type, r.rule_name,
                           row_number() OVER (PARTITION BY r.rule_type
                                              ORDER BY e.file_path, e.start_line) AS rank_in_level,
                           count(*)     OVER (PARTITION BY r.rule_type) AS total_in_level
                    FROM latest l
                    JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                    JOIN evidence_rule r
                      ON r.rule_id = e.rule_id AND r.registry_version = e.registry_version
                    WHERE r.tech_id = ?
                )
                SELECT * FROM matched
                WHERE rank_in_level <= ?
                ORDER BY rule_type DESC, file_path, start_line
                """, (rs, row) -> new EvidenceLine(
                        rs.getString("repository_full_name"),
                        rs.getString("commit_sha"),
                        rs.getString("file_path"),
                        rs.getInt("start_line"),
                        rs.getInt("end_line"),
                        rs.getString("fact_type"),
                        rs.getString("rule_id"),
                        rs.getString("rule_type"),
                        rs.getString("rule_name"),
                        rs.getInt("total_in_level")),
                userId, techId, perLevelLimit);
    }

    /**
     * 기술별 Personal Level. 본인이 쓴 근거만으로 같은 규칙을 다시 판정한 결과다.
     *
     * <h2>왜 점수가 아닌가</h2>
     *
     * <p>화면이 Personal 과 Repository 를 나란히 놓는다. 한쪽이 규칙 판정이고 한쪽이
     * 가중치 합이면 나란히 둘 이유가 없다 -- 같은 자로 재야 차이가 정보가 된다.
     * 같은 규칙에 좁은 사실을 넣으므로 {@code Personal <= Repository} 도 자동으로
     * 성립한다.</p>
     *
     * <h2>저장소 안에서 판정하고, 저장소를 넘어 최고치를 고른다</h2>
     *
     * <p>이 순서가 뒤집히면 저장소 A 의 IMPORT 와 저장소 B 의 API_CALL 을 붙여 L2 를
     * 만든다. 어느 저장소에서도 하지 않은 일이다. 그래서 절 커버리지는
     * {@code analysis_id} 안에서 따지고, 최고치는 그다음에 고른다.</p>
     *
     * <h2>엄격 판정</h2>
     *
     * <p>규칙의 <b>모든</b> REQUIRED 절이 본인 근거로 덮여야 한다. 하나라도 있으면
     * 되는 쪽으로 하면 Personal 과 Repository 가 거의 같아져 두 칸을 두는 의미가
     * 사라진다.</p>
     *
     * <p>{@code PARTIAL_EDIT} 는 세지 않는다. 정의상 그 근거 줄을 본인이 쓰지 않았고,
     * 파일을 만졌다는 것은 레벨의 근거가 아니라 화면에 보여줄 사실이다.</p>
     */
    public List<TechnologyLevel> personalLevels(long userId) {
        return personalLevels(userId, null, null);
    }

    /**
     * 처음 선택한 분석 집합만으로 Personal Level을 계산한다.
     *
     * <p>조립 중 다른 분석이 완료되면 "저장소별 최신" 집합이 질의 사이에 바뀔 수 있다.
     * Evidence 묶음이 고른 분석 ID와 개인 판정이 서로 다른 시점을 보지 않도록 조립기가
     * 이 경로를 사용한다.</p>
     */
    public List<TechnologyLevel> personalLevels(long userId, Set<String> analysisIds) {
        if (analysisIds == null || analysisIds.isEmpty()) {
            return List.of();
        }
        return personalLevels(userId, null, analysisIds);
    }

    /**
     * 기술 하나의 Personal Level.
     *
     * <p>{@link #verdict(long, String)} 와 같은 이유로 따로 둔다. 요약은 카드마다
     * 이 값을 물으므로, 전체를 판정한 뒤 하나만 고르면 열두 장에 열두 번이다.</p>
     *
     * @return 본인 근거로 성립하는 규칙이 없으면 비어 있다. "본인이 안 썼다"가
     *         아니라 "확인된 범위가 없다"는 뜻이다
     */
    public Optional<String> personalLevel(long userId, String techId) {
        return personalLevels(userId, techId, null).stream()
                .map(TechnologyLevel::level)
                .findFirst();
    }

    /** @param techId {@code null} 이면 모든 기술. */
    private List<TechnologyLevel> personalLevels(long userId, String techId,
                                                  Set<String> selectedAnalysisIds) {
        String filter = techId == null ? "" : "      AND r.tech_id = ?\n";
        List<Object> args = new ArrayList<>();
        String selectedAnalyses = selectedAnalysesCte(userId, selectedAnalysisIds, args);
        // latest CTE 뒤 mine CTE의 기여 판정 사용자.
        args.add(userId);
        if (techId != null) {
            args.add(techId);
        }
        return jdbc.query(selectedAnalyses + """
                , mine AS (
                    SELECT DISTINCT e.analysis_id, e.rule_id, e.fact_type
                    FROM latest l
                    JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                    JOIN analysis_evidence_commit c
                      ON c.analysis_evidence_id = e.analysis_evidence_id
                    WHERE c.user_id = ?
                      AND c.contribution_type IN ('SOLE_AUTHOR', 'CO_AUTHORED')
                ),
                -- 저장소 하나 안에서 그 규칙의 모든 절이 본인 근거로 덮였는가
                holds AS (
                    SELECT mine.analysis_id, r.tech_id, r.rule_type
                    FROM evidence_rule r
                    JOIN evidence_rule_clause cl
                      ON cl.rule_id = r.rule_id AND cl.registry_version = r.registry_version
                    JOIN mine ON mine.rule_id = r.rule_id
                    WHERE cl.role = 'REQUIRED'
                """ + filter + """
                    GROUP BY mine.analysis_id, r.tech_id, r.rule_id, r.rule_type
                    HAVING count(DISTINCT cl.fact_type)
                         = count(DISTINCT cl.fact_type) FILTER (
                               WHERE cl.fact_type IN (
                                   SELECT m2.fact_type FROM mine m2
                                   WHERE m2.analysis_id = mine.analysis_id
                                     AND m2.rule_id = r.rule_id))
                )
                SELECT tech_id, max(rule_type) AS level
                FROM holds GROUP BY tech_id
                """, (rs, row) -> new TechnologyLevel(
                        rs.getString("tech_id"), rs.getString("level")),
                args.toArray());
    }

    private String selectedAnalysesCte(long userId, Set<String> selectedAnalysisIds,
                                       List<Object> args) {
        args.add(userId);
        if (selectedAnalysisIds == null) {
            return LATEST_PER_REPOSITORY;
        }
        List<String> ids = new ArrayList<>(new TreeSet<>(selectedAnalysisIds));
        ids.forEach(args::add);
        return """
                WITH latest AS (
                    SELECT analysis_id, repository_id, repository_full_name, commit_sha,
                           completed_at
                    FROM analysis_job
                    WHERE user_id = ? AND status = 'SUCCEEDED'
                      AND analysis_id IN (%s)
                )
                """.formatted(String.join(", ", java.util.Collections.nCopies(ids.size(), "?")));
    }

    /** 화면 상단 지표. 기술 수·L2 이상·저장소 수·마지막 분석 시각. */
    public ProfileSummary summary(long userId) {
        return jdbc.queryForObject(LATEST_PER_REPOSITORY + """
                SELECT count(DISTINCT r.tech_id)                          AS technology_count,
                       count(DISTINCT r.tech_id) FILTER (
                           WHERE r.rule_type IN ('L2', 'L3'))             AS advanced_count,
                       count(DISTINCT l.repository_id)                    AS repository_count,
                       max(l.completed_at)                                AS analyzed_at
                FROM latest l
                LEFT JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                LEFT JOIN evidence_rule r
                  ON r.rule_id = e.rule_id AND r.registry_version = e.registry_version
                """, (rs, row) -> {
                    var analyzedAt = rs.getTimestamp("analyzed_at");
                    return new ProfileSummary(
                            rs.getInt("technology_count"),
                            rs.getInt("advanced_count"),
                            rs.getInt("repository_count"),
                            analyzedAt == null ? null : analyzedAt.toInstant());
                }, userId);
    }

    /**
     * 판정에 쓰인 저장소들. "어떤 저장소가 근거가 됐는지"를 화면이 보여준다.
     *
     * <p>근거가 하나도 안 나온 저장소도 포함한다. 분석은 했는데 아는 기술이 없었던
     * 것과, 분석 자체를 안 한 것은 다르다.</p>
     */
    public List<AnalyzedRepository> repositories(long userId) {
        return jdbc.query(LATEST_PER_REPOSITORY + """
                SELECT l.repository_id, l.repository_full_name, l.commit_sha, l.completed_at,
                       count(e.analysis_evidence_id) AS evidence_count
                FROM latest l
                LEFT JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                GROUP BY l.repository_id, l.repository_full_name, l.commit_sha, l.completed_at
                ORDER BY l.completed_at DESC
                """, (rs, row) -> new AnalyzedRepository(
                        rs.getString("repository_id"),
                        rs.getString("repository_full_name"),
                        rs.getString("commit_sha"),
                        // 정렬이 NULL 을 뒤로 보내도 그런 행만 있는 저장소가 있을 수
                        // 있다. summary() 도 같은 값을 이렇게 다룬다.
                        completedAt(rs.getTimestamp("completed_at")),
                        rs.getInt("evidence_count")),
                userId);
    }

    private static java.time.Instant completedAt(java.sql.Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    /** 그 버전의 레지스트리가 아는 기술인지. 오타와 "근거 0건"을 구분하려고 본다. */
    public boolean isKnownTechnology(String techId) {
        Integer found = jdbc.queryForObject("""
                SELECT count(*) FROM technology t
                JOIN technology_registry g ON g.registry_version = t.registry_version
                WHERE t.tech_id = ? AND g.status IN ('CURRENT', 'RETIRED')
                """, Integer.class, techId);
        return found != null && found > 0;
    }

    public record TechnologyLevel(String techId, String level) {
    }

    public record TechnologyVerdict(String techId, String displayName, String repositoryLevel,
            int evidenceCount, int repositoryCount, String registryVersion) {
    }

    /** {@code totalInLevel} 은 상한에 잘리기 전, 그 Level 의 전체 근거 수다. */
    public record EvidenceLine(String repositoryFullName, String commitSha, String filePath,
            int startLine, int endLine, String factType, String ruleId, String ruleType,
            String ruleName, int totalInLevel) {
    }

    public record ProfileSummary(int technologyCount, int advancedCount, int repositoryCount,
            Instant analyzedAt) {
    }

    public record AnalyzedRepository(String repositoryId, String repositoryFullName,
            String commitSha, Instant completedAt, int evidenceCount) {
    }
}
