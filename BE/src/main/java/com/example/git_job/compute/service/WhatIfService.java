package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CRelatedJobs;
import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.WhatIfResponse;
import com.example.git_job.compute.service.ComputeResultReader.Computed;
import org.springframework.stereotype.Service;

/**
 * 추천 기술을 채웠을 때의 신규 부합 공고 (S15P21E102-279).
 *
 * <p>C를 한 번만 부른다. 증가 건수와 목록이 같은 응답에서 나와야 한다는 것이 인수
 * 조건이고, 숫자를 추천 API에서 목록을 이 API에서 읽으면 그 사이에 새 Snapshot이 생겼을 때
 * 둘이 어긋난다.</p>
 *
 * <p>{@code WHAT_IF} 모드는 새로 늘어나는 공고만 준다. 현재 충족 공고까지 합친 목록이
 * 아니므로 이 목록의 길이는 증가 건수와 같은 것을 센다.</p>
 */
@Service
public class WhatIfService {

    private static final String WHAT_IF = "WHAT_IF";

    private final CComputeApi compute;
    private final ComputeResultReader reader;

    public WhatIfService(CComputeApi compute, ComputeResultReader reader) {
        this.compute = compute;
        this.reader = reader;
    }

    public WhatIfResponse whatIf(long userId, String techId, int page, int perPage) {
        Computed<CRelatedJobs> computed = reader.read(userId, snapshot ->
                compute.relatedJobs(snapshot.recommendationSnapshotId(), userId, WHAT_IF, techId,
                        ComputePaging.toComputePage(page), perPage));

        if (!computed.hasValue()) {
            return WhatIfResponse.pending(computed.state(), Basis.of(computed.target()), techId,
                    page, perPage);
        }
        return WhatIfResponse.of(ComputeState.ready(), Basis.of(computed.target()),
                computed.value(), page, perPage);
    }
}
