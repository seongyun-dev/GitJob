package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.controller.dto.AnalysisLatestBatchResponse;
import com.example.git_job.analysis.store.AnalysisBatchStore;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** "2/4"와 제출 차단이 서로 다른 말을 하지 않는지가 이 서비스의 전부다. */
class AnalysisLatestBatchServiceTest {

    private static final long USER_ID = 42L;
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";
    private static final Duration VISIBLE_FOR = Duration.ofMinutes(30);

    private AnalysisBatchStore batches;
    private AnalysisRequestService requests;
    private AnalysisLatestBatchService service;

    @BeforeEach
    void setUp() {
        batches = mock(AnalysisBatchStore.class);
        requests = mock(AnalysisRequestService.class);
        service = new AnalysisLatestBatchService(batches, requests,
                new AnalysisRequestProperties(2, Duration.ofHours(2), VISIBLE_FOR, 10));
        when(requests.hasActiveAnalysis(USER_ID)).thenReturn(false);
    }

    private AnalysisBatchStore.Row row(String analysisId, String status, Instant completedAt) {
        return new AnalysisBatchStore.Row(analysisId, "ab_1", "555", "octocat/repo", "main",
                SHA, status, "WAITING_FOR_WORKER", null,
                Instant.parse("2026-09-20T00:00:00Z"), completedAt);
    }

    @Test
    @DisplayName("배치가 없으면 batch는 null이고 그래도 200이다")
    void noBatchIsNotAnError() {
        when(batches.latestBatch(USER_ID)).thenReturn(List.of());

        AnalysisLatestBatchResponse response = service.get(USER_ID);

        // 404로 만들면 분석을 한 번도 해 본 적 없는 사용자 전원에게 오류 패널이 뜬다.
        assertNull(response.batch());
        assertTrue(response.canSubmit());
    }

    @Test
    @DisplayName("끝난 구성원 수를 센다 — 2/4")
    void countsCompletedMembers() {
        Instant now = Instant.now();
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                row("an_1", "SUCCEEDED", now),
                row("an_2", "FAILED", now),
                row("an_3", "QUEUED", null),
                row("an_4", "ANALYZING", null)));

        AnalysisLatestBatchResponse.Batch batch = service.get(USER_ID).batch();

        assertEquals(4, batch.totalCount());
        assertEquals(2, batch.completedCount());
        assertEquals(1, batch.failedCount());
        assertEquals(5, batch.pollAfterSeconds());
    }

    @Test
    @DisplayName("전부 끝나면 폴링을 멈추라고 알린다")
    void stopsPollingWhenEveryMemberIsDone() {
        Instant now = Instant.now();
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                row("an_1", "SUCCEEDED", now), row("an_2", "SUCCEEDED", now)));

        AnalysisLatestBatchResponse.Batch batch = service.get(USER_ID).batch();

        // 화면이 종료를 판정하지 않고 이 값만 본다. null 이 유일한 정지 신호다.
        assertNull(batch.pollAfterSeconds());
        assertEquals(2, batch.completedCount());
    }

    @Test
    @DisplayName("끝난 지 오래된 배치는 더 이상 내려주지 않는다")
    void forgetsBatchesThatFinishedLongAgo() {
        Instant longAgo = Instant.now().minus(VISIBLE_FOR).minus(Duration.ofMinutes(5));
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                row("an_1", "SUCCEEDED", longAgo)));

        // 며칠 만에 들어온 사용자에게 옛 배치가 "지금 진행 중"처럼 떠오르면 안 된다.
        assertNull(service.get(USER_ID).batch());
    }

    @Test
    @DisplayName("진행 중이면 얼마나 오래됐든 계속 보여 준다")
    void keepsShowingABatchThatIsStillRunning() {
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(row("an_1", "QUEUED", null)));

        assertEquals("ab_1", service.get(USER_ID).batch().batchId());
    }

    @Test
    @DisplayName("canSubmit은 배치가 아니라 사용자 단위 판정을 그대로 쓴다")
    void canSubmitComesFromTheSameGateThePostUses() {
        when(requests.hasActiveAnalysis(USER_ID)).thenReturn(true);
        // 배치에 속하지 않은 옛 잡이 막고 있는 상황. 구성원은 전부 끝나 있다.
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                row("an_1", "SUCCEEDED", Instant.now())));

        AnalysisLatestBatchResponse response = service.get(USER_ID);

        // 배치 범위로 판정했다면 여기서 true가 나오고, 사용자는 눌렀다가 409를 맞는다.
        assertFalse(response.canSubmit());
        assertNull(response.batch().pollAfterSeconds());
    }

    @Test
    @DisplayName("워커가 쓰는 상태를 화면 계약의 다섯 값으로 접어 내린다")
    void foldsWorkerVocabularyIntoTheContractStatuses() {
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                row("an_1", "COLLECTING", null), row("an_2", "COMPLETED", Instant.now())));

        List<AnalysisLatestBatchResponse.Item> items = service.get(USER_ID).batch().items();

        assertEquals("RUNNING", items.get(0).analysisStatus());
        assertEquals("SUCCEEDED", items.get(1).analysisStatus());
    }

    @Test
    @DisplayName("저장소 카드가 그리는 네 값이 항목에 들어 있다")
    void itemsCarryEverythingTheRepositoryCardDraws() {
        when(batches.latestBatch(USER_ID)).thenReturn(List.of(
                new AnalysisBatchStore.Row("an_1", "ab_1", "555", "octocat/repo", "develop",
                        SHA, "FAILED", "FAILED", "ANALYSIS_TIMED_OUT",
                        Instant.parse("2026-09-20T00:00:00Z"), Instant.now())));

        AnalysisLatestBatchResponse.Item item = service.get(USER_ID).batch().items().get(0);

        assertEquals("FAILED", item.currentStage());
        assertEquals("ANALYSIS_TIMED_OUT", item.errorCode());
        assertEquals(SHA, item.commitSha());
        assertEquals(Instant.parse("2026-09-20T00:00:00Z"), item.requestedAt());
    }
}
