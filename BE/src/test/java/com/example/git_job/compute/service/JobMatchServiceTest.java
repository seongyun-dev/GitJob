package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CMatching;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.JobMatchResponse;
import com.example.git_job.compute.query.UserEvidenceStore;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * C의 부합 판정을 화면 어휘로 옮기는 규칙을 고정한다 (S15P21E102-279).
 *
 * <p>여기서 지키는 인수 조건 둘. "unknown이나 미확정 요구를 기술 미보유로 표시하지 않을
 * 것"과 "공고 매칭 건수와 목록이 일치할 것"이다. 앞은 절 판정의 번역이고, 뒤는 숫자를
 * 목록에서 세지 않는다는 뜻이다.</p>
 */
class JobMatchServiceTest {

    private static final long USER_ID = 7L;
    private static final String RECOMMENDATION = "c-3";

    private CComputeApi compute;
    private JobMatchService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        UserTargetStore targets = mock(UserTargetStore.class);
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        UserEvidenceStore evidence = mock(UserEvidenceStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.of(
                new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2", RECOMMENDATION,
                        "ev-1", "BACKEND|서울|신입", Instant.EPOCH)));
        service = new JobMatchService(compute,
                reader(targets, snapshots));

        when(compute.recommendation(anyString(), anyLong())).thenReturn(recommendation("READY", 12));
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(matching(clause("SATISFIED", false)));
    }

    private static CSnapshot recommendation(String status, int currentCount) {
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-1", "READY", 87,
                Map.of("target_role", "BACKEND_ENGINEER", "as_of", "2026-09-15T01:30:00Z"),
                List.of());
        return new CSnapshot(RECOMMENDATION, "RECOMMENDATION",
                new CSnapshot.Recommendation("7", "u7-x", "cohort-1", status, currentCount,
                        List.of(), demand, null, Map.of(), Map.of(), List.of(), null));
    }

    private static CMatching.Clause clause(String status, boolean ceilingApplied) {
        return new CMatching.Clause(
                new CMatching.Requirement("ANY_OF", List.of("kafka"), "L2"),
                status, List.of(), List.of("kafka"), List.of(), null, ceilingApplied);
    }

    private static CMatching matching(CMatching.Clause clause) {
        return matching(clause, List.of("JOB_LEVEL_REQUIREMENT_UNRESOLVED"));
    }

    private static CMatching matching(CMatching.Clause clause, List<String> dataGaps) {
        CMatching.Condition required = new CMatching.Condition(List.of(clause), List.of(),
                3, 1, 0, 0.75);
        CMatching.Job job = new CMatching.Job("job-1", "saramin", "https://example.test/1",
                "회사", "백엔드 개발자", "서울", "신입", "2026-09-26T14:59:59Z",
                "2026-09-15T00:00:00Z", "ELIGIBLE", List.of());
        CMatching.Item item = new CMatching.Item(job, required,
                new CMatching.Condition(List.of(), List.of(), 0, 0, 0, null), "PARTIAL");
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-1", "READY", 87,
                Map.of("target_role", "BACKEND_ENGINEER", "as_of", "2026-09-15T01:30:00Z"),
                List.of());
        return new CMatching(RECOMMENDATION, "calc-1", "cohort-1", 87, 5, 5, 12, demand,
                0, 20, true,
                List.of(item), dataGaps);
    }

    @Test
    @DisplayName("충족 건수는 C가 준 값이고 목록에서 세지 않는다")
    void doesNotRecountMatches() {
        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        // 목록에는 공고 한 건뿐이지만 총계는 87, 전체 충족은 12다. 목록에서 세면 둘 다 1이 된다.
        assertThat(response.summary().totalCount()).isEqualTo(87);
        assertThat(response.summary().fullMatchCount()).isEqualTo(12);
        assertThat(response.items()).hasSize(1);
        verify(compute, never()).recommendation(anyString(), anyLong());
    }

    @Test
    @DisplayName("구 C 응답에는 Recommendation Snapshot으로만 보완한다")
    void fallsBackForLegacyMatchingResponse() {
        CMatching current = matching(clause("SATISFIED", false));
        CMatching legacy = new CMatching(current.snapshotId(), current.calculationSnapshotId(),
                current.cohortId(), current.totalCount(), current.conditionalCount(),
                current.excludedConditionalCount(), null, null, current.page(), current.size(),
                current.hasNext(), current.items(), current.dataGaps());
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(legacy);

        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        assertThat(response.summary().fullMatchCount()).isEqualTo(12);
        assertThat(response.basis().jobCount()).isEqualTo(87);
        verify(compute).recommendation(RECOMMENDATION, USER_ID);
    }

    @Test
    @DisplayName("C가 주지 않는 KPI는 0이 아니라 null이다")
    void leavesUnknownKpiNull() {
        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        // 0으로 채우면 화면이 "75~99% 충족 공고가 0건"이라고 말한다. 센 적이 없다.
        assertThat(response.summary().nearMatchCount()).isNull();
        assertThat(response.summary().lowMatchCount()).isNull();
        // 제외된 조건부 건수는 알려 준다. 목록에서 사라진 공고가 몇 건인지 말할 수 있어야 한다.
        assertThat(response.summary().excludedConditionalCount()).isEqualTo(5);
    }

    @Test
    @DisplayName("UNKNOWN을 미보유로 접지 않는다")
    void keepsUnknownDistinctFromMissing() {
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(matching(clause("UNKNOWN", false)));

        assertThat(firstClause().mark()).isEqualTo("UNKNOWN");
    }

    @Test
    @DisplayName("요구 Level에 못 미친 것과 아예 없는 것을 구분한다")
    void separatesLevelShortFromMissing() {
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(matching(clause("UNSATISFIED", true)));
        assertThat(firstClause().mark()).isEqualTo("WEAK");

        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(matching(clause("UNSATISFIED", false)));
        assertThat(firstClause().mark()).isEqualTo("NONE");
    }

    @Test
    @DisplayName("요구 기술과 요구 Level을 그대로 전달한다")
    void carriesRequirement() {
        JobMatchResponse.Clause clause = firstClause();

        assertThat(clause.techIds()).containsExactly("kafka");
        assertThat(clause.requiredLevel()).isEqualTo("L2");
        assertThat(clause.missingTechIds()).containsExactly("kafka");
    }

    @Test
    @DisplayName("1-base 페이지를 C의 0-base로 바꿔 보낸다")
    void convertsPaging() {
        service.matches(USER_ID, 3, 20, false);

        verify(compute).matching(RECOMMENDATION, USER_ID, 2, 20, false);
    }

    @Test
    @DisplayName("부분 분석은 값을 숨기지 않고 상태로 알린다")
    void reportsPartialAnalysis() {
        when(compute.recommendation(anyString(), anyLong())).thenReturn(recommendation("PARTIAL", 9));

        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.PARTIAL);
        assertThat(response.statusReason()).isEqualTo("PARTIAL_ANALYSIS");
        // 부분이라고 목록을 비우지 않는다. 있는 근거로 나온 결과는 보여 준다.
        assertThat(response.items()).isNotEmpty();
    }

    @Test
    @DisplayName("추천 근거가 부족해도 저장된 공고 매칭 결과는 숨기지 않는다")
    void matchingStateDoesNotDependOnRecommendationState() {
        when(compute.recommendation(anyString(), anyLong()))
                .thenReturn(recommendation("INSUFFICIENT_EVIDENCE", 0));
        when(compute.matching(anyString(), anyLong(), anyInt(), anyInt(), anyBoolean()))
                .thenReturn(matching(clause("UNKNOWN", false), List.of()));

        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.READY);
        assertThat(response.items()).isNotEmpty();
    }

    @Test
    @DisplayName("비교 기준은 C가 정규화한 조건과 실제 분모를 쓴다")
    void exposesBasis() {
        JobMatchResponse response = service.matches(USER_ID, 1, 20, false);

        assertThat(response.basis().targetRole()).isEqualTo("BACKEND_ENGINEER");
        assertThat(response.basis().asOf()).isEqualTo("2026-09-15T01:30:00Z");
        assertThat(response.basis().jobCount()).isEqualTo(87);
    }

    private JobMatchResponse.Clause firstClause() {
        return service.matches(USER_ID, 1, 20, false)
                .items().getFirst().required().clauses().getFirst();
    }
}
