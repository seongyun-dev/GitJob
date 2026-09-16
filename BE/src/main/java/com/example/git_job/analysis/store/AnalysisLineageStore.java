package com.example.git_job.analysis.store;

import com.example.git_job.analysis.event.AnalysisStats;
import com.example.git_job.analysis.event.RepositoryAnalysisResultPayload;
import com.example.git_job.analysis.event.TechnologySupportItem;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.json.JsonMapper;

/**
 * 분석 한 건의 판정 기준을 저장한다 (S15P21E102-279 후속).
 *
 * <p>{@code repository-analysis-result/v2} 부터 결과에 Rule Pack 계보와 기술별 지원
 * 범위가 실린다. 지금까지 BE 는 v1 만 받아 이 값을 버렸고, 그래서 C 에 보낼
 * {@code evidence_rule_version} 을 Registry 버전으로 대신하고 판정 상한을 관측된 최고
 * Level 로 만들었다. 둘 다 사실이 아니다.</p>
 *
 * <p>근거 행이 아니라 <b>분석</b>에 붙이는 이유가 있다. 등록 기술이 하나도 관측되지 않은
 * 분석은 근거 행이 0건이라 판정 기준을 어디에도 남길 수 없었고, 그 사용자는 C 계산
 * 대상에서 통째로 빠졌다. "분석했지만 아는 기술이 없었다"와 "분석하지 않았다"는 다른
 * 사실이며, 앞은 Skill Gap 을 받을 자격이 있다.</p>
 *
 * <p>호출자의 트랜잭션에 참여한다. 계보와 근거와 잡 상태가 함께 움직여야 한다.</p>
 */
@Repository
public class AnalysisLineageStore {

    private static final String UPDATE_JOB = """
            UPDATE analysis_job
               SET registry_version = ?,
                   rule_pack_version = ?,
                   rule_pack_content_sha256 = ?,
                   result_schema_version = ?,
                   skipped_reasons = ?::jsonb
             WHERE analysis_id = ?
            """;

    private static final String INSERT_SUPPORT = """
            INSERT INTO analysis_technology_support
                (analysis_id, tech_id, evaluation_scope, max_supported_level,
                 coverage, required_fact_types, limitations)
            VALUES (?, ?, ?, ?, ?, ?, ?::jsonb)
            ON CONFLICT (analysis_id, tech_id) DO UPDATE SET
                evaluation_scope = EXCLUDED.evaluation_scope,
                max_supported_level = EXCLUDED.max_supported_level,
                coverage = EXCLUDED.coverage,
                required_fact_types = EXCLUDED.required_fact_types,
                limitations = EXCLUDED.limitations
            """;

    private final JdbcTemplate jdbc;
    private final JsonMapper mapper = JsonMapper.builder().build();

    public AnalysisLineageStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 판정 기준을 남긴다.
     *
     * <p>v1 결과는 Rule Pack 계보를 갖고 있지 않다. 그때 Registry 버전을 대신 넣지
     * 않고 {@code null} 로 둔다 -- C 는 이 값으로 근거의 범위를 검사하므로, 틀린 값을
     * 넣으면 모든 근거가 조용히 버려지고 화면은 "근거는 있는데 아무것도 보유가 아닌"
     * 상태가 된다. 모른다고 남기면 조회 쪽이 그 분석을 재분석 대상으로 다룬다.</p>
     *
     * @return 저장한 기술 지원 행 수
     */
    public int record(String analysisId, String schemaVersion,
                      RepositoryAnalysisResultPayload payload) {
        jdbc.update(UPDATE_JOB,
                payload.registryVersion(),
                payload.rulePackVersion(),
                payload.rulePackContentSha256(),
                schemaVersion,
                skippedReasonsJson(payload.stats()),
                analysisId);

        List<TechnologySupportItem> support = payload.technologySupport();
        if (support.isEmpty()) {
            return 0;
        }
        jdbc.batchUpdate(INSERT_SUPPORT, support, support.size(), (statement, item) -> {
            statement.setString(1, analysisId);
            statement.setString(2, item.techId());
            statement.setString(3, item.evaluationScope());
            statement.setString(4, item.maxSupportedLevel());
            statement.setString(5, item.coverage());
            statement.setArray(6, statement.getConnection()
                    .createArrayOf("text", item.requiredFactTypes().toArray()));
            statement.setString(7, mapper.writeValueAsString(item.limitations()));
        });
        return support.size();
    }

    /**
     * 건너뛴 사유.
     *
     * <p>받지 못한 계약(v1)은 {@code null} 로 저장한다. 빈 객체로 바꾸면 "건너뛴 것이
     * 없다"가 되어 저장소 전체를 본 적 없는 분석이 완전 판정으로 나간다.</p>
     */
    private String skippedReasonsJson(AnalysisStats stats) {
        if (stats == null || !stats.reportedSkips()) {
            return null;
        }
        return mapper.writeValueAsString(stats.skippedReasons());
    }
}
