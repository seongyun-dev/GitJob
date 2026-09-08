package com.example.git_job.db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.domain.AnalysisJob;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

/**
 * db/init.sql builds a new database in one pass, while db/changes/*.sql add the same
 * objects to a database that already has the rest. Those statements are duplicated on
 * purpose, and this is what stops the copies from drifting apart. It also checks the one
 * place where SQL duplicates Java. It needs no database, so it runs on every build.
 *
 * <p>db/changes/002 and 003 are not compared: CDC objects are deliberately kept out of
 * init.sql so the schema file stays runnable without substituting a password, and 003
 * drops a constraint that init.sql simply no longer creates.</p>
 */
class DatabaseScriptConsistencyTest {

    private static final Pattern ACTIVE_INDEX_PREDICATE = Pattern.compile(
            "CREATE UNIQUE INDEX uq_analysis_job_active.*?WHERE status IN \\(([^)]*)\\)",
            Pattern.DOTALL);

    @Test
    void initSqlCarriesTheOutboxChangeScriptVerbatim() throws IOException {
        assertContainsInOrder(statements("db/init.sql"),
                statements("db/changes/001_analysis_outbox.sql"));
    }

    @Test
    void initSqlCarriesTheActiveJobIndexChangeScriptVerbatim() throws IOException {
        assertContainsInOrder(statements("db/init.sql"),
                statements("db/changes/004_analysis_job_active_unique.sql"));
    }

    /**
     * The partial index hardcodes the status list, and so does Java. A status present in one
     * but not the other quietly lets duplicate jobs through again, which is exactly the bug
     * the index exists to prevent.
     */
    @Test
    @DisplayName("uq_analysis_job_active의 상태 목록이 IN_PROGRESS_STATUSES와 같다")
    void theActiveJobIndexCoversExactlyTheInProgressStatuses() throws IOException {
        for (String path : List.of("db/init.sql", "db/changes/004_analysis_job_active_unique.sql")) {
            assertEquals(AnalysisJob.IN_PROGRESS_STATUSES, indexedStatuses(path),
                    path + " disagrees with AnalysisJob.IN_PROGRESS_STATUSES");
        }
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

    private static void assertContainsInOrder(List<String> whole, List<String> part) {
        assertFalse(part.isEmpty(), "the change script parsed to no statements");
        assertTrue(Collections.indexOfSubList(whole, part) >= 0,
                () -> "db/init.sql no longer contains these statements as one block:\n  "
                        + String.join("\n  ", part));
    }

    /** Comments go first: a comment may contain the ';' that would otherwise split a statement. */
    private static List<String> statements(String path) throws IOException {
        String sql = new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
        var withoutComments = new StringBuilder();
        for (String line : sql.split("\\R")) {
            int comment = line.indexOf("--");
            withoutComments.append(comment < 0 ? line : line.substring(0, comment)).append('\n');
        }
        List<String> statements = new ArrayList<>();
        for (String raw : withoutComments.toString().split(";")) {
            String normalized = raw.replaceAll("\\s+", " ").trim();
            if (!normalized.isEmpty()) {
                statements.add(normalized);
            }
        }
        return statements;
    }
}
