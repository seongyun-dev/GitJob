package com.example.git_job.compute.client;

import com.example.git_job.compute.client.dto.CDemandSnapshot;
import com.example.git_job.compute.client.dto.CohortResolved;
import com.example.git_job.compute.client.dto.CohortSelector;
import com.example.git_job.compute.client.dto.CMatching;
import com.example.git_job.compute.client.dto.CRelatedJobs;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.client.dto.CTrend;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * C 내부 API의 조회 경로를 한곳에 모은다 (S15P21E102-279).
 *
 * <p>{@link CComputeClient}는 HTTP와 오류 번역만 안다. 어떤 경로에 어떤 파라미터가
 * 붙는지는 계약이고, 기능마다 문자열로 적으면 오타 하나가 404로 나타난다 -- 그 404는
 * "아직 준비되지 않음"과 구분되지 않아 화면이 영원히 기다린다.</p>
 *
 * <p>{@code userId}를 받는 메서드는 전부 개인 결과다. 이 값은 호출부에서 인증된 사용자로
 * 정해야 하며, 요청 파라미터를 그대로 넘기면 남의 결과를 읽는 경로가 된다.</p>
 */
@Component
public class CComputeApi {

    private static final String RECOMMENDATIONS = "/internal/v1/c/recommendations/";
    private static final String SNAPSHOTS = "/internal/v1/c/snapshots/";

    private final CComputeClient client;

    public CComputeApi(CComputeClient client) {
        this.client = client;
    }

    /**
     * 조건에 맞는 공고 모집단과 수요를 고른다.
     *
     * <p>처음 보는 조건이면 C가 멱등하게 계산·저장하고, 같은 조건이면 기존 결과를
     * 재사용한다. B가 목록을 잘라 필터를 흉내 내지 않고 매번 이 endpoint를 부르는 이유는,
     * 잘라내면 추천 수치의 분모와 공고 목록의 분모가 달라지기 때문이다.</p>
     */
    public CohortResolved resolveCohort(CohortSelector selector) {
        return client.post("/internal/v1/c/job-cohorts/resolve", selector, CohortResolved.class);
    }

    /** 개인 추천 Snapshot. 소유자가 다르면 C가 존재 여부를 드러내지 않고 404를 준다. */
    public CSnapshot recommendation(String snapshotId, long userId) {
        return client.get(SNAPSHOTS + snapshotId, Map.of("user_id", String.valueOf(userId)),
                CSnapshot.class);
    }

    /**
     * 공용 수요 Snapshot. 개인 결과가 아니므로 {@code user_id}를 붙이지 않는다.
     *
     * <p>붙이면 C가 소유자 조건으로 조회해 공용 결과를 찾지 못한다.</p>
     */
    public CDemandSnapshot demand(String snapshotId) {
        return client.get(SNAPSHOTS + snapshotId, Map.of(), CDemandSnapshot.class);
    }

    /** 공고별 부분 부합 목록. {@code page}는 0-based이고 {@code size}는 1~50이다. */
    public CMatching matching(String snapshotId, long userId, int page, int size,
                              boolean includeConditional) {
        Map<String, Object> query = new HashMap<>();
        query.put("user_id", String.valueOf(userId));
        query.put("page", page);
        query.put("size", size);
        query.put("include_conditional", includeConditional);
        return client.get(RECOMMENDATIONS + snapshotId + "/matching-job-postings", query,
                CMatching.class);
    }

    public CMatching.Detail matchingDetail(String snapshotId, long userId, String jobId) {
        return client.get(RECOMMENDATIONS + snapshotId + "/matching-job-posting",
                Map.of("user_id", String.valueOf(userId), "job_id", jobId),
                CMatching.Detail.class);
    }

    /**
     * 공고 목록. {@code WHAT_IF}는 그 기술을 채웠을 때 <b>새로 늘어나는</b> 공고만 준다.
     *
     * @param techId {@code CURRENT}에서는 {@code null}이다. 값이 있으면 보내지 않는다.
     */
    public CRelatedJobs relatedJobs(String snapshotId, long userId, String mode, String techId,
                                    int page, int size) {
        Map<String, Object> query = new HashMap<>();
        query.put("user_id", String.valueOf(userId));
        query.put("mode", mode);
        query.put("recommended_tech_id", techId);
        query.put("page", page);
        query.put("size", size);
        return client.get(RECOMMENDATIONS + snapshotId + "/job-postings", query,
                CRelatedJobs.class);
    }

    /** 공용 Trend의 완료 head 조회. 계산을 만들지 않는 순수 조회다. */
    public CTrend.Resolved resolveTrend(CTrend.Selector selector) {
        return client.post("/internal/v1/c/trends/resolve", selector, CTrend.Resolved.class);
    }

    /** 같은 출처의 기술 비교용. resolve와 Snapshot payload를 C 왕복 한 번에 받는다. */
    public CTrend.Batch resolveTrends(List<CTrend.Selector> selectors) {
        return client.post("/internal/v1/c/trends/resolve-batch",
                new CTrend.BatchRequest(selectors), CTrend.Batch.class);
    }

    public CTrend.Snapshot trendSnapshot(String snapshotId) {
        return client.get(SNAPSHOTS + snapshotId, Map.of(), CTrend.Snapshot.class);
    }
}
