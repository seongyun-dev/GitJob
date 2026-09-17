package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.TechnologyEvidenceResponse;
import com.example.git_job.analysis.controller.dto.TechnologyProfileResponse;
import com.example.git_job.analysis.controller.dto.TechnologySummaryView;
import com.example.git_job.analysis.service.TechnologySummaryService;
import com.example.git_job.analysis.service.TechnologyProfileService;
import com.example.git_job.analysis.service.TechnologyProfileService.Profile;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.security.CurrentUser;
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
    private final TechnologySummaryService summaries;

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
                profile.summary(), profile.technologies(), profile.repositories(),
                profile.personalLevels())));
    }

    /**
     * 카드에 얹을 한 문단. 캐시에 있으면 즉시, 없으면 만들어서.
     *
     * <h2>왜 목록이 아니라 여기인가</h2>
     *
     * <p>생성에 4초쯤 걸린다. 기술 열두 개를 {@code GET /me/technologies} 에 실으면
     * 목록이 48초를 기다리게 되고, 그동안 화면에 아무것도 못 그린다. 카드마다 따로
     * 부르면 목록은 즉시 뜨고 문단은 도착하는 대로 채워진다.</p>
     *
     * <p>못 만들어도 200 이다. {@code summary} 가 {@code null} 로 나가고 화면은
     * 그 자리를 비운다 -- 요약 서비스는 노트북 GPU 위에 있어 꺼져 있는 것이
     * 정상적으로 자주 일어난다.</p>
     *
     * <p>비어 있을 때는 {@code status} 를 본다. {@code PENDING} 이면 GPU 자리가
     * 없었다는 뜻이고 {@code retryAfterSeconds} 뒤에 다시 부르면 채워진다. 카드
     * 열두 장이 한꺼번에 들어오면 자리가 둘뿐이라 대부분이 여기에 해당하므로,
     * 화면이 재시도하지 않으면 그 자리는 계속 비어 보인다.</p>
     */
    @GetMapping("/{techId}/summary")
    public ResponseEntity<ApiResponse<TechnologySummaryView>> summary(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String techId
    ) {
        return ResponseEntity.ok(ApiResponse.success(TechnologySummaryView.of(techId,
                summaries.summaryOf(CurrentUser.idOf(user), techId))));
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
