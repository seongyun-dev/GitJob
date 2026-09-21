package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.domain.Pageable;

/**
 * 이 스케줄러가 없으면 분석이 {@code QUEUED}에 영구히 남고, 그 저장소는
 * {@code uq_analysis_job_active}에 묶여 다시 요청할 수조차 없게 된다(2026-09 운영 장애).
 */
class StaleAnalysisReaperTest {

    private static final Duration WINDOW = Duration.ofHours(2);
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";

    private AnalysisJobRepository jobs;
    private StaleAnalysisReaper reaper;

    @BeforeEach
    void setUp() {
        jobs = mock(AnalysisJobRepository.class);
        reaper = new StaleAnalysisReaper(jobs,
                new AnalysisRequestProperties(2, WINDOW, Duration.ofMinutes(30), 10));
    }

    private AnalysisJob queued(String analysisId, Instant requestedAt) {
        return AnalysisJob.queue(analysisId, 42L, "555", "octocat/repo", "main", SHA,
                requestedAt, "ab_1");
    }

    @Test
    @DisplayName("유효시간을 넘긴 분석을 ANALYSIS_TIMED_OUT으로 종료시킨다")
    void reapsJobsOlderThanTheWindow() {
        AnalysisJob stale = queued("an_stale", Instant.now().minus(Duration.ofHours(49)));
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any()))
                .thenReturn(List.of(stale));

        reaper.reapStale();

        assertEquals(AnalysisJob.STATUS_FAILED, stale.getStatus());
        assertEquals(AnalysisJob.ERROR_ANALYSIS_TIMED_OUT, stale.getErrorCode());
        // 종료로 옮겨야 uq_analysis_job_active 가 풀려 같은 저장소를 다시 요청할 수 있다.
        assertEquals(AnalysisJob.STAGE_FAILED, stale.getCurrentStage());
        verify(jobs).save(stale);
    }

    @Test
    @DisplayName("조회 기준은 IN_PROGRESS_STATUSES와 activeWindow 그대로다")
    void queriesWithTheSameStatusesAndWindowTheGateUses() {
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any())).thenReturn(List.of());
        Instant before = Instant.now();

        reaper.reapStale();

        @SuppressWarnings("unchecked")
        ArgumentCaptor<java.util.Collection<String>> statuses =
                ArgumentCaptor.forClass(java.util.Collection.class);
        ArgumentCaptor<Instant> threshold = ArgumentCaptor.forClass(Instant.class);
        verify(jobs).findByStatusInAndRequestedAtBefore(
                statuses.capture(), threshold.capture(), any(Pageable.class));

        /*
         * 상태 목록이 어긋나면 어떤 상태의 분석은 영원히 정리되지 않는다. 제출 차단이
         * 쓰는 집합과 같아야 한다.
         */
        assertEquals(AnalysisJob.IN_PROGRESS_STATUSES,
                new java.util.HashSet<>(statuses.getValue()));
        assertTrue(threshold.getValue().isBefore(before.minus(WINDOW).plusSeconds(5)));
        assertTrue(threshold.getValue().isAfter(before.minus(WINDOW).minusSeconds(5)));
    }

    @Test
    @DisplayName("조회와 종료 사이에 워커가 끝낸 분석은 덮어쓰지 않는다")
    void doesNotOverwriteAJobTheWorkerFinishedInTheMeantime() {
        AnalysisJob finished = queued("an_done", Instant.now().minus(Duration.ofHours(49)));
        finished.succeed(Instant.now());
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any()))
                .thenReturn(List.of(finished));

        reaper.reapStale();

        assertEquals(AnalysisJob.STATUS_SUCCEEDED, finished.getStatus());
        assertEquals(null, finished.getErrorCode());
        verify(jobs, never()).save(any());
    }

    @Test
    @DisplayName("한 tick이 처리할 건수를 묶어 오래 밀린 상태에서도 트랜잭션이 커지지 않는다")
    void limitsHowManyJobsOneTickTouches() {
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any())).thenReturn(List.of());

        reaper.reapStale();

        ArgumentCaptor<Pageable> page = ArgumentCaptor.forClass(Pageable.class);
        verify(jobs).findByStatusInAndRequestedAtBefore(any(), any(), page.capture());
        assertEquals(20, page.getValue().getPageSize());
        assertEquals(0, page.getValue().getPageNumber());
    }

    @Test
    @DisplayName("정리할 것이 없으면 아무것도 저장하지 않는다")
    void savesNothingWhenNothingIsStale() {
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any())).thenReturn(List.of());

        reaper.reapStale();

        verify(jobs, never()).save(any());
        verify(jobs, never()).saveAndFlush(any());
    }

    @Test
    @DisplayName("여러 건이 밀려 있으면 전부 종료시킨다")
    void reapsEveryStaleJobInThePage() {
        AnalysisJob first = queued("an_1", Instant.now().minus(Duration.ofHours(5)));
        AnalysisJob second = queued("an_2", Instant.now().minus(Duration.ofHours(6)));
        when(jobs.findByStatusInAndRequestedAtBefore(any(), any(), any()))
                .thenReturn(List.of(first, second));

        reaper.reapStale();

        verify(jobs).save(eq(first));
        verify(jobs).save(eq(second));
    }
}
