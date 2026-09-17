package com.example.git_job.analysis.query;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Fact Pack 을 채우는 네 가지 질의.
 *
 * <p>{@link TechnologyProfileStore} 가 화면에 필요한 것을 답한다면, 여기는 요약을
 * 쓰는 데만 필요한 것을 답한다. 같은 클래스에 넣지 않은 이유는 수명이 다르기
 * 때문이다 -- 이 넷은 LLM 계약이 바뀌면 같이 바뀌고, 화면 조회는 그렇지 않다.</p>
 *
 * <p>읽기 전용이다. 집계 단위는 {@code TechnologyProfileStore} 와 같은 "저장소별
 * 최신 성공 분석"이어야 한다. 다르면 요약이 화면과 다른 사실을 말하게 된다.</p>
 */
@Repository
public class TechnologySummaryFactStore {

    /**
     * 저장소별 최신 성공 분석. {@link TechnologyProfileStore} 와 같은 정의다.
     *
     * <p>{@code NULLS LAST} 가 필요하다. {@code completed_at} 은 nullable 이고
     * PostgreSQL 의 {@code DESC} 기본값이 {@code NULLS FIRST} 라, 끝난 시각이 없는
     * SUCCEEDED 행 하나가 '최신'으로 뽑힌다.</p>
     */
    private static final String LATEST_PER_REPOSITORY = """
            WITH latest AS (
                SELECT DISTINCT ON (repository_id)
                       analysis_id, repository_id, repository_full_name, completed_at
                FROM analysis_job
                WHERE user_id = ? AND status = 'SUCCEEDED'
                ORDER BY repository_id, completed_at DESC NULLS LAST
            )
            """;

    /**
     * 한 기술의 근거를 기여 판정과 함께 읽는 공통 조각.
     *
     * <p>{@code LEFT JOIN} 이어야 한다. {@code INNER} 로 하면 기여 판정이 아직 없는
     * 분석의 근거가 통째로 사라지고, 요약이 "근거가 없다"고 말하게 된다. 판정이
     * 없는 것과 본인이 안 쓴 것은 다르다.</p>
     */
    private static final String EVIDENCE_OF_TECH = """
            , mine AS (
                SELECT e.analysis_evidence_id, e.fact_type, e.fact_payload, e.file_path,
                       e.start_line, e.rule_id, e.registry_version, e.commit_sha,
                       l.repository_id, l.repository_full_name, r.rule_type,
                       c.contribution_type,
                       c.contribution_type IN ('SOLE_AUTHOR', 'CO_AUTHORED') AS is_mine
                FROM latest l
                JOIN analysis_evidence e ON e.analysis_id = l.analysis_id
                JOIN evidence_rule r
                  ON r.rule_id = e.rule_id AND r.registry_version = e.registry_version
                LEFT JOIN analysis_evidence_commit c
                  ON c.analysis_evidence_id = e.analysis_evidence_id AND c.user_id = ?
                WHERE r.tech_id = ?
            )
            """;

    private final JdbcTemplate jdbc;

