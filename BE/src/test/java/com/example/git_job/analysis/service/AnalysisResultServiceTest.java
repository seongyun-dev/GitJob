package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.AnalysisStats;
import com.example.git_job.analysis.event.EvidenceItem;
import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.event.RepositoryAnalysisResultPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisResultPayload.Status;
import com.example.git_job.analysis.event.TechnologyCandidate;
import com.example.git_job.analysis.event.TechnologyVerdict;
import com.example.git_job.analysis.outbox.AnalysisEvidenceStore;
import com.example.git_job.analysis.outbox.TechnologyCandidateStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisResultService.Applied;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Closing a job from a result event. The rule that matters here is idempotency:
 * delivery is at-least-once, so the same result arrives more than once.
 */
class AnalysisResultServiceTest {

    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final long USER_ID = 7L;

    private AnalysisJobRepository jobs;
    private AnalysisEvidenceStore evidence;
    private TechnologyCandidateStore candidates;
    private AnalysisResultService service;

    @BeforeEach
    void setup() {
        jobs = mock(AnalysisJobRepository.class);
        evidence = mock(AnalysisEvidenceStore.class);
        candidates = mock(TechnologyCandidateStore.class);
        service = new AnalysisResultService(jobs, evidence, candidates);
        when(evidence.insertAll(anyString(), anyLong(), anyString(), any(), any()))
                .thenReturn(1);
    }

    private AnalysisJob queuedJob() {
        return AnalysisJob.queue("an_1", USER_ID, "repo_1", "octocat/repo", "main", SHA,
                Instant.now());
    }

    private RepositoryAnalysisResultEvent completed() {
        return event(new RepositoryAnalysisResultPayload(
                "an_1", "ev_1", "registry-20260910.1", SHA, Status.COMPLETED, null, null,
                List.of(new TechnologyVerdict("spring-boot", TechnologyVerdict.Level.L1,
                        List.of("spring-boot.l1.import"))),
                List.of(new EvidenceItem("spring-boot.l1.import", "IMPORT",
                        "src/App.java", 3, 3, Map.of("MODULE", "org.springframework.boot"),
                        "import org.springframework.boot.SpringApplication;")),
                List.of(new TechnologyCandidate(TechnologyCandidate.Ecosystem.MAVEN,
                        "com.h2database:h2", "runtimeOnly", 1)),
                new AnalysisStats(50, 82, 471, 55, 1932742, 250)));
    }

    private RepositoryAnalysisResultEvent failed(String errorCode) {
        return event(new RepositoryAnalysisResultPayload(
                "an_1", "ev_1", "registry-20260910.1", SHA, Status.FAILED, errorCode,
                "git fetch could not find the repository",
                List.of(), List.of(), List.of(), null));
    }

    private RepositoryAnalysisResultEvent event(RepositoryAnalysisResultPayload payload) {
        return new RepositoryAnalysisResultEvent("res_ev_1",
                RepositoryAnalysisResultEvent.SCHEMA_VERSION,
                RepositoryAnalysisResultEvent.EVENT_TYPE,
                Instant.parse("2026-09-10T02:16:00Z"), "tr_1", payload);
    }

    @Test
    @DisplayName("성공 결과가 job을 SUCCEEDED로 닫고 Evidence를 쓴다")
    void aCompletedResultClosesTheJobAndWritesEvidence() {
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        Applied applied = service.apply(completed());

        assertEquals(Applied.SUCCEEDED, applied);
        assertEquals(AnalysisJob.STATUS_SUCCEEDED, job.getStatus());
        assertEquals(AnalysisJob.STAGE_COMPLETED, job.getCurrentStage());
        assertNull(job.getErrorCode());
        assertTrue(job.getCompletedAt() != null);
        verify(evidence).insertAll(anyString(), anyLong(), anyString(), any(), any());
        verify(jobs).save(job);
    }

    @Test
    @DisplayName("실패 결과가 job을 FAILED로 닫고 error_code를 남긴다")
    void aFailedResultClosesTheJobWithItsCode() {
        // Without this the user watches "대기 중" forever for a repository that
        // was deleted before the worker reached it.
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        Applied applied = service.apply(failed("REPOSITORY_NOT_FOUND"));

        assertEquals(Applied.FAILED, applied);
        assertEquals(AnalysisJob.STATUS_FAILED, job.getStatus());
        assertEquals("REPOSITORY_NOT_FOUND", job.getErrorCode());
    }

