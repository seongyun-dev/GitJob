package com.example.git_job.analysis.event;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.event.RepositoryAnalysisResultPayload.Status;
import com.example.git_job.analysis.event.TechnologyCandidate.Ecosystem;
import com.example.git_job.analysis.event.TechnologyVerdict.Level;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * The consuming half of the result contract. The producing half is
 * AI/tests/test_analysis_results.py, and both check the same rules on purpose:
 * the two services deploy separately, so neither can assume the other is current.
 */
class RepositoryAnalysisResultEventTest {

    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";

    @Test
    void acceptsACompletedResultWithItsFindings() {
        RepositoryAnalysisResultEvent event = completed();

        assertEquals("an_1", event.payload().analysisId());
        assertFalse(event.payload().failed());
        assertEquals(Level.L3, event.payload().technologies().getFirst().level());
        assertEquals(3, event.payload().evidence().getFirst().startLine());
        assertEquals("org.postgresql:postgresql",
                event.payload().candidates().getFirst().coordinate());
    }

    @Test
    void carriesFailureOnThisTopicRatherThanLeavingItInTheDlq() {
        // Without this the job stays QUEUED forever and the user never learns
        // that their deleted repository could not be analyzed.
        RepositoryAnalysisResultPayload payload = failedPayload("REPOSITORY_NOT_FOUND");

        assertTrue(payload.failed());
        assertEquals("REPOSITORY_NOT_FOUND", payload.errorCode());
    }

    @Test
    void refusesAFailureWithoutACode() {
        IllegalArgumentException thrown = assertThrows(IllegalArgumentException.class,
                () -> failedPayload(null));
        assertTrue(thrown.getMessage().contains("errorCode"));
    }

    @Test
    void refusesAFailureThatAlsoReportsFindings() {
        // This service would write evidence rows for an analysis it is about to
        // mark failed.
        IllegalArgumentException thrown = assertThrows(IllegalArgumentException.class,
                () -> new RepositoryAnalysisResultPayload("an_1", "ev_1",
                        "registry-20260908.1", SHA, Status.FAILED, "CLONE_TIMEOUT", null,
                        List.of(verdict()), List.of(), List.of(), null, null, null, List.of()));
        assertTrue(thrown.getMessage().contains("must not carry findings"));
    }

    @Test
    void refusesASuccessThatCarriesAnErrorCode() {
        assertThrows(IllegalArgumentException.class,
                () -> new RepositoryAnalysisResultPayload("an_1", "ev_1",
                        "registry-20260908.1", SHA, Status.COMPLETED, "CLONE_TIMEOUT", null,
                        List.of(), List.of(), List.of(), null, null, null, List.of()));
    }

    @Test
    void treatsNothingMatchedAsASuccess() {
        // Only status separates this from a failure, which is exactly what a
        // wrong registry_version would silently imitate.
        RepositoryAnalysisResultPayload payload = new RepositoryAnalysisResultPayload(
                "an_1", "ev_1", "registry-20260908.1", SHA, Status.COMPLETED,
                null, null, List.of(), List.of(), List.of(), null, null, null, List.of());

        assertFalse(payload.failed());
        assertTrue(payload.technologies().isEmpty());
    }

    @Test
    void acceptsTheRulePackContracts() {
        // 워커는 Registry 버전에 따라 발행 계약을 바꾸며 v1 을 함께 보내지 않는다.
        // v2·v3 를 거절하면 registry-20260911.3/.4 결과가 통째로 도달하지 않는다.
        for (String version : RepositoryAnalysisResultEvent.SUPPORTED_SCHEMA_VERSIONS) {
            RepositoryAnalysisResultEvent event = new RepositoryAnalysisResultEvent("ev_r1",
                    version, RepositoryAnalysisResultEvent.EVENT_TYPE,
                    Instant.parse("2026-09-10T01:02:03Z"), "tr_1", completedPayload());
            assertEquals(version, event.schemaVersion());
        }
    }

