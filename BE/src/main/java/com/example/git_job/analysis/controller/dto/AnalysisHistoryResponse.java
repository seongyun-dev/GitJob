package com.example.git_job.analysis.controller.dto;

import java.time.Instant;
import java.util.List;

/**
 * 분석 이력 목록 응답 (B-FN-009, 화면 14).
 *
 * <p>쪽 번호는 0부터다. 저장소 목록({@link PageResponse})이 쓰는 1-base 와 다른데,
 * 그쪽은 GitHub 페이지 번호를 그대로 넘겨받는 자리라 GitHub 규약을 따른다. 이 목록은
 * 우리 DB를 읽으므로 화면이 먼저 고정한 계약(`features/mypage/api/types.ts`)을 따른다.</p>
 *
 * <p>{@code totalCount}를 주는 것도 같은 이유다. GitHub은 전체 개수를 주지 않아 저장소
 * 목록이 {@code hasNext}만 알리지만, 여기서는 셀 수 있다.</p>
 *
 * @param analyzedAt  UTC ISO-8601. "오늘 10:42" 같은 상대 시각은 보는 시점에 따라
 *                    달라져 서버가 만들 수 없다 — 화면이 환산한다.
 */
public record AnalysisHistoryResponse(List<Item> items, int page, int size, int totalCount) {

    public record Item(String analysisId, Instant analyzedAt, List<String> repositories,
            String resultText, String status) {
    }
}
