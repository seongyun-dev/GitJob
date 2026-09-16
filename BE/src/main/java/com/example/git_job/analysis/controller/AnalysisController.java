package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.AnalysisAcceptedResponse;
import com.example.git_job.analysis.controller.dto.AnalysisCreateRequest;
import com.example.git_job.analysis.controller.dto.AnalysisStatusResponse;
import com.example.git_job.analysis.service.AnalysisStatusService;
import com.example.git_job.analysis.service.AnalysisSubmissionService;
import com.example.git_job.global.logging.TraceIdFilter;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.security.CurrentUser;
import lombok.RequiredArgsConstructor;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
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
 * 분석 요청 (B-FN-002).
 *
 * <p>등록만 하고 결과를 기다리지 않는다. 응답 시점에 Kafka 발행은 아직 일어나지
 * 않았고, 커밋된 Outbox 행을 Debezium이 옮긴다. 그래서 Kafka가 잠깐 죽어 있어도
 * 요청은 성공한다.</p>
 */
@RestController
@RequestMapping("/api/v1/analyses")
@RequiredArgsConstructor
public class AnalysisController {

    private final AnalysisSubmissionService analysisSubmissionService;
    private final AnalysisStatusService analysisStatusService;

    @GetMapping("/{analysisId}")
    public ApiResponse<AnalysisStatusResponse> getStatus(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String analysisId,
            @RequestParam(defaultValue = "true") boolean includeRepositories) {
        return ApiResponse.success("분석 진행 상태를 조회했습니다.",
                analysisStatusService.get(CurrentUser.idOf(user), analysisId, includeRepositories));
    }

    /**
     * 새로 등록하면 202, 같은 저장소 분석이 이미 진행 중이어서 그 Job을 그대로
     * 안내하면 200이다. 본문 형태는 같으므로 화면은 statusUrl만 쓰면 된다.
     */
    @PostMapping
    public ResponseEntity<ApiResponse<AnalysisAcceptedResponse>> requestAnalysis(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestBody AnalysisCreateRequest request
    ) {
        var submission = analysisSubmissionService.submit(
                CurrentUser.idOf(user),
                request.repositoryFullName(),
                request.branchName(),
                MDC.get(TraceIdFilter.TRACE_ID));

        var body = ApiResponse.success(
                submission.created() ? "분석을 등록했습니다." : "이미 진행 중인 분석이 있습니다.",
                AnalysisAcceptedResponse.from(submission));
        return ResponseEntity
                .status(submission.created() ? HttpStatus.ACCEPTED : HttpStatus.OK)
                .body(body);
    }
}
