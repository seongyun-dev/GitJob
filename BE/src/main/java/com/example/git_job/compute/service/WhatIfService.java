package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CRelatedJobs;
import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.WhatIfResponse;
import com.example.git_job.compute.service.ComputeResultReader.Computed;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * 추천 기술 학습 시 확인된 조건에 영향을 받는 공고 (S15P21E102-279).
 *
 * <p>C를 한 번만 부른다. 활성 공고의 영향 건수와 목록은 같은 응답에서 나온다.</p>
 *
 * <p>현행 추천은 {@code IMPACT} 모드를 사용한다. 전체 채용 조건 충족을 뜻하지 않는다.</p>
 */
@Service
public class WhatIfService {

    private static final String IMPACT = "IMPACT";

    private final CComputeApi compute;
    private final ComputeResultReader reader;
    private final ComputeRetryScheduler scheduler;

    public WhatIfService(CComputeApi compute, ComputeResultReader reader) {
        this(compute, reader, null);
    }

    @Autowired
    public WhatIfService(CComputeApi compute, ComputeResultReader reader,
                         ComputeRetryScheduler scheduler) {
        this.compute = compute;
        this.reader = reader;
        this.scheduler = scheduler;
    }

    public WhatIfResponse whatIf(long userId, String techId, int page, int perPage) {
        return whatIf(userId, techId, "ALL", page, perPage);
    }

    public WhatIfResponse whatIf(long userId, String techId, String impactKind,
                                 int page, int perPage) {
        Computed<CRelatedJobs> computed = reader.readCurrentContract(userId, snapshot ->
                compute.relatedJobs(snapshot.recommendationSnapshotId(), userId, IMPACT, techId,
                        impactKind,
                        ComputePaging.toComputePage(page), perPage));

        if (!computed.hasValue()) {
            return WhatIfResponse.pending(computed.state(), Basis.of(computed.target()), techId,
                    impactKind,
                    page, perPage);
        }
        CRelatedJobs value = computed.value();
        ComputeState state = ComputeState.ready();
        if ("STALE".equals(value.resultStatus())) {
            if (scheduler != null) {
                scheduler.requestInitialSync(userId);
            }
            state = ComputeState.partial("STALE_RESULT_RECOMPUTING");
        }
        return WhatIfResponse.of(state, Basis.of(computed.target()), value, page, perPage);
    }
}
