package com.example.git_job.analysis.outbox;

import com.example.git_job.analysis.event.EvidenceItem;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.json.JsonMapper;

/**
 * Writes the evidence rows one analysis produced.
 *
 * <p>JdbcTemplate rather than JPA, for the same reason the outbox uses it: this
 * is a bulk insert of up to two thousand rows in one transaction, and a
 * persistence context that tracks every one of them buys nothing here. It also
 * keeps {@code fact_payload} as the jsonb the column actually is, instead of a
 * mapping that has to be taught the type.</p>
 *
 * <p>Participates in the caller's transaction, so evidence and the job status
 * move together. A crash between them would leave a finished job with no
 * evidence, which reads as "this repository uses nothing".</p>
 */
@Repository
public class AnalysisEvidenceStore {

    private static final String INSERT = """
            INSERT INTO analysis_evidence
                (analysis_id, user_id, rule_id, file_path, start_line, end_line,
                 fact_type, fact_payload, code_snippet, snippet_hash,
                 matched_at, registry_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?)
            """;

    private final JdbcTemplate jdbc;
    private final JsonMapper mapper = JsonMapper.builder().build();

    public AnalysisEvidenceStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public int insertAll(String analysisId, long userId, String registryVersion,
            List<EvidenceItem> items, Instant matchedAt) {
        if (items.isEmpty()) {
            return 0;
        }
        Timestamp matched = Timestamp.from(matchedAt);
        int[][] applied = jdbc.batchUpdate(INSERT, items, items.size(), (ps, item) -> {
            ps.setString(1, analysisId);
            ps.setLong(2, userId);
            ps.setString(3, item.ruleId());
            ps.setString(4, item.filePath());
            ps.setInt(5, item.startLine());
            ps.setInt(6, item.endLine());
            ps.setString(7, item.factType());
            ps.setString(8, mapper.writeValueAsString(item.factPayload()));
            ps.setString(9, item.codeSnippet());
            ps.setString(10, sha256(item.codeSnippet()));
            ps.setTimestamp(11, matched);
            ps.setString(12, registryVersion);
        });
        return java.util.Arrays.stream(applied).flatMapToInt(java.util.Arrays::stream).sum();
    }

    /**
     * The hash exists so two evidence rows quoting the same line can be compared
     * without reading the snippet, and so a snippet that later has to be dropped
     * (a private repository, a takedown) leaves something to compare against.
     */
    private static String sha256(String snippet) {
        if (snippet == null) {
            return null;
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(snippet.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is required by the platform", impossible);
        }
    }
}
