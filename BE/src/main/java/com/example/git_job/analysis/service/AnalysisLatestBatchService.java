package com.example.git_job.analysis.service;

import com.example.git_job.analysis.controller.dto.AnalysisLatestBatchResponse;
import com.example.git_job.analysis.controller.dto.AnalysisStatusResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.store.AnalysisBatchStore;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 저장소 선택 화면이 읽는 배치 하나 (S15P21E102-136).
 *
 * <h2>종료 판정을 한 군데서만 한다</h2>
 *
 * <p>{@link AnalysisJob#IN_PROGRESS_STATUSES}가 유일한 기준이다.
 * {@code AnalysisStatusResponse.normalize()}도 종료를 판정할 수 있지만 두 목록은 따로
 * 관리되고, 애초에 {@code normalize}가 존재하는 이유가 "워커가 BE 모르는 값을 쓸 수
 * 있다"는 것이다. 두 술어를 섞으면 "2/4"와 차단 규칙이 어긋난 날이 온다.</p>
 *
 * <p>{@code normalize}는 화면에 보낼 상태 문자열을 만드는 데만 쓴다.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisLatestBatchService {

    /** 진행 중일 때 화면에 권하는 재조회 간격. 단건 조회와 같은 값이다. */
    private static final int POLL_AFTER_SECONDS = 5;

    private final AnalysisBatchStore batches;
    private final AnalysisRequestService requests;
    private final AnalysisRequestProperties properties;

    @Transactional(readOnly = true)
    public AnalysisLatestBatchResponse get(long userId) {
        boolean canSubmit = !requests.hasActiveAnalysis(userId);
        List<AnalysisBatchStore.Row> rows = batches.latestBatch(userId);
        if (rows.isEmpty()) {
            return AnalysisLatestBatchResponse.none(canSubmit, properties.maxBatchSize());
        }

        boolean running = rows.stream().anyMatch(this::inProgress);
        if (!running && !recentlyFinished(rows)) {
            /*
             * 끝난 지 오래된 배치다. 계속 내려주면 며칠 만에 들어온 사용자에게 옛 배치가
             * "지금 진행 중"처럼 떠오르고, 완료 패널과 초기화 버튼이 그때 시작한 적도 없는
             * 무언가를 가리킨다. 그 시점부터는 이력 화면이 말할 일이다.
             */
            return AnalysisLatestBatchResponse.none(canSubmit, properties.maxBatchSize());
        }

        var items = rows.stream().map(this::item).toList();
        var batch = new AnalysisLatestBatchResponse.Batch(
                rows.get(0).batchId(),
                rows.stream().map(AnalysisBatchStore.Row::requestedAt)
                        .min(Comparator.naturalOrder()).orElseThrow(),
                rows.size(),
                (int) rows.stream().filter(row -> !inProgress(row)).count(),
                (int) rows.stream()
                        .filter(row -> AnalysisStatusResponse.STATUS_FAILED
                                .equals(AnalysisStatusResponse.normalize(row.status())))
                        .count(),
                running ? POLL_AFTER_SECONDS : null,
                items);
        return new AnalysisLatestBatchResponse(canSubmit, properties.maxBatchSize(), batch);
    }

    private boolean inProgress(AnalysisBatchStore.Row row) {
        return AnalysisJob.IN_PROGRESS_STATUSES.contains(row.status());
    }

    /**
     * 끝난 지 얼마 안 된 배치인가.
     *
     * <p>{@code completed_at}이 비어 있으면 {@code requested_at}으로 대신한다.
     * {@code finish()}가 그 값을 항상 채우므로 정상 경로에서는 비지 않지만, 비는 순간
     * 배치가 화면에서 통째로 사라지는 실패 방식이라 기대고 싶지 않다.
     * {@code AnalysisHistoryStore}도 같은 이유로 {@code coalesce}를 쓴다.</p>
     */
    private boolean recentlyFinished(List<AnalysisBatchStore.Row> rows) {
        Instant cutoff = Instant.now().minus(properties.completedBatchVisibleFor());
        return rows.stream()
                .map(row -> row.completedAt() != null ? row.completedAt() : row.requestedAt())
                .anyMatch(finishedAt -> finishedAt.isAfter(cutoff));
    }

    private AnalysisLatestBatchResponse.Item item(AnalysisBatchStore.Row row) {
        return new AnalysisLatestBatchResponse.Item(
                row.analysisId(),
                row.repositoryId(),
                row.repositoryFullName(),
                row.branchName(),
                row.commitSha(),
                AnalysisStatusResponse.normalize(row.status()),
                row.currentStage(),
                row.requestedAt(),
                row.errorCode());
    }
}
