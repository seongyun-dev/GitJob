package com.example.git_job.compute.controller;

import com.example.git_job.compute.service.AdminComputeAttemptService;
import com.example.git_job.compute.service.AdminComputeAttemptService.RearmCheck;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import java.util.UUID;
import org.springframework.dao.ConcurrencyFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** /api/v1/admin/** security matcher가 보호하는 compute 복구 API. */
@RestController
@RequestMapping("/api/v1/admin/compute-attempts")
public class AdminComputeAttemptController {

    private final AdminComputeAttemptService service;

    public AdminComputeAttemptController(AdminComputeAttemptService service) {
        this.service = service;
    }

    @PostMapping("/rearm/dry-run")
    public ResponseEntity<ApiResponse<RearmCheck>> dryRun(
            @RequestBody RearmRequest request) {
        return ResponseEntity.ok(ApiResponse.success(service.dryRun(request.userId(),
                request.targetKey(), request.evidenceVersion(), request.expectedRunToken())));
    }

    @PostMapping("/rearm")
    public ResponseEntity<ApiResponse<ComputeAttempt>> rearm(
            @RequestBody RearmRequest request,
            @AuthenticationPrincipal AuthenticatedUser actor) {
        try {
            ComputeAttempt attempt = service.rearm(request.userId(), request.targetKey(),
                    request.evidenceVersion(), request.expectedRunToken(),
                    Long.parseLong(actor.userId()), request.reason());
            return ResponseEntity.ok(ApiResponse.success(attempt));
        } catch (ConcurrencyFailureException conflict) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "FAILED attempt changed during rearm", conflict);
        }
    }

    public record RearmRequest(
            long userId,
            String targetKey,
            String evidenceVersion,
            UUID expectedRunToken,
            String reason) {
    }
}
