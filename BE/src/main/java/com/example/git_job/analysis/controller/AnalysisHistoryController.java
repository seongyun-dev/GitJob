package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.AnalysisHistoryResponse;
import com.example.git_job.analysis.controller.dto.AnalysisLatestBatchResponse;
import com.example.git_job.analysis.service.AnalysisHistoryService;
import com.example.git_job.analysis.service.AnalysisLatestBatchService;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.security.CurrentUser;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 마이페이지 분석 이력 (B-FN-009, 화면 14).
 *
 * <p>대상 사용자는 항상 세션의 주인이다. 경로나 파라미터로 사용자 ID를 받지 않으므로
 * 남의 이력을 요청할 방법이 없다 — 저장소 목록과 같은 규칙이다.</p>
 */
@RestController
@RequestMapping("/api/v1/me/analyses")
@RequiredArgsConstructor
public class AnalysisHistoryController {

    private final AnalysisHistoryService analyses;
    private final AnalysisLatestBatchService latestBatch;

    @GetMapping
    public ApiResponse<AnalysisHistoryResponse> analyses(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size
    ) {
        return ApiResponse.success(analyses.list(CurrentUser.idOf(user), page, size));
    }

    /**
     * 저장소 선택 화면이 읽는 "지금 무엇이 돌고 있나" (S15P21E102-136).
     *
     * <p>{@code /active}라고 부르지 않는다. 끝난 배치도 잠시 돌려주므로 이름이 사실과
     * 어긋나고, 화면이 영원히 폴링해야 할 대상처럼 읽힌다.</p>
     *
     * <p>배치가 없어도 200이다. 상세는 {@code AnalysisLatestBatchResponse} 참고.</p>
     */
    @GetMapping("/latest-batch")
    public ApiResponse<AnalysisLatestBatchResponse> latestBatch(
            @AuthenticationPrincipal AuthenticatedUser user
    ) {
        return ApiResponse.success(latestBatch.get(CurrentUser.idOf(user)));
    }
}