    public TechnologySummaryFactStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 본인 근거가 차지하는 정도를 구간으로.
     *
     * <h2>왜 건수가 아니라 구간인가</h2>
     *
     * <p>{@code SOLE_AUTHOR 32 / UNVERIFIED 12} 를 그대로 보내면 모델이 "약 73%"
     * 를 쓴다. 와이어프레임 1-1 이 비율 표기를 금지한다. 프롬프트로 막는 것보다
     * 입력에서 없애는 편이 확실하다.</p>
     *
     * <h2>분모는 판정된 근거다</h2>
     *
     * <p>기여 판정이 없는 근거를 분모에 넣으면 안 된다. 미판정은 "남이 썼다"가
     * 아니라 "모른다"이고, 그것을 남의 것처럼 세면 본인 몫이 체계적으로
     * 과소평가된다. 실측: {@code spring-security} 근거 170 건 중 판정된 것이 85,
     * 그중 69 가 본인 것이었다. 전체로 나누면 과반이 안 되어 {@code MIXED} 가
     * 나오지만, 확인된 것만 보면 81% 로 분명히 {@code MOSTLY_MINE} 이다.</p>
     *
     * <p>"판정됐다"는 <b>행이 있다</b>가 아니라 <b>답을 얻었다</b>이다.
     * {@code analysis_evidence_commit} 에는 {@code UNVERIFIED} 행도 쌓이는데, 그것은
     * GitHub 이 커밋을 계정에 붙이지 못했거나 조회 상한에 걸려 묻지 못한 근거다.
     * 행이 있다는 이유로 분모에 넣으면 위 문단이 막으려던 과소평가가 그대로
     * 일어난다.</p>
     *
     * <p>이 구분은 {@code OTHER_AUTHOR}(물어봐서 남이 썼다)가 {@code UNVERIFIED} 에서
     * 갈라져 나오면서 비로소 가능해졌다(V19). 그 전에는 둘이 한 값이라 미판정을 빼면
     * 확인된 타인 작성까지 함께 빠졌다.</p>
     *
     * <h2>경계</h2>
     *
     * <p>판정된 근거가 하나도 없으면 {@code NOT_VERIFIED} 다. 이것은 "본인이 안
     * 썼다"가 아니라 "확인되지 않았다"이며 나머지 셋과 종류가 다르다.</p>
     *
     * <p>나머지는 과반과 1/4 로 가른다. 1/4 는 정한 값이다 -- 계약이 "소수"를
     * 따로 두라고 하는데 "하나도 없음"으로만 좁히면 그 칸이 사실상 비고, 본인
     * 근거가 두어 건뿐인 기술이 {@code MIXED} 로 올라와 요약이 그것을 대등하게
     * 말한다.</p>
     */
    public String authorship(long userId, String techId) {
        Counts counts = jdbc.queryForObject(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE is_mine) AS mine_count,
                       -- 행이 있는지가 아니라 답을 얻었는지로 센다. UNVERIFIED 는
                       -- 행이 있어도 "묻지 못했다"이므로 분모가 아니다.
                       count(*) FILTER (WHERE contribution_type IS NOT NULL
                                          AND contribution_type <> 'UNVERIFIED') AS judged
                FROM mine
                """, (rs, row) -> new Counts(
                        rs.getInt("total"), rs.getInt("mine_count"), rs.getInt("judged")),
                userId, userId, techId);

        if (counts == null || counts.judged() == 0) {
            return "NOT_VERIFIED";
        }
        if (counts.mine() * 2 > counts.judged()) {
            return "MOSTLY_MINE";
        }
        return counts.mine() * 4 <= counts.judged() ? "MOSTLY_OTHERS" : "MIXED";
    }

    /**
     * Level 마다 충족된 규칙 이름과, 그 Level 에 본인 근거가 있는지.
     *
     * <p>높은 Level 이 먼저다. 요약이 가장 높은 것부터 말하게 된다.</p>
     */
    public List<LevelRules> levels(long userId, String techId) {
        return jdbc.query(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT m.rule_type,
                       array_agg(DISTINCT r.rule_name) AS rule_names,
                       bool_or(coalesce(m.is_mine, false)) AS any_mine
                FROM mine m
                -- registry_version 까지 걸어야 한다. rule_id 만으로 조이면 옛 버전의
                -- 같은 규칙이 함께 붙어, 그 사이 이름이 바뀌었을 때 두 이름이 다
                -- 나온다.
                JOIN evidence_rule r
                  ON r.rule_id = m.rule_id AND r.registry_version = m.registry_version
                GROUP BY m.rule_type
                ORDER BY m.rule_type DESC
                """, (rs, row) -> new LevelRules(
                        rs.getString("rule_type"),
                        List.of((String[]) rs.getArray("rule_names").getArray()),
                        rs.getBoolean("any_mine")),
                userId, userId, techId);
    }

    /**
     * 다음 Level 의 규칙에서 본인 근거로 덮이지 않은 절이 기대하던 값들.
     *
     * <h2>규칙 이름이 아니라 기대값을 모으는 이유</h2>
     *
     * <p>"메서드 보안 활성화가 없다"는 무엇을 해야 하는지 말해 주지 않는다.
     * {@code @EnableMethodSecurity} 라고 적혀야 다음에 할 일이 된다.</p>
     *
     * <h2>절 단위로 본다</h2>
     *
     * <p>규칙이 아예 안 걸렸으면 모든 절이 비어 전부 모인다. Repository 에서는
     * 걸렸는데 Personal 이 못 미친 경우에는 본인이 덮은 절만 빠진다 -- 그게 이
     * 사람에게 실제로 남은 일이다.</p>
     *
     * @param level 다음 Level ({@code L1}..{@code L3})
     */
    public Optional<MissingClauses> missingForLevel(long userId, String techId,
            String registryVersion, String level) {
        List<MissingRow> rows = jdbc.query(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT r.rule_name, cl.clause_id, v.expected_value,
                       EXISTS (
                           SELECT 1 FROM mine m
                           WHERE m.rule_id = r.rule_id
                             AND m.fact_type = cl.fact_type
                             AND m.is_mine
                       ) AS covered
                FROM evidence_rule r
                JOIN evidence_rule_clause cl
                  ON cl.rule_id = r.rule_id AND cl.registry_version = r.registry_version
                JOIN evidence_rule_predicate p ON p.clause_id = cl.clause_id
                JOIN evidence_rule_predicate_value v ON v.predicate_id = p.predicate_id
                WHERE r.tech_id = ? AND r.registry_version = ? AND r.rule_type = ?
                  AND r.status = 'ACTIVE' AND cl.role = 'REQUIRED'
                ORDER BY r.priority, cl.clause_order, p.predicate_order, v.value_order
                """, (rs, row) -> new MissingRow(
                        rs.getString("rule_name"),
                        rs.getLong("clause_id"),
                        rs.getString("expected_value"),
                        rs.getBoolean("covered")),
                userId, userId, techId, techId, registryVersion, level);

        if (rows.isEmpty()) {
            // 그 Level 에 규칙이 없다. 기술 29개 중 L3 를 가진 것은 둘뿐이라
            // 흔한 경우이고, 실패가 아니다.
            return Optional.empty();
        }
        List<String> missing = new ArrayList<>(new LinkedHashSet<>(
                rows.stream().filter(candidate -> !candidate.covered())
                        .map(MissingRow::expectedValue).toList()));
        if (missing.isEmpty()) {
            // 모든 절이 본인 근거로 덮였는데 Level 이 안 섰다면 규칙과 판정이
            // 어긋난 것이다. 지어내지 말고 비운다.
            return Optional.empty();
        }
        return Optional.of(new MissingClauses(rows.getFirst().ruleName(), missing));
    }

    /**
     * 본인이 이 기술을 건드린 기간.
     *
     * <p>본인 커밋만 센다. 저장소의 첫 커밋부터 재면 합류하기 전의 기간까지 본인
     * 것으로 말하게 된다. 확인된 커밋이 없으면 비어 있고, 그때 요약은 기간을
     * 언급하지 않는다.</p>
     */
    public Optional<Span> period(long userId, String techId) {
        List<Span> found = jdbc.query(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT min(rc.authored_at) AS first_at, max(rc.authored_at) AS last_at
                FROM mine m
                JOIN repository_commit rc
                  ON rc.repository_id = m.repository_id AND rc.commit_sha = m.commit_sha
                WHERE m.is_mine
                """, (rs, row) -> {
                    Instant first = toInstant(rs.getTimestamp("first_at"));
                    Instant last = toInstant(rs.getTimestamp("last_at"));
                    return first == null || last == null ? null : new Span(first, last);
                }, userId, userId, techId);
        return found.isEmpty() ? Optional.empty() : Optional.ofNullable(found.getFirst());
    }

    /**
     * 이 기술의 근거가 나온 저장소와, 그중 본인이 쓴 것이 있는지.
     *
     * <p>근거가 있다는 것만으로 {@code mine} 을 세우지 않는다. 팀 저장소에 그
     * 기술이 쓰였다는 사실과 이 사람이 그것을 썼다는 사실은 다르고, 요약이 후자를
     * 말하면 없는 기여를 주장하게 된다.</p>
     *
     * <p>{@code repository_full_name} 은 V13 이전 분석에서 비어 있을 수 있다.
     * 이름 없는 저장소는 요약이 가리킬 수 없으므로 뺀다.</p>
     */
    public List<RepositoryMine> repositories(long userId, String techId) {
        return jdbc.query(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT repository_full_name,
                       bool_or(coalesce(is_mine, false)) AS any_mine
                FROM mine
                WHERE repository_full_name IS NOT NULL
                GROUP BY repository_full_name
                ORDER BY repository_full_name
                """, (rs, row) -> new RepositoryMine(
                        rs.getString("repository_full_name"), rs.getBoolean("any_mine")),
                userId, userId, techId);
    }

    /**
     * 요약이 근거로 삼을 사실들. 선별과 중복 제거는 부르는 쪽이 한다.
     *
     * <p>여기서 자르지 않는 이유는 순서가 결정적이어야 하기 때문이다. 상한과
     * 정렬을 SQL 과 Java 에 나눠 두면 한쪽만 바뀌었을 때 Fact Pack 이 달라지고,
     * 그러면 캐시 키가 매번 달라져 같은 요약을 계속 다시 만든다.</p>
     */
    public List<EvidenceFact> facts(long userId, String techId) {
        return jdbc.query(LATEST_PER_REPOSITORY + EVIDENCE_OF_TECH + """
                SELECT fact_type, fact_payload::text AS payload, file_path, start_line, is_mine
                FROM mine
                """, (rs, row) -> new EvidenceFact(
                        rs.getString("fact_type"),
                        rs.getString("payload"),
                        rs.getString("file_path"),
                        rs.getInt("start_line"),
                        (Boolean) rs.getObject("is_mine")),
                userId, userId, techId);
    }

    private static Instant toInstant(java.sql.Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    private record Counts(int total, int mine, int judged) {
    }

    private record MissingRow(String ruleName, long clauseId, String expectedValue,
            boolean covered) {
    }

    /** 다음 Level 의 규칙 이름과, 아직 덮이지 않은 기대값들. */
    public record MissingClauses(String ruleName, List<String> missing) {
    }

    public record Span(Instant first, Instant last) {
    }

    public record RepositoryMine(String fullName, boolean mine) {
    }

    /**
     * 근거 한 줄.
     *
     * @param payloadJson {@code fact_payload} 원문. 어느 키를 읽을지는
     *                    {@code fact_type} 이 정하므로 여기서 풀지 않는다
     * @param mine        기여 판정이 없으면 {@code null}. {@code false} 와 구분해야
     *                    한다 -- 선별 순서에서 자리가 다르다
     */
    public record EvidenceFact(String factType, String payloadJson, String filePath,
            int startLine, Boolean mine) {
    }

    public record LevelRules(String level, List<String> ruleNames, boolean mine) {
    }
}
