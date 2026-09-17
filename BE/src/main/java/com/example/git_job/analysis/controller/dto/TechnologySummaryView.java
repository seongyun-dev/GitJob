package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.service.TechnologySummaryService;
import com.example.git_job.analysis.service.TechnologySummaryService.SummaryResult;

/**
 * 카드에 얹을 한 문단.
 *
 * <p>{@code summary} 가 {@code null} 이면 아직 없다는 뜻이다. 오류가 아니다 --
 * 요약 서비스는 노트북 GPU 위에 있어 꺼져 있는 것이 정상적으로 자주 일어나고,
 * 카드는 수준·근거·permalink 로 이미 완성돼 있다.</p>
 *
 * <p>{@code status} 로 없는 이유를 가른다. {@code PENDING} 은 GPU 자리가 없어 아직
 * 못 만들었다는 뜻이고 {@code retryAfterSeconds} 뒤에 다시 물으면 채워진다.
 * {@code NONE} 은 다시 물어도 같다. 둘을 같은 얼굴로 내리면 화면은 새로 고칠
 * 때마다 같은 자리가 비는 것을 보면서 그것이 영구적인지 알 수 없다 -- 카드 열두
 * 장이 한꺼번에 들어오면 GPU 자리가 둘뿐이라 대부분이 PENDING 이다.</p>
 *
 * <p>{@code llmStatus} 가 {@code FALLBACK} 이어도 화면은 {@code OK} 와 다르게
 * 그리지 않는다. 데이터에서 만든 문장이라는 사실은 되짚을 때만 쓴다.</p>
 */
public record TechnologySummaryView(
        String techId,
        /** {@code READY} · {@code PENDING} · {@code NONE} */
        String status,
        /** {@code PENDING} 일 때만 0 보다 크다. */
        int retryAfterSeconds,
        String headline,
        String summary,
        String gap,
        String confidence,
        String llmStatus
) {

    public static TechnologySummaryView of(String techId, SummaryResult result) {
        TechnologySummaryService.Summary summary = result.summary();
        if (summary == null) {
            return new TechnologySummaryView(techId, result.status().name(),
                    result.retryAfterSeconds(), null, null, null, null, null);
        }
        return new TechnologySummaryView(techId, result.status().name(),
                result.retryAfterSeconds(), summary.headline(), summary.summary(),
                summary.gap(), summary.confidence(), summary.llmStatus());
    }
}
