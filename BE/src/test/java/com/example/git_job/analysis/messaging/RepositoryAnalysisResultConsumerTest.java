package com.example.git_job.analysis.messaging;

import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.service.AnalysisResultService;
import com.example.git_job.analysis.service.AnalysisResultService.Applied;
import com.example.git_job.analysis.service.EvidenceAuthorshipService;
import com.example.git_job.compute.service.CComputeSyncService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

class RepositoryAnalysisResultConsumerTest {

    private AnalysisResultService results;
    private EvidenceAuthorshipService authorship;
    private CComputeSyncService compute;
    private RepositoryAnalysisResultConsumer consumer;
    private RepositoryAnalysisResultEvent event;
    private AnalysisJob job;

    @BeforeEach
    void setUp() {
        results = mock(AnalysisResultService.class);
        authorship = mock(EvidenceAuthorshipService.class);
        compute = mock(CComputeSyncService.class);
        consumer = new RepositoryAnalysisResultConsumer(results, authorship, compute);
        event = mock(RepositoryAnalysisResultEvent.class);
        job = mock(AnalysisJob.class);
        when(job.getAnalysisId()).thenReturn("analysis-1");
        when(job.getUserId()).thenReturn(7L);
        when(results.apply(event)).thenReturn(Applied.SUCCEEDED);
        when(results.attributionTarget(event, Applied.SUCCEEDED)).thenReturn(job);
    }

    @Test
    @DisplayName("기여 판정이 끝났다는 상태를 저장한 뒤에만 C 계산을 시작한다")
    void marksComputeReadyAfterAuthorshipAndBeforeCompute() {
        consumer.onResult(event);

        InOrder order = inOrder(authorship, results, compute);
        order.verify(authorship).attribute(job);
        order.verify(results).markComputeReady("analysis-1");
        order.verify(compute).synchronize(7L);
    }

    @Test
    @DisplayName("기여 판정 실패도 종료 상태로 기록하고 미확인 근거로 계산한다")
    void marksComputeReadyWhenAuthorshipFails() {
        when(authorship.attribute(job)).thenThrow(new IllegalStateException("github down"));

        consumer.onResult(event);

        verify(results).markComputeReady("analysis-1");
        verify(compute).synchronize(7L);
    }
}