    @Test
    @DisplayName("같은 결과가 두 번 와도 두 번 적용되지 않는다")
    void aDuplicateResultIsIgnored() {
        // at-least-once 전달이라 반드시 일어난다. Evidence를 두 번 쓰면 화면에
        // 같은 근거가 두 줄로 뜬다.
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));
        service.apply(completed());

        Applied second = service.apply(completed());

        assertEquals(Applied.ALREADY_TERMINAL, second);
        verify(evidence).insertAll(anyString(), anyLong(), anyString(), any(), any());
        verify(jobs).save(job);
    }

    @Test
    @DisplayName("취소된 job은 결과가 도착해도 다시 열리지 않는다")
    void aResultDoesNotReopenACancelledJob() {
        // The job status is the idempotency marker, and this case comes with it
        // for free: CANCELED is terminal, so the guard already covers it.
        AnalysisJob job = queuedJob();
        job.fail("CANCELED_BY_USER", Instant.now());
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        Applied applied = service.apply(completed());

        assertEquals(Applied.ALREADY_TERMINAL, applied);
        assertEquals(AnalysisJob.STATUS_FAILED, job.getStatus());
        verify(evidence, never()).insertAll(anyString(), anyLong(), anyString(), any(), any());
        verify(candidates, never()).record(anyString(), anyLong(), anyString(), any(), any());
    }

    @Test
    @DisplayName("모르는 analysis_id는 소비하고 넘어간다")
    void aResultForAnUnknownJobIsConsumed() {
        // Replaying it will not make the job exist, and leaving it uncommitted
        // would stop the partition.
        when(jobs.findById("an_1")).thenReturn(Optional.empty());

        assertEquals(Applied.UNKNOWN_JOB, service.apply(completed()));
        verify(evidence, never()).insertAll(anyString(), anyLong(), anyString(), any(), any());
        verify(candidates, never()).record(anyString(), anyLong(), anyString(), any(), any());
    }

    @Test
    @DisplayName("후보는 job의 소유자와 저장소로 관찰된다")
    void candidatesAreObservedAgainstTheJobsOwnerAndRepository() {
        // Neither is on the event: the worker never learns who owns an analysis,
        // and "how many users" is an aggregate it cannot see.
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        service.apply(completed());

        verify(candidates).record(
                org.mockito.ArgumentMatchers.eq("an_1"),
                org.mockito.ArgumentMatchers.eq(USER_ID),
                org.mockito.ArgumentMatchers.eq("repo_1"),
                org.mockito.ArgumentMatchers.argThat(list -> list.size() == 1),
                any());
    }

    @Test
    @DisplayName("중복 결과는 후보도 두 번 세지 않는다")
    void aDuplicateResultDoesNotObserveCandidatesTwice() {
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));
        service.apply(completed());

        service.apply(completed());

        verify(candidates).record(anyString(), anyLong(), anyString(), any(), any());
    }

    @Test
    @DisplayName("Evidence는 job의 user_id와 결과의 registry_version으로 쓴다")
    void evidenceIsWrittenWithTheJobsOwnerAndTheJudgingRegistry() {
        // user_id is not on the event: the worker never learns who owns an
        // analysis. registry_version has to be the one that judged, so evidence
        // stays traceable to the rules that produced it.
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        service.apply(completed());

        verify(evidence).insertAll(
                org.mockito.ArgumentMatchers.eq("an_1"),
                org.mockito.ArgumentMatchers.eq(USER_ID),
                org.mockito.ArgumentMatchers.eq("registry-20260910.1"),
                any(), any());
    }

    @Test
    @DisplayName("실패 결과는 Evidence를 쓰지 않는다")
    void aFailedResultWritesNoEvidence() {
        AnalysisJob job = queuedJob();
        when(jobs.findById("an_1")).thenReturn(Optional.of(job));

        service.apply(failed("CLONE_TIMEOUT"));

        // The contract forbids findings on a failure, so the list is empty and
        // the store is still called with it — the guard is the contract's, not
        // this service's, and duplicating it here would hide a contract change.
        verify(evidence).insertAll(anyString(), anyLong(), anyString(),
                org.mockito.ArgumentMatchers.argThat(List::isEmpty), any());
    }

}
