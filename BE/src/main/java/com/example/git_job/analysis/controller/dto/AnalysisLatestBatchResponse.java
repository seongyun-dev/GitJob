package com.example.git_job.analysis.controller.dto;

import java.time.Instant;
import java.util.List;

/**
 * 저장소 선택 화면이 읽는 "지금 무엇이 돌고 있나" 하나.
 *
 * <h2>{@code canSubmit}이 최상위인 이유</h2>
 *
 * <p>제출 차단은 <b>사용자 단위</b>이고 배치 단위가 아니다. V27 이전에 만들어진 분석은
 * {@code batch_id}가 없어 어떤 배치에도 속하지 않지만, 진행 중이면 저장소를 점유하고
 * 제출을 막는다. 이 값을 배치 안에 두면 그런 사용자가 "제출 가능"을 보고 눌렀다가 409를
 * 맞는다. 화면이 묻는 질문과 서버가 판정하는 질문이 같아야 한다.</p>
 *
 * <p>배치가 없으면 {@code batch}가 {@code null}이고 상태는 200이다. 404가 아닌 이유는
 * 화면의 HTTP 클라이언트가 404에서 예외를 던져, 분석을 한 번도 해 본 적 없는 사용자
 * 전원에게 오류 패널이 뜨기 때문이다.</p>
 *
 * <h2>{@code maxBatchSize}를 함께 내린다</h2>
 *
 * <p>한 번에 고를 수 있는 저장소 수를 화면이 지어내지 않게 하려는 것이다. 화면이 상수를
 * 들고 있으면 서버가 상한을 바꾼 날 조용히 어긋나고, 사용자는 버튼을 눌러야만 거절을
 * 알게 된다. 이 값이 있으면 고르는 동안 막을 수 있다.</p>
 */
public record AnalysisLatestBatchResponse(
        boolean canSubmit, int maxBatchSize, Batch batch) {

    /**
     * @param pollAfterSeconds 진행 중인 구성원이 없으면 {@code null}. 화면이 폴링을 멈추는
     *                         유일한 신호이고, 단건 조회와 같은 규약이다
     */
    public record Batch(
            String batchId,
            Instant requestedAt,
            int totalCount,
            int completedCount,
            int failedCount,
            Integer pollAfterSeconds,
            List<Item> items
    ) {
    }

    /**
     * 구성원 하나.
     *
     * <p>{@code currentStage}·{@code requestedAt}·{@code errorCode}·{@code commitSha}는
     * 선택 항목이 아니다. 저장소 카드가 각각 단계 한 줄, "요청 후 N분 경과", 실패 사유,
     * 기준 커밋 표시에 쓴다. 빼면 카드가 조용히 퇴화한다.</p>
     */
    public record Item(
            String analysisId,
            String repositoryId,
            String repositoryFullName,
            String branchName,
            String commitSha,
            String analysisStatus,
            String currentStage,
            Instant requestedAt,
            String errorCode
    ) {
    }

    /** 배치를 한 번도 만들지 않았거나, 마지막 배치가 보여 줄 기간을 지난 경우. */
    public static AnalysisLatestBatchResponse none(boolean canSubmit, int maxBatchSize) {
        return new AnalysisLatestBatchResponse(canSubmit, maxBatchSize, null);
    }
}