    @Test
    void refusesAVersionItDoesNotImplement() {
        // v4 는 개인 귀속(personal_assessments)이 붙는 계약이고 저장할 자리가 없다.
        // 반쯤 해석한 결과를 저장하면 그 사실이 어디에도 남지 않는다.
        assertThrows(IllegalArgumentException.class,
                () -> new RepositoryAnalysisResultEvent("ev_r1",
                        "repository-analysis-result/v4",
                        RepositoryAnalysisResultEvent.EVENT_TYPE,
                        Instant.parse("2026-09-10T01:02:03Z"), "tr_1", completedPayload()));
    }

    @Test
    void refusesAnAbbreviatedCommitSha() {
        // Evidence permalinks are built from this, and an abbreviated sha would
        // produce links that break when the repository grows.
        assertThrows(IllegalArgumentException.class,
                () -> new RepositoryAnalysisResultPayload("an_1", "ev_1",
                        "registry-20260908.1", "818c4136ea97", Status.COMPLETED,
                        null, null, List.of(), List.of(), List.of(), null, null, null, List.of()));
    }

    @Test
    void refusesAVerdictWithoutTheRulesBehindIt() {
        assertThrows(IllegalArgumentException.class,
                () -> new TechnologyVerdict("redis", Level.L1, List.of()));
    }

    @Test
    void refusesAnInvertedLineRange() {
        assertThrows(IllegalArgumentException.class,
                () -> new EvidenceItem("r", "IMPORT", "a.java", 10, 9, Map.of(), null, null));
    }

    @Test
    void keepsCandidateScopeSoTestOnlyUseStaysDistinguishable() {
        // Re-deriving scope later would mean cloning the repository again.
        TechnologyCandidate candidate = new TechnologyCandidate(Ecosystem.MAVEN,
                "org.testcontainers:testcontainers", "testImplementation", 2);

        assertEquals("testImplementation", candidate.scope());
    }

    @Test
    void defaultsMissingCollectionsToEmptyRatherThanNull() {
        // The worker omits them on a failure, and a null list here would become
        // a NullPointerException in the consumer rather than a clear contract error.
        RepositoryAnalysisResultPayload payload = new RepositoryAnalysisResultPayload(
                "an_1", "ev_1", "registry-20260908.1", SHA, Status.FAILED,
                "CLONE_TIMEOUT", null, null, null, null, null, null, null, List.of());

        assertTrue(payload.technologies().isEmpty());
        assertTrue(payload.evidence().isEmpty());
        assertTrue(payload.candidates().isEmpty());
    }

    private static RepositoryAnalysisResultEvent completed() {
        return new RepositoryAnalysisResultEvent("ev_r1",
                RepositoryAnalysisResultEvent.SCHEMA_VERSION,
                RepositoryAnalysisResultEvent.EVENT_TYPE,
                Instant.parse("2026-09-10T01:02:03Z"), "tr_1", completedPayload());
    }

    private static RepositoryAnalysisResultPayload completedPayload() {
        return new RepositoryAnalysisResultPayload("an_1", "ev_1", "registry-20260908.1",
                SHA, Status.COMPLETED, null, null,
                List.of(verdict()),
                List.of(new EvidenceItem("spring-boot.l1.java-import", "IMPORT",
                        "src/main/java/App.java", 3, 3,
                        Map.of("MODULE", "org.springframework.boot.SpringApplication"), null, null)),
                List.of(new TechnologyCandidate(Ecosystem.MAVEN,
                        "org.postgresql:postgresql", "runtimeOnly", 1)),
                new AnalysisStats(50, 82, 471, 17, 1932742L, 1400L, Map.of(), 0),
                null, null, List.of());
    }

    private static RepositoryAnalysisResultPayload failedPayload(String errorCode) {
        return new RepositoryAnalysisResultPayload("an_1", "ev_1", "registry-20260908.1",
                SHA, Status.FAILED, errorCode, "git fetch could not find the repository",
                List.of(), List.of(), List.of(), null, null, null, List.of());
    }

    private static TechnologyVerdict verdict() {
        return new TechnologyVerdict("spring-boot", Level.L3,
                List.of("spring-boot.l1.java-import", "spring-boot.l3.actuator"));
    }
}
