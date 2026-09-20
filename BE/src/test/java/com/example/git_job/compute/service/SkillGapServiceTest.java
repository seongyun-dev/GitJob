package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.controller.dto.RecommendationResponse;
import com.example.git_job.compute.controller.dto.SkillGapResponse;
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
 * Skill Gap과 추천의 번역 규칙을 고정한다 (S15P21E102-279).
 *
 * <p>가장 중요한 것은 {@code UNKNOWN}을 부족으로 세지 않는 것이다. C에서 {@code UNKNOWN}은
 * "그 기술을 평가하지 않았다"는 뜻이고, 부족에 넣으면 화면이 사용자에게 없는 결핍을
 * 만들어 보여 준다.</p>
 */
class SkillGapServiceTest {

    private static final long USER_ID = 7L;
    private static final String RECOMMENDATION = "c-3";

    private CComputeApi compute;
    private SkillGapService service;
    private ComputeResultReader resultReader;

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
        resultReader = reader(targets, snapshots);
        service = new SkillGapService(compute, resultReader);
        when(compute.recommendation(anyString(), anyLong())).thenReturn(snapshot("READY"));
    }

    private static CSnapshot snapshot(String status) {
        CSnapshot.Gap gap = new CSnapshot.Gap("technology-gap/v2", List.of("spring"), List.of(
                new CSnapshot.GapTechnology("spring", "HELD", List.of(), List.of()),
                new CSnapshot.GapTechnology("kafka", "NOT_HELD",
                        List.of("TECHNOLOGY_NOT_EVALUATED"), List.of()),
                new CSnapshot.GapTechnology("redis", "NOT_HELD",
                        List.of("REQUIRED_LEVEL_NOT_MET"), List.of()),
                new CSnapshot.GapTechnology("docker", "UNKNOWN",
                        List.of("TECHNOLOGY_NOT_EVALUATED"), List.of())),
                List.of());
        CSnapshot.Demand demand = new CSnapshot.Demand("cohort-1", "READY", 87,
                Map.of("target_role", "BACKEND_ENGINEER"), List.of(
                        technologyDemand("kafka", 21), technologyDemand("redis", 8)));
        CSnapshot.WhatIf whatIf = new CSnapshot.WhatIf("kafka", 87, 12, 19, 7,
                List.of("job-1"), List.of());
        CSnapshot.Candidate candidate = new CSnapshot.Candidate("kafka", 1, "NOT_HELD",
                technologyDemand("kafka", 21), whatIf, List.of("java"), List.of(),
                List.of("docker"), List.of("DEMAND_TOP_QUARTILE"), List.of());
        CSnapshot.Explanation explanation = new CSnapshot.Explanation("RULE", List.of(
                new CSnapshot.Fact("f1", "DEMAND", "kafka", "공고 87건 중 21건이 Kafka를 요구합니다."),
                new CSnapshot.Fact("f2", "QUALITY", null, "전체 계산에 대한 설명")));
        return new CSnapshot(RECOMMENDATION, "RECOMMENDATION",
                new CSnapshot.Recommendation("7", "u7-x", "cohort-1", status, 12,
                        List.of(candidate), demand, gap, Map.of("spring", "L2"),
                        Map.of("spring", "L3", "redis", "L1"), List.of(), explanation));
    }

    private static CSnapshot.TechnologyDemand technologyDemand(String techId, int required) {
        return new CSnapshot.TechnologyDemand(techId, 1, required, 4, 0, required + 4,
                0.24, 0.05, 0, 0.29);
    }

    @Test
    @DisplayName("미판정은 부족으로 세지 않는다")
    void doesNotCountUnknownAsGap() {
        SkillGapResponse.Summary summary = service.skillGap(USER_ID).summary();

        assertThat(summary.requiredTechCount()).isEqualTo(4);
        assertThat(summary.metCount()).isEqualTo(1);
        // Evidence 없음 1 + Level 부족 1. docker 의 UNKNOWN 은 여기 들어가지 않는다.
        assertThat(summary.gapCount()).isEqualTo(2);
        assertThat(summary.undeterminedCount()).isEqualTo(1);
    }

    @Test
    @DisplayName("stale 추천·Gap은 제공하면서 비동기 재계산을 요청한다")
    void staleResultRequestsAsyncRecompute() {
        CSnapshot current = snapshot("READY");
        when(compute.recommendation(anyString(), anyLong())).thenReturn(
                new CSnapshot(current.snapshotId(), current.kind(), "STALE", true,
                        current.payload()));
        ComputeRetryScheduler scheduler = mock(ComputeRetryScheduler.class);
        SkillGapService staleService = new SkillGapService(compute, resultReader, scheduler);

        RecommendationResponse response = staleService.recommendations(USER_ID);

        assertThat(response.dataStatus()).isEqualTo("PARTIAL");
        assertThat(response.statusReason()).isEqualTo("STALE_RESULT_RECOMPUTING");
        verify(scheduler).requestInitialSync(USER_ID);
    }

    @Test
    @DisplayName("Evidence 없음과 Level 부족을 구분한다")
    void separatesNoEvidenceFromLevelShort() {
        Map<String, String> verdicts = verdicts();

        assertThat(verdicts.get("spring")).isEqualTo("MET");
        assertThat(verdicts.get("kafka")).isEqualTo("NO_EVIDENCE");
        // 사용자가 할 일이 다르다 -- 새로 배우는 것과 더 깊이 쓰는 것.
        assertThat(verdicts.get("redis")).isEqualTo("LEVEL_SHORT");
        assertThat(verdicts.get("docker")).isEqualTo("UNDETERMINED");
    }

    @Test
    @DisplayName("판정 상한을 함께 내려 화면이 미확인 구간을 말할 수 있게 한다")
    void carriesAssessmentCeiling() {
        SkillGapResponse.Row redis = row("redis");

        assertThat(redis.personalLevel()).isNull();
        // Level 이 없다고 "안 써 봤다"가 아니다. 상한까지는 판정했다는 뜻이다.
        assertThat(redis.assessmentCeiling()).isEqualTo("L1");
        assertThat(redis.requiredCount()).isEqualTo(8);
    }

    @Test
    @DisplayName("fillDelta는 What-if를 계산한 후보에만 있다")
    void fillDeltaOnlyForCandidates() {
        assertThat(row("kafka").fillDelta()).isEqualTo(7);
        // C 는 상위 3개 후보에만 What-if 를 계산한다. 나머지에 숫자를 만들어 넣지 않는다.
        assertThat(row("redis").fillDelta()).isNull();
    }

    @Test
    @DisplayName("추천 근거는 점수가 아니라 문장이고 기술별로 붙는다")
    void recommendationCarriesSentences() {
        RecommendationResponse.Candidate candidate =
                service.recommendations(USER_ID).candidates().getFirst();

        assertThat(candidate.techId()).isEqualTo("kafka");
        assertThat(candidate.rank()).isEqualTo(1);
        assertThat(candidate.reasons()).containsExactly("공고 87건 중 21건이 Kafka를 요구합니다.");
        assertThat(candidate.whatIf().increasedCount()).isEqualTo(7);
        // 판정하지 못한 선행 기술과 빠진 선행 기술을 섞지 않는다.
        assertThat(candidate.missingPrerequisiteTechIds()).isEmpty();
        assertThat(candidate.unknownPrerequisiteTechIds()).containsExactly("docker");
    }

    @Test
    @DisplayName("Skill Gap과 추천이 같은 Snapshot을 읽는다")
    void bothReadTheSameSnapshot() {
        int whatIfFromGap = row("kafka").fillDelta();
        int whatIfFromRecommendation = service.recommendations(USER_ID)
                .candidates().getFirst().whatIf().increasedCount();

        // 두 화면의 숫자가 어긋나면 서로 다른 계산을 읽은 것이다.
        assertThat(whatIfFromGap).isEqualTo(whatIfFromRecommendation);
    }

    @Test
    @DisplayName("추천을 만들 근거가 부족해도 기술별 보유와 미판정 결과는 보여 준다")
    void keepsGapRowsVisibleWhenRecommendationEvidenceIsInsufficient() {
        when(compute.recommendation(anyString(), anyLong()))
                .thenReturn(snapshot("INSUFFICIENT_EVIDENCE"));

        SkillGapResponse response = service.skillGap(USER_ID);

        assertThat(response.dataStatus()).isEqualTo("PARTIAL");
        assertThat(response.statusReason()).isEqualTo("PARTIAL_SKILL_GAP_EVIDENCE");
        assertThat(response.rows()).hasSize(4);
        assertThat(response.summary().undeterminedCount()).isEqualTo(1);
        assertThat(service.recommendations(USER_ID).dataStatus())
                .isEqualTo("INSUFFICIENT_DATA");
    }

    private Map<String, String> verdicts() {
        return service.skillGap(USER_ID).rows().stream()
                .collect(java.util.stream.Collectors.toMap(SkillGapResponse.Row::techId,
                        SkillGapResponse.Row::verdict));
    }

    private SkillGapResponse.Row row(String techId) {
        return service.skillGap(USER_ID).rows().stream()
                .filter(row -> techId.equals(row.techId()))
                .findFirst()
                .orElseThrow();
    }
}
