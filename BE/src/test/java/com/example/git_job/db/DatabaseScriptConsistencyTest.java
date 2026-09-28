package com.example.git_job.db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.domain.AnalysisJob;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

/**
 * Checks the one place where the schema duplicates Java. Flyway owns the migrations now,
 * so the copies this test used to compare (db/init.sql against db/changes/*.sql) no longer
 * exist and cannot drift. It needs no database, so it runs on every build.
 */
class DatabaseScriptConsistencyTest {

    private static final Pattern ACTIVE_INDEX_PREDICATE = Pattern.compile(
            "CREATE UNIQUE INDEX uq_analysis_job_active.*?WHERE status IN \\(([^)]*)\\)",
            Pattern.DOTALL);

    /**
     * The partial index hardcodes the status list, and so does Java. A status present in one
     * but not the other quietly lets duplicate jobs through again, which is exactly the bug
     * the index exists to prevent.
     */
    @Test
    @DisplayName("uq_analysis_job_active의 상태 목록이 IN_PROGRESS_STATUSES와 같다")
    void theActiveJobIndexCoversExactlyTheInProgressStatuses() throws IOException {
        String path = "db/migration/V1__baseline_schema.sql";
        assertEquals(AnalysisJob.IN_PROGRESS_STATUSES, indexedStatuses(path),
                path + " disagrees with AnalysisJob.IN_PROGRESS_STATUSES");
    }

    /** Pulls the status list out of the partial index predicate. */
    private static Set<String> indexedStatuses(String path) throws IOException {
        String sql = new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
        Matcher matcher = ACTIVE_INDEX_PREDICATE.matcher(sql);
        assertTrue(matcher.find(), "uq_analysis_job_active not found in " + path);
        return Arrays.stream(matcher.group(1).split(","))
                .map(value -> value.trim().replace("'", ""))
                .filter(value -> !value.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
    }


}
