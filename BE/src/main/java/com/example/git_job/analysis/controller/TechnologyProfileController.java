package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.TechnologyEvidenceResponse;
import com.example.git_job.analysis.controller.dto.TechnologyProfileResponse;
import com.example.git_job.analysis.service.TechnologyProfileService;
import com.example.git_job.analysis.service.TechnologyProfileService.Profile;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 내 분석 결과 조회.
 *
 * <p>{@code /me} 아래라 대상은 언제나 인증된 본인이다. 사용자 id 를 경로나 파라미터로
 * 받지 않는 것은, 받는 순간 남의 것을 요구할 수 있게 되고 그 검사를 매번 해야 하기
 * 때문이다.</p>
 */
@RestController
@RequestMapping("/api/v1/me/technologies")
@RequiredArgsConstructor
public class TechnologyProfileController {

    private final TechnologyProfileService profiles;

    /**
     * 기술별 판정 한 장. 지표·기술 목록·판정에 쓰인 저장소를 함께 준다.
     *
     * <p>분석한 적이 없어도 200 이다. 빈 결과는 오류가 아니며, {@code dataStatus} 가
     * {@code NO_DATA} 로 그 사실을 말한다.</p>
     */
    @GetMapping
    public ResponseEntity<ApiResponse<TechnologyProfileResponse>> technologies(
            @AuthenticationPrincipal AuthenticatedUser user
    ) {
        Profile profile = profiles.profile(CurrentUser.idOf(user));
        return ResponseEntity.ok(ApiResponse.success(TechnologyProfileResponse.of(
                profile.summary(), profile.technologies(), profile.repositories())));
    }

    /** 한 기술을 무엇으로 판정했는지. 레지스트리에 없는 기술이면 404 다. */
    @GetMapping("/{techId}/evidence")
    public ResponseEntity<ApiResponse<TechnologyEvidenceResponse>> evidence(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String techId
    ) {
        return ResponseEntity.ok(ApiResponse.success(TechnologyEvidenceResponse.of(
                techId, profiles.evidence(CurrentUser.idOf(user), techId),
                TechnologyProfileService.EVIDENCE_PER_LEVEL)));
    }
}
