package com.example.git_job.analysis.service;

import com.example.git_job.analysis.controller.dto.AnalysisStatusResponse;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class AnalysisStatusService {
    private final AnalysisJobRepository jobs;

    @Transactional(readOnly = true)
    public AnalysisStatusResponse get(long userId, String analysisId, boolean includeRepositories) {
        var job = jobs.findById(analysisId)
                .orElseThrow(() -> new CustomException(ErrorCode.ANALYSIS_NOT_FOUND));
        if (!Long.valueOf(userId).equals(job.getUserId())) {
            throw new CustomException(ErrorCode.ANALYSIS_ACCESS_DENIED);
        }
        return AnalysisStatusResponse.from(job, includeRepositories);
    }
}
