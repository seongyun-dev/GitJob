package com.example.git_job.analysis.event;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.kafka.support.serializer.JacksonJsonSerializer;

class RepositoryAnalysisRequestedEventTest {

    @Test
    void serializesTheVersionedSnakeCaseContractWithoutSecrets() {
        RepositoryAnalysisRequestedEvent event = validEvent();
        JacksonJsonSerializer<RepositoryAnalysisRequestedEvent> serializer =
                new JacksonJsonSerializer<>();

        String json = new String(
                serializer.serialize("repository-analysis", event),
                StandardCharsets.UTF_8
        );

        assertTrue(json.contains("\"event_id\":\"ev_01ABC\""));
        assertTrue(json.contains(
                "\"schema_version\":\"repository-analysis-request/v1\""
        ));
        assertTrue(json.contains(
                "\"event_type\":\"repository.analysis.requested\""
        ));
        assertTrue(json.contains("\"analysis_repository_id\":\"ar_01ABC\""));
        assertTrue(json.contains("\"github_repository_id\":123456789"));
        assertTrue(json.contains("\"branch_name\":\"feature/repository-analysis\""));
        assertTrue(json.contains(
                "\"commit_sha\":\"0123456789abcdef0123456789abcdef01234567\""
        ));
        assertTrue(json.contains("\"analysis_mode\":\"SNAPSHOT\""));
        assertFalse(json.contains("access_token"));
        assertFalse(json.contains("refresh_token"));
        assertFalse(json.contains("private_key"));
    }

    @Test
    void usesAnalysisRepositoryIdAsKafkaPartitionKey() {
        assertEquals("ar_01ABC", validEvent().partitionKey());
    }

    @Test
    void rejectsInvalidCommitSha() {
        assertThrows(
                IllegalArgumentException.class,
                () -> new RepositoryAnalysisRequestPayload(
                        "an_01ABC",
                        "ar_01ABC",
                        123456789L,
                        "octocat/gitjob",
                        "main",
                        "main",
                        RepositoryAnalysisMode.SNAPSHOT,
                        "technology-registry/v1"
                )
        );
    }

    @Test
    void rejectsRepositoryNamesThatCouldBecomeCommandArguments() {
        assertThrows(
                IllegalArgumentException.class,
                () -> new RepositoryAnalysisRequestPayload(
                        "an_01ABC",
                        "ar_01ABC",
                        123456789L,
                        "octocat/repository --upload-pack=malicious",
                        "main",
                        "0123456789abcdef0123456789abcdef01234567",
                        RepositoryAnalysisMode.SNAPSHOT,
                        "technology-registry/v1"
                )
        );
    }

    @Test
    void rejectsUnsupportedSchemaVersion() {
        RepositoryAnalysisRequestedEvent valid = validEvent();

        assertThrows(
                IllegalArgumentException.class,
                () -> new RepositoryAnalysisRequestedEvent(
                        valid.eventId(),
                        "repository-analysis-request/v2",
                        valid.eventType(),
                        valid.occurredAt(),
                        valid.traceId(),
                        valid.payload()
                )
        );
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t", " main", "main "})
    void rejectsMissingOrUntrimmedBranchName(String branchName) {
        assertThrows(
                IllegalArgumentException.class,
                () -> new RepositoryAnalysisRequestPayload(
                        "an_01ABC", "ar_01ABC", 123456789L,
                        "octocat/gitjob", branchName,
                        "0123456789abcdef0123456789abcdef01234567",
                        RepositoryAnalysisMode.SNAPSHOT, "technology-registry/v1"
                )
        );
    }

    private RepositoryAnalysisRequestedEvent validEvent() {
        return RepositoryAnalysisRequestedEvent.create(
                "ev_01ABC",
                Instant.parse("2026-09-07T10:00:00Z"),
                "tr_01ABC",
                new RepositoryAnalysisRequestPayload(
                        "an_01ABC",
                        "ar_01ABC",
                        123456789L,
                        "octocat/gitjob",
                        "feature/repository-analysis",
                        "0123456789abcdef0123456789abcdef01234567",
                        RepositoryAnalysisMode.SNAPSHOT,
                        "technology-registry/v1"
                )
        );
    }
}
