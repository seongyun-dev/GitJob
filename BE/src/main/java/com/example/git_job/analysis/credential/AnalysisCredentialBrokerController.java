package com.example.git_job.analysis.credential;

import com.example.git_job.global.response.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/v1/repository-analysis")
@RequiredArgsConstructor
public class AnalysisCredentialBrokerController {

    private final AnalysisCredentialBrokerService service;

    @PostMapping("/credentials")
    public ResponseEntity<ApiResponse<AnalysisCredentialResponse>> exchange(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false)
            String authorization,
            @RequestBody AnalysisCredentialRequest request
    ) {
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(ApiResponse.success(
                        "저장소 분석 자격증명을 발급했습니다.",
                        service.exchange(authorization, request)
                ));
    }
}
