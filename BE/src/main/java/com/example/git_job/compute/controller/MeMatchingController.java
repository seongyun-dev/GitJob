package com.example.git_job.compute.controller;

import com.example.git_job.compute.controller.dto.JobMatchResponse;
import com.example.git_job.compute.controller.dto.RecommendationResponse;
import com.example.git_job.compute.controller.dto.SkillGapResponse;
import com.example.git_job.compute.controller.dto.TargetRequest;
import com.example.git_job.compute.controller.dto.TargetResponse;
import com.example.git_job.compute.controller.dto.WhatIfResponse;
import com.example.git_job.compute.service.ComputePaging;
import com.example.git_job.compute.service.JobMatchService;
import com.example.git_job.compute.service.SkillGapService;
import com.example.git_job.compute.service.TargetService;
import com.example.git_job.compute.service.WhatIfService;
import com.example.git_job.compute.store.UserTargetStore.Target;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.security.CurrentUser;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 내 공고 매칭·Skill Gap·추천·What-if (S15P21E102-279).
 *
 * <p>{@code /me} 아래라 대상은 언제나 인증된 본인이다. 사용자 ID도 Snapshot ID도 경로나
 * 파라미터로 받지 않는다 -- 받는 순간 남의 것을 요구할 수 있게 되고, 그 검사를 화면마다
 * 다시 해야 한다. 어느 Snapshot을 읽을지는 서버가 목표 직무와 최신 계산에서 정한다.</p>
 *
 * <p>여기서 계산하는 것은 없다. 점수·부합 여부·Gap·What-if 증가 수는 전부 C의 결론이고,
 * 이 층은 화면 DTO로 옮기고 페이징을 바꾸는 일만 한다.</p>
 */
@RestController
@RequestMapping("/api/v1/me")
@RequiredArgsConstructor
public class MeMatchingController {

    private final TargetService targets;
    private final JobMatchService matches;
    private final SkillGapService skillGaps;
    private final WhatIfService whatIfs;

    /**
     * 목표 직무. 고른 적이 없으면 {@code data}가 {@code null}이다.
     *
     * <p>404가 아닌 이유는 이 화면이 "직무를 고르는 화면"이기 때문이다. 아직 고르지 않은
     * 것은 정상이며, 조회 자체가 실패한 것이 아니다.</p>
     */
    @GetMapping("/target")
    public ResponseEntity<ApiResponse<TargetResponse>> target(
            @AuthenticationPrincipal AuthenticatedUser user
    ) {
        Target target = targets.find(CurrentUser.idOf(user));
        return ResponseEntity.ok(ApiResponse.success(
                target == null ? null : TargetResponse.of(target)));
    }

    /** 전량 교체. 저장 후 C 계산을 한 번 시도하지만, 실패해도 저장은 유지한다. */
    @PutMapping("/target")
    public ResponseEntity<ApiResponse<TargetResponse>> saveTarget(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestBody TargetRequest request
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                TargetResponse.of(targets.save(CurrentUser.idOf(user), request))));
    }

    /**
     * 공고 매칭 목록.
     *
     * @param includeConditional 기본은 {@code false}다. 조건부 공고는 자격 자체가 확정되지
     *                           않아 부합 여부를 말할 수 없고, 목록에 섞으면 충족 건수가
     *                           실제보다 커 보인다. 제외된 건수는 응답에 함께 준다.
     */
    @GetMapping("/job-matches")
    public ResponseEntity<ApiResponse<JobMatchResponse>> jobMatches(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer perPage,
            @RequestParam(defaultValue = "false") boolean includeConditional
    ) {
        return ResponseEntity.ok(ApiResponse.success(matches.matches(
                CurrentUser.idOf(user), ComputePaging.page(page), ComputePaging.perPage(perPage),
                includeConditional)));
    }

    /** 공고 한 건의 요건 대조. 목록과 같은 저장 평가를 읽는다. */
    @GetMapping("/job-matches/{jobId}")
    public ResponseEntity<ApiResponse<JobMatchResponse.Detail>> jobMatch(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String jobId
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                matches.detail(CurrentUser.idOf(user), jobId)));
    }

    /** Skill Gap. 미판정을 부족으로 세지 않는다. */
    @GetMapping("/skill-gap")
    public ResponseEntity<ApiResponse<SkillGapResponse>> skillGap(
            @AuthenticationPrincipal AuthenticatedUser user
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                skillGaps.skillGap(CurrentUser.idOf(user))));
    }

    /** 다음 학습 기술 후보. 점수가 아니라 근거 문장을 준다. */
    @GetMapping("/recommendations")
    public ResponseEntity<ApiResponse<RecommendationResponse>> recommendations(
            @AuthenticationPrincipal AuthenticatedUser user
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                skillGaps.recommendations(CurrentUser.idOf(user))));
    }

    /**
     * 그 기술을 채웠을 때 새로 부합하는 공고.
     *
     * <p>증가 건수와 목록이 한 응답에서 나온다. 화면의 "+7건"과 아래 목록이 어긋나지 않게
     * 하려면 둘을 나눠 부르면 안 된다.</p>
     */
    @GetMapping("/recommendations/{techId}/what-if")
    public ResponseEntity<ApiResponse<WhatIfResponse>> whatIf(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String techId,
            @RequestParam(defaultValue = "ALL") ImpactKind kind,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer perPage
    ) {
        return ResponseEntity.ok(ApiResponse.success(whatIfs.whatIf(
                CurrentUser.idOf(user), techId, kind.name(), ComputePaging.page(page),
                ComputePaging.perPage(perPage))));
    }

    private enum ImpactKind { ALL, REQUIRED, PREFERRED }
}
