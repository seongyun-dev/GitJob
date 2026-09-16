package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.CandidatePromoteRequest;
import com.example.git_job.analysis.controller.dto.CandidateRejectRequest;
import com.example.git_job.analysis.controller.dto.PromotionResponse;
import com.example.git_job.analysis.controller.dto.TechnologyCandidateDetailResponse;
import com.example.git_job.analysis.controller.dto.TechnologyCandidateResponse;
import com.example.git_job.analysis.service.TechnologyCandidateAdminService;
import com.example.git_job.analysis.service.TechnologyCandidateAdminService.RegistryStatus;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The technology-candidate review screen's API.
 *
 * <p>Under {@code /api/v1/admin}, which {@code SecurityConfig} restricts to
 * ADMIN. The restriction is not a formality: promoting a candidate changes the
 * registry, and the registry is the basis on which every user's technology
 * profile is judged.</p>
 *
 * <p>Promotions land in a draft version, not the current one. Publishing is a
 * separate call so a week of decisions ships as one version, and so they stay
 * reversible until someone says otherwise.</p>
 *
 * <p>Refusals come out of the service as {@code CustomException}, so failures
 * here carry the same envelope every other endpoint returns.</p>
 */
@RestController
@RequestMapping("/api/v1/admin/technology-candidates")
@RequiredArgsConstructor
public class AdminTechnologyCandidateController {

    private final TechnologyCandidateAdminService admin;

    /** Ranked by how many distinct users a candidate would serve. Rejected ones are hidden. */
    @GetMapping
    public ResponseEntity<ApiResponse<List<TechnologyCandidateResponse>>> list(
            @RequestParam(defaultValue = "50") int limit
    ) {
        List<TechnologyCandidateResponse> rows = admin.list(limit).stream()
                .map(TechnologyCandidateResponse::from)
                .toList();
        return ResponseEntity.ok(ApiResponse.success(rows));
    }

    /**
     * One candidate with its decision and the recent evidence behind it
     * (S15P21E102-141). 404 when the id does not exist -- the summary counts on
     * the list say how many people are affected, and this traces that number to
     * the repositories and scopes that produced it.
     */
    @GetMapping("/{candidateId}")
    public ResponseEntity<ApiResponse<TechnologyCandidateDetailResponse>> detail(
            @PathVariable long candidateId
    ) {
        return ResponseEntity.ok(ApiResponse.success(
                TechnologyCandidateDetailResponse.from(admin.detail(candidateId))));
    }

    /** Which version analyses use now, and which one promotions are accumulating in. */
    @GetMapping("/registry")
    public ResponseEntity<ApiResponse<RegistryStatus>> registry() {
        return ResponseEntity.ok(ApiResponse.success(admin.registryStatus()));
    }

    /**
     * The registry status rides along so the screen can show the pending draft
     * right after a decision without a second round trip.
     */
    @PostMapping("/{candidateId}/promote")
    public ResponseEntity<ApiResponse<PromotionResponse>> promote(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable long candidateId,
            @RequestBody(required = false) CandidatePromoteRequest request
    ) {
        CandidatePromoteRequest body =
                request == null ? new CandidatePromoteRequest(null, null, null, null) : request;
        String techId = admin.promote(candidateId, body.techId(), body.displayName(),
                body.jobDomains(), Long.parseLong(user.userId()), body.note());
        return ResponseEntity.ok(ApiResponse.success(
                new PromotionResponse(techId, admin.registryStatus())));
    }

    @PostMapping("/{candidateId}/reject")
    public ResponseEntity<ApiResponse<RegistryStatus>> reject(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable long candidateId,
            @RequestBody(required = false) CandidateRejectRequest request
    ) {
        admin.reject(candidateId, Long.parseLong(user.userId()),
                request == null ? null : request.note());
        return ResponseEntity.ok(ApiResponse.success(admin.registryStatus()));
    }

    /**
     * Makes the draft current. Analyses requested after this are judged with it;
     * ones already judged keep pointing at the version that judged them.
     */
    @PostMapping("/registry/publish")
    public ResponseEntity<ApiResponse<RegistryStatus>> publish() {
        admin.publishDraft();
        return ResponseEntity.ok(ApiResponse.success(admin.registryStatus()));
    }
}
