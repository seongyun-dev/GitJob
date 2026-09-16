package com.example.git_job.compute.controller;

import com.example.git_job.compute.controller.dto.JobDemandResponse;
import com.example.git_job.compute.controller.dto.TrendResponse;
import com.example.git_job.compute.service.JobDemandService;
import com.example.git_job.compute.service.TrendService;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.security.CurrentUser;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 개인 결과가 아닌 시장 지표 -- 직무별 수요와 기술 Trend (S15P21E102-279).
 *
 * <p>{@code /me} 아래가 아닌 이유는 이 값들이 사용자에 따라 달라지지 않기 때문이다.
 * 로그인은 확인하지만 소유권 검사는 없고, C에도 {@code user_id} 없이 공용 Snapshot으로
 * 조회한다. {@code user_id}를 붙이면 C가 소유자 조건으로 찾아 공용 결과를 못 찾는다.</p>
 *
 * <p>인증을 요구하는 것은 이 값이 비밀이어서가 아니라, 인증 없는 경로를 열면 C 계산을
 * 유발하는 endpoint가 공개망에 노출되기 때문이다.</p>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class MarketController {

    /** 화면 한 장이 보여 줄 수 있는 기술 수. C의 수요 목록은 이보다 길다. */
    private static final int DEFAULT_DEMAND_LIMIT = 20;
    private static final int MAX_DEMAND_LIMIT = 50;

    private final JobDemandService demands;
    private final TrendService trends;

    /**
     * 직무별 기술 수요.
     *
     * <p>목표 직무를 저장하지 않은 사용자도 조건을 직접 넣어 볼 수 있어야 하므로 조건을
     * 쿼리로 받는다. 개인 결과가 아니라 공용 집계라 이것이 안전하다.</p>
     */
    @GetMapping("/job-demands")
    public ResponseEntity<ApiResponse<JobDemandResponse>> jobDemands(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestParam String targetRole,
            @RequestParam(required = false) List<String> regions,
            @RequestParam(required = false) List<String> careerLevels,
            @RequestParam(required = false) Integer limit
    ) {
        return ResponseEntity.ok(ApiResponse.success(demands.demand(
                CurrentUser.idOf(user), targetRole,
                regions == null ? List.of() : regions,
                careerLevels == null ? List.of() : careerLevels,
                limit(limit))));
    }

    /**
     * 기술 하나의 출처별 추세.
     *
     * @param periods 월별 Archive를 볼 기간({@code 2026-06,2026-07}). 비우면 주간 출처만
     *                조회한다. 기간을 서버가 임의로 고르지 않는 이유는, 화면에 표시된
     *                기간과 실제 계산 기간이 달라지면 안 되기 때문이다.
     */
    @GetMapping("/technologies/{techId}/trends")
    public ResponseEntity<ApiResponse<TrendResponse>> trends(
            @PathVariable String techId,
            @RequestParam(required = false) List<String> periods
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                trends.trends(techId, periods == null ? List.of() : periods)));
    }

    /**
     * 기술 교차 비교. 한 번에 <b>한 출처만</b> 본다.
     *
     * <p>여러 출처를 한 표에 섞으면 분모가 다른 값이 한 축에 들어간다. 화면은 출처 카드마다
     * 이 API를 따로 부른다.</p>
     */
    @GetMapping("/trends/compare")
    public ResponseEntity<ApiResponse<TrendResponse.Compare>> compare(
            @RequestParam String source,
            @RequestParam List<String> techIds,
            @RequestParam(required = false) List<String> periods
    ) {
        return ResponseEntity.ok(ApiResponse.success(trends.compare(
                source, techIds, periods == null ? List.of() : periods)));
    }

    private static int limit(Integer limit) {
        if (limit == null || limit < 1) {
            return DEFAULT_DEMAND_LIMIT;
        }
        return Math.min(limit, MAX_DEMAND_LIMIT);
    }
}
