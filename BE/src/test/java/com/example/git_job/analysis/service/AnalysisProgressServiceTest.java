package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.domain.AnalysisStage;
import com.example.git_job.analysis.event.RepositoryAnalysisProgressEvent;
import com.example.git_job.analysis.event.RepositoryAnalysisProgressPayload;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisProgressService.Applied;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 진행 이벤트로 단계를 옮기는 규칙.
 *
 * <p>여기서 지키는 것은 "잘 옮긴다"가 아니라 <b>언제 옮기지 않는가</b>다. 진행
 * 토픽과 결과 토픽은 서로 다른 토픽이라 순서가 보장되지 않고, 전달은
 * at-least-once 이며, 클레임 테이크오버는 같은 분석을 처음부터 다시 돌린다. 셋 다
 * 정상 동작이라 코드가 막지 않으면 화면이 거꾸로 간다.</p>
 */
class AnalysisProgressServiceTest {

    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final long USER_ID = 7L;

    private AnalysisJobRepository jobs;
    private AnalysisProgressService service;

    @BeforeEach
    void setup() {
        jobs = mock(AnalysisJobRepository.class);
        service = new AnalysisProgressService(jobs);
    }

    private AnalysisJob queuedJob() {
        return AnalysisJob.queue("an_1", USER_ID, "repo_1", "octocat/repo", "main", SHA,
                Instant.now(), null);
    }

    @Test
    @DisplayName("대기 중인 분석을 저장소 분석 단계로 옮긴다")
    void movesQueuedJobToFirstStage() {
        AnalysisJob job = queuedJob();
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.of(job));

        assertEquals(Applied.MOVED, service.apply(event("ANALYZING_REPOSITORY")));

        // 상태는 계약 밖으로 나가지 않는다. ANALYZING 은 응답 경계에서 RUNNING 으로
        // 접히는 값이라 FE 계약이 그대로다.
        assertEquals(AnalysisJob.STATUS_ANALYZING, job.getStatus());
        assertEquals("ANALYZING_REPOSITORY", job.getCurrentStage());
        verify(jobs).save(job);
    }

    @Test
    @DisplayName("첫 단계 전환에서 시작 시각을 남기고, 다음 전환이 덮지 않는다")
    void stampsStartedAtOnceAndKeepsIt() {
        AnalysisJob job = queuedJob();
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.of(job));

        service.apply(event("ANALYZING_REPOSITORY"));
        Instant first = job.getStartedAt();
        service.apply(event("ATTRIBUTING_CONTRIBUTION"));

        // 사용자가 기다린 시간의 기준이다. 단계마다 새로 찍으면 "요청 후 N분"이
        // 단계가 넘어갈 때마다 0으로 돌아간다.
        assertNotNull(first);
        assertSame(first, job.getStartedAt());
    }

    @Test
    @DisplayName("이미 끝난 분석은 되돌리지 않는다")
    void neverReopensATerminalJob() {
        // 결과 토픽이 먼저 닿는 경우다. 두 토픽 사이에는 순서 보장이 없으므로
        // 드문 일이 아니라 정상 동작에 속한다.
        AnalysisJob job = queuedJob();
        job.succeed(Instant.now());
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.of(job));

        assertEquals(Applied.IGNORED, service.apply(event("ATTRIBUTING_CONTRIBUTION")));

        assertEquals(AnalysisJob.STATUS_SUCCEEDED, job.getStatus());
        assertEquals(AnalysisJob.STAGE_COMPLETED, job.getCurrentStage());
        verify(jobs, never()).save(any());
    }

    @Test
    @DisplayName("뒤로 가는 단계는 무시한다")
    void doesNotGoBackwards() {
        // 클레임 테이크오버로 같은 분석이 처음부터 다시 돈다. 실제로 다시 돌고 있는
        // 것은 맞지만, 화면이 거꾸로 가면 사용자는 진행이 취소됐다고 읽는다.
        AnalysisJob job = queuedJob();
        job.progress(AnalysisStage.ATTRIBUTING_CONTRIBUTION, Instant.now());
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.of(job));

        assertEquals(Applied.IGNORED, service.apply(event("ANALYZING_REPOSITORY")));

        assertEquals("ATTRIBUTING_CONTRIBUTION", job.getCurrentStage());
    }

    @Test
    @DisplayName("같은 단계가 다시 와도 한 번만 옮긴다")
    void isIdempotentForARedeliveredStage() {
        AnalysisJob job = queuedJob();
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.of(job));

        assertEquals(Applied.MOVED, service.apply(event("ANALYZING_REPOSITORY")));
        assertEquals(Applied.IGNORED, service.apply(event("ANALYZING_REPOSITORY")));
    }

    @Test
    @DisplayName("모르는 단계는 잡을 읽지도 않는다")
    void ignoresAStageThisVersionDoesNotKnow() {
        // 워커가 이 코드보다 새 버전일 때 정상적으로 일어난다. 배포 순서를 강제하지
        // 않기로 했으므로 실패가 아니라 무시다.
        assertEquals(Applied.UNKNOWN_STAGE, service.apply(event("SUMMARIZING")));

        verify(jobs, never()).findById(any());
    }

    @Test
    @DisplayName("종료 단계는 진행 토픽으로 받지 않는다")
    void refusesTerminalStagesFromTheProgressTopic() {
        // 종료는 결과 이벤트가 만든다. 두 경로가 같은 전이를 쓰면 근거를 저장하지
        // 않은 채 분석이 완료로 보일 수 있다.
        assertEquals(Applied.UNKNOWN_STAGE, service.apply(event("COMPLETED")));

        verify(jobs, never()).findById(any());
    }

    @Test
    @DisplayName("모르는 분석은 경고만 남기고 소비한다")
    void consumesProgressForAnUnknownJob() {
        // 재시도해도 생기지 않는다. 결과 경로와 같은 판단이다.
        when(jobs.findWithLockByAnalysisId("an_1")).thenReturn(Optional.empty());

        assertEquals(Applied.UNKNOWN_JOB, service.apply(event("ANALYZING_REPOSITORY")));

        verify(jobs, never()).save(any());
    }

    @Test
    @DisplayName("접수 직후에는 시작 시각이 비어 있다")
    void hasNoStartedAtBeforeTheFirstProgressEvent() {
        assertNull(queuedJob().getStartedAt());
    }

    private static RepositoryAnalysisProgressEvent event(String stage) {
        return new RepositoryAnalysisProgressEvent(
                "ev_progress_" + stage,
                RepositoryAnalysisProgressEvent.SCHEMA_VERSION,
                RepositoryAnalysisProgressEvent.EVENT_TYPE,
                Instant.parse("2026-09-18T01:02:03Z"),
                "tr_1",
                new RepositoryAnalysisProgressPayload("an_1", stage));
    }
}
