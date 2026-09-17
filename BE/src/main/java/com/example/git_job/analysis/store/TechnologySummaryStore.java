package com.example.git_job.analysis.store;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * 저장된 요약을 읽고 쓴다.
 *
 * <p>사용자 한 명의 기술 하나에 한 행이다. 입력이 바뀌면 옛 요약은 쓸 데가
 * 없으므로 덮어쓴다 -- 해시를 키에 넣어 이력을 쌓으면 레벨이 오를 때마다 행이
 * 늘고 아무도 지우지 않는다.</p>
 */
@Repository
public class TechnologySummaryStore {

    private final JdbcTemplate jdbc;

    public TechnologySummaryStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 저장된 요약. 입력이나 프롬프트가 그때와 다르면 비어 있다.
     *
     * <p>{@code promptVersion} 을 조건에 넣는 이유는, 프롬프트가 바뀌면 지금
     * 프롬프트로는 나올 수 없는 문장이 화면에 남기 때문이다. 요약 서비스가
     * {@code /health} 로 현재 버전을 말해 준다.</p>
     *
     * <p>{@code promptVersion} 이 {@code null} 이면 버전을 따지지 않는다. 서비스가
     * 꺼져 있어 지금 버전을 물을 수 없다는 뜻인데, 그때는 조금 낡았을지 모르는
     * 요약이라도 보여주는 편이 빈 자리보다 낫다 -- 어차피 새로 만들 수도 없다.</p>
     */
    public Optional<Cached> find(long userId, String techId, String factPackSha256,
            String promptVersion) {
        List<Cached> found = jdbc.query("""
                SELECT llm_status, headline, summary, gap, confidence, generated_at
                FROM technology_summary
                WHERE user_id = ? AND tech_id = ?
                  AND fact_pack_sha256 = ?
                  AND (CAST(? AS TEXT) IS NULL OR prompt_version = ?)
                """, (rs, row) -> new Cached(
                        rs.getString("llm_status"),
                        rs.getString("headline"),
                        rs.getString("summary"),
                        rs.getString("gap"),
                        rs.getString("confidence"),
                        rs.getTimestamp("generated_at").toInstant()),
                userId, techId, factPackSha256, promptVersion, promptVersion);
        return found.stream().findFirst();
    }

    /** 사용자·기술마다 한 행이므로 충돌하면 덮어쓴다. */
    public void save(long userId, String techId, String factPackSha256, String cacheKey,
            String promptVersion, String model, String llmStatus, String headline,
            String summary, String gap, String confidence, List<Integer> usedHighlights,
            Instant generatedAt) {
        Integer[] highlights = usedHighlights == null
                ? new Integer[0]
                : usedHighlights.toArray(new Integer[0]);
        jdbc.update("""
                INSERT INTO technology_summary (user_id, tech_id, fact_pack_sha256, cache_key,
                    prompt_version, model, llm_status, headline, summary, gap, confidence,
                    used_highlights, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, tech_id) DO UPDATE SET
                    fact_pack_sha256 = EXCLUDED.fact_pack_sha256,
                    cache_key = EXCLUDED.cache_key,
                    prompt_version = EXCLUDED.prompt_version,
                    model = EXCLUDED.model,
                    llm_status = EXCLUDED.llm_status,
                    headline = EXCLUDED.headline,
                    summary = EXCLUDED.summary,
                    gap = EXCLUDED.gap,
                    confidence = EXCLUDED.confidence,
                    used_highlights = EXCLUDED.used_highlights,
                    generated_at = EXCLUDED.generated_at
                """, userId, techId, factPackSha256, cacheKey, promptVersion, model,
                llmStatus, headline, summary, gap, confidence, highlights,
                Timestamp.from(generatedAt));
    }

    public record Cached(String llmStatus, String headline, String summary, String gap,
            String confidence, Instant generatedAt) {
    }
}
