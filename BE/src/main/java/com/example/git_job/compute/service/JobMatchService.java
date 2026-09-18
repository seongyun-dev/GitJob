package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CMatching;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.controller.dto.Basis;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.JobMatchResponse;
import com.example.git_job.compute.service.ComputeResultReader.Computed;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import org.springframework.stereotype.Service;

/**
 * 공고 매칭 목록과 상세 (S15P21E102-279).
 *
 * <p>C를 두 번 부른다. 공고별 평가는 매칭 API에 있고, 상단 KPI의 "필수 전체 충족 수"와
 * 비교 기준(분모·as_of)은 RECOMMENDATION Snapshot에 있다. 목록에서 세어 만들 수도 있지만
 * 그건 부합 판정 재계산이고, 페이지 단위로 세면 분모까지 틀린다.</p>
 */
@Service
public class JobMatchService {

    private final CComputeApi compute;
    private final ComputeResultReader reader;

    public JobMatchService(CComputeApi compute, ComputeResultReader reader) {
        this.compute = compute;
        this.reader = reader;
    }

    public JobMatchResponse matches(long userId, int page, int perPage,
                                    boolean includeConditional) {
        Computed<Page> computed = reader.read(userId, snapshot -> new Page(
                compute.recommendation(snapshot.recommendationSnapshotId(), userId),
                compute.matching(snapshot.recommendationSnapshotId(), userId,
                        ComputePaging.toComputePage(page), perPage, includeConditional)));

        if (!computed.hasValue()) {
            return JobMatchResponse.pending(computed.state(), Basis.of(computed.target()),
                    page, perPage);
        }
        CSnapshot.Recommendation recommendation = computed.value().recommendation();
        CMatching matching = computed.value().matching();
        return JobMatchResponse.of(
                matchingState(matching),
                Basis.of(computed.target(), recommendation.demand()),
                summary(recommendation, matching),
                matching, page, perPage);
    }

    /** 매칭 결과가 존재하면 추천 후보 상태와 무관하게 그 결과를 표시한다. */
    private ComputeState matchingState(CMatching matching) {
        if (matching.dataGaps() != null && !matching.dataGaps().isEmpty()) {
            return new ComputeState(ComputeState.PARTIAL, "PARTIAL_ANALYSIS", null);
        }
        return ComputeState.ready();
    }

    public JobMatchResponse.Detail detail(long userId, String jobId) {
        Computed<CMatching.Detail> computed = reader.read(userId, snapshot ->
                compute.matchingDetail(snapshot.recommendationSnapshotId(), userId, jobId));

        if (!computed.hasValue()) {
            return JobMatchResponse.Detail.pending(computed.state(), Basis.of(computed.target()));
        }
        CMatching.Detail detail = computed.value();
        if (detail.item() == null) {
            // C는 없는 job_id에 404를 주므로 보통 여기 오지 않는다. 그래도 빈 상세를
            // 200으로 내리면 화면이 빈 서랍을 그린다.
            throw new CustomException(ErrorCode.MATCHING_RESULT_NOT_FOUND);
        }
        return JobMatchResponse.Detail.of(ComputeState.ready(),
                Basis.of(computed.target()), detail.item());
    }

    /**
     * 상단 KPI.
     *
     * <p>{@code nearMatchCount}와 {@code lowMatchCount}는 {@code null}이다. C가
     * {@code required_status}별 분포를 주지 않고, 목록을 모아 세는 것은 부합 판정을 다시
     * 구현하는 일이다. 계약 §6-1의 미결 항목이며 화면은 그 칸을 그리지 않는다.</p>
     */
    private JobMatchResponse.Summary summary(CSnapshot.Recommendation recommendation,
                                             CMatching matching) {
        return new JobMatchResponse.Summary(
                matching.totalCount(),
                recommendation.currentCount(),
                null,
                null,
                matching.conditionalCount(),
                matching.excludedConditionalCount());
    }

    /** 한 화면이 쓰는 두 결과. 같은 Snapshot에서 읽어야 숫자와 목록이 맞는다. */
    private record Page(CSnapshot recommendationSnapshot, CMatching matching) {

        CSnapshot.Recommendation recommendation() {
            return recommendationSnapshot.payload();
        }
    }
}
