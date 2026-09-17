package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.compute.client.dto.EvidencePayload;
import com.example.git_job.compute.query.UserEvidenceStore;
import com.example.git_job.compute.query.UserEvidenceStore.EvidenceRow;
import com.example.git_job.compute.query.UserEvidenceStore.RepositoryAnalysis;
import com.example.git_job.compute.query.UserEvidenceStore.TechnologySupport;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 저장소별 근거를 C 계약으로 옮기는 규칙을 고정한다 (S15P21E102-279).
 *
 * <p>DB 없이 돈다. 여기서 검증할 것은 SQL이 아니라 <b>변환</b>이고, 그 변환이 틀리면
 * C가 묶음 전체를 422로 거절하거나 -- 더 나쁘게는 -- 조용히 아무 기술도 보유로 인정하지
 * 않는다. 후자는 화면에 "Skill Gap 전부 미판정"으로만 보여서 원인을 찾기 어렵다.</p>
 */
class UserEvidenceAssemblerTest {

    private static final long USER_ID = 7L;
    private static final String SHA = "a".repeat(40);
    private static final String BLAME = "b".repeat(40);
    private static final String REGISTRY = "registry-20260911.4";
    private static final String RULE_PACK = "rule-pack-20260911.4";
    private static final String PACK_SHA = "c".repeat(64);

    private UserEvidenceStore evidence;
    private TechnologyProfileStore profiles;
    private UserEvidenceAssembler assembler;

    @BeforeEach
    void setUp() {
        evidence = mock(UserEvidenceStore.class);
        profiles = mock(TechnologyProfileStore.class);
        assembler = new UserEvidenceAssembler(evidence, profiles);
        when(evidence.failedRepositoryIds(anyLong())).thenReturn(List.of());
        when(profiles.personalLevels(anyLong())).thenReturn(List.of());
        // 판정 범위는 이제 Registry 전체가 아니라 그 분석의 Rule Pack 이 실제로 본
        // 기술이다. 상한도 관측치가 아니라 여기서 온다.
        when(evidence.technologySupport(anyLong())).thenReturn(List.of(
                new TechnologySupport("an_1", "spring", "L3", "SUPPORTED"),
                new TechnologySupport("an_1", "kafka", "L1", "PARTIAL")));
    }

    private void given(List<RepositoryAnalysis> analyses, List<EvidenceRow> rows) {
        when(evidence.latestAnalyses(USER_ID)).thenReturn(analyses);
        when(evidence.evidence(USER_ID)).thenReturn(rows);
    }

    private static RepositoryAnalysis analysis() {
        return analysis(RULE_PACK, true, false);
    }

    /**
     * @param reportedSkips   건너뛴 사유를 보고받았는지. v1 결과는 받지 못한다.
     * @param skippedAnything 실제로 건너뛴 파일이 있었는지.
     */
    private static RepositoryAnalysis analysis(String rulePack, boolean reportedSkips,
                                               boolean skippedAnything) {
        return new RepositoryAnalysis("an_1", "101", "octocat/api", SHA, Instant.EPOCH,
                REGISTRY, rulePack, PACK_SHA, reportedSkips, skippedAnything);
    }

    private static EvidenceRow row(long id, String factType, String ruleType,
                                   String contribution) {
        return new EvidenceRow("an_1", "101", SHA, id, REGISTRY, "rule-" + factType, ruleType,
                "spring", factType, "src/main/java/App.java", 10, 12,
                contribution == null ? null : BLAME, contribution);
    }

    @Test
    @DisplayName("성공한 분석이 없으면 분석 전이라고 말한다")
    void reportsNoAnalysis() {
        given(List.of(), List.of());

        assertThat(assembler.assemble(USER_ID).unavailable())
                .isEqualTo(UserEvidenceAssembler.Unavailable.NO_ANALYSIS);
    }

    @Test
    @DisplayName("근거가 0건이어도 보낸다 — 등록 기술이 관측되지 않은 것과 분석하지 않은 것은 다르다")
    void sendsAnalysesWithoutEvidence() {
        given(List.of(analysis()), List.of());

        EvidencePayload payload = assembler.assemble(USER_ID).payload();

        // 예전에는 Registry 버전을 근거 행에서만 읽어 여기서 통째로 포기했고, 그래서
        // 이런 사용자는 Skill Gap 도 추천도 받지 못했다.
        assertThat(payload).isNotNull();
        assertThat(payload.repositories()).hasSize(1);
        assertThat(payload.repositories().getFirst().technologies()).isEmpty();
        // 무엇을 평가할 수 있었는지는 남는다. C 는 이 범위로 미보유를 판정한다.
        assertThat(payload.repositories().getFirst().evaluatedTechIds())
                .containsExactly("kafka", "spring");
    }

    @Test
    @DisplayName("Rule Pack 계보가 없으면 재분석 필요로 말한다")
    void reportsMissingRulePackLineage() {
        // v1 계약으로만 받은 결과다. Registry 버전으로 대신 채우면 C 가 근거를 전부
        // 버리므로, 기다릴 상태가 아니라 재분석할 상태다.
        given(List.of(analysis(null, false, false)), List.of(row(1L, "DEPENDENCY", "L1", null)));

        assertThat(assembler.assemble(USER_ID).unavailable())
                .isEqualTo(UserEvidenceAssembler.Unavailable.NO_RULE_PACK_LINEAGE);
    }

    @Test
    @DisplayName("Rule Pack 이 섞여 있으면 재분석 필요로 말한다")
    void refusesMixedRulePacks() {
        RepositoryAnalysis older = new RepositoryAnalysis("an_2", "202", "octocat/old", SHA,
                Instant.EPOCH, REGISTRY, "rule-pack-20260911.3", PACK_SHA, true, false);
        given(List.of(analysis(), older), List.of(row(1L, "DEPENDENCY", "L1", null)));

        // C 는 하나의 evidence_rule_version 으로 모든 근거를 검증한다. 섞으면 옛 Rule
        // Pack 의 근거가 전부 버려지고, 그 사실이 오류로 드러나지 않는다.
        assertThat(assembler.assemble(USER_ID).unavailable())
                .isEqualTo(UserEvidenceAssembler.Unavailable.MIXED_RULE_PACK);
    }

    @Test
    @DisplayName("C가 검사하는 버전은 Registry가 아니라 Rule Pack이다")
    void sendsRulePackAsEvidenceRuleVersion() {
        given(List.of(analysis()), List.of(row(1L, "DEPENDENCY", "L1", null)));

        EvidencePayload payload = assembler.assemble(USER_ID).payload();

        // C 는 evidence_rule_version 으로 근거의 범위를 검사한다. 여기에 Registry
        // 버전을 넣으면 모든 근거가 범위 불일치로 버려지는데, 오류가 아니라 조용한
        // 0건으로 나타나 화면에는 "전부 미판정"으로만 보인다.
        assertThat(payload.evidenceRuleVersion()).isEqualTo(RULE_PACK);
        assertThat(payload.registryVersion()).isEqualTo(REGISTRY);
        assertThat(payload.repositories().getFirst().technologies().getFirst()
                .proofs().getFirst().ruleVersion()).isEqualTo(RULE_PACK);
    }

    @Test
    @DisplayName("파일을 건너뛴 분석을 완전 판정으로 보내지 않는다")
    void skippedFilesAreNotCompleteCoverage() {
        given(List.of(analysis(RULE_PACK, true, true)),
                List.of(row(1L, "DEPENDENCY", "L1", null)));

        EvidencePayload.Repository repository =
                assembler.assemble(USER_ID).payload().repositories().getFirst();

        // 성공만으로 참을 만들면 저장소 일부만 본 분석이 완전 판정으로 나가고,
        // C 가 "이 기술을 쓰지 않는다"까지 결론짓는다.
        assertThat(repository.coverageComplete()).isFalse();
        assertThat(repository.dataGaps()).contains("FILES_SKIPPED");
    }

    @Test
    @DisplayName("건너뛴 사유를 보고받지 못한 계약도 완전 판정이 아니다")
    void unreportedSkipsAreNotCompleteCoverage() {
        given(List.of(analysis(RULE_PACK, false, false)),
                List.of(row(1L, "DEPENDENCY", "L1", null)));

        EvidencePayload.Repository repository =
                assembler.assemble(USER_ID).payload().repositories().getFirst();

        // 건너뛴 것이 없다는 뜻이 아니라 모른다는 뜻이다. 둘을 같게 다루면 모르는
        // 분석이 완전 판정으로 나간다.
        assertThat(repository.coverageComplete()).isFalse();
        assertThat(repository.dataGaps()).contains("SKIP_REPORT_UNAVAILABLE");
    }

    @Test
    @DisplayName("판정 상한은 Rule Pack이 볼 수 있었던 최고 Level이다")
    void ceilingComesFromRulePackSupport() {
        // kafka 는 이 Rule Pack 에서 L1 까지만 본다. 관측치가 L2 라도 상한이 L1 보다
        // 높아질 수 없다 -- 규칙이 볼 수 없었던 구간을 판정했다고 말하면 안 된다.
        EvidenceRow kafka = new EvidenceRow("an_1", "101", SHA, 9L, REGISTRY, "rule-kafka",
                "L2", "kafka", "API_CALL", "src/main/java/App.java", 1, 2, BLAME, "SOLE_AUTHOR");
        given(List.of(analysis()), List.of(kafka));

        EvidencePayload.PersonalAssessment assessment =
                assembler.assemble(USER_ID).payload().personalAssessments().getFirst();

        assertThat(assessment.techId()).isEqualTo("kafka");
        assertThat(assessment.assessmentCeiling()).isEqualTo("L1");
    }

    @Test
    @DisplayName("확인하지 못한 것은 false가 아니라 null이다")
    void unconfirmedIsNullNotFalse() {
        // 의존성 근거만 있고 구현 근거도 기여 판정도 없는 상태.
        given(List.of(analysis()), List.of(row(1L, "DEPENDENCY", "L1", null)));

        EvidencePayload.Technology technology = onlyTechnology();

        assertThat(technology.directDependency()).isTrue();
        // 구현을 못 봤다는 것이지 "구현이 없다"가 아니다. false 를 보내면 C 가
        // 그 기술을 쓰지 않는다고 결론짓는다.
        assertThat(technology.implementationPresent()).isNull();
        assertThat(technology.userParticipation()).isNull();
        assertThat(technology.implementedBy()).isEqualTo("UNKNOWN");
        assertThat(technology.attributionStatus()).isEqualTo("UNKNOWN");
    }

    @Test
    @DisplayName("본인이 쓴 구현 근거가 있으면 SELF로 보낸다")
    void reportsSelfImplementation() {
        given(List.of(analysis()), List.of(
                row(1L, "DEPENDENCY", "L1", null),
                row(2L, "API_CALL", "L2", "SOLE_AUTHOR")));

        EvidencePayload.Technology technology = onlyTechnology();

        assertThat(technology.implementationPresent()).isTrue();
        assertThat(technology.userParticipation()).isTrue();
        assertThat(technology.implementedBy()).isEqualTo("SELF");
        // 근거 둘 중 하나만 판정됐다.
        assertThat(technology.attributionStatus()).isEqualTo("PARTIAL");
        assertThat(technology.evidenceLevel()).isEqualTo("L2");
    }

    @Test
    @DisplayName("PARTIAL_EDIT는 본인이 쓴 줄이 아니다")
    void partialEditIsNotSelf() {
        given(List.of(analysis()), List.of(row(1L, "API_CALL", "L2", "PARTIAL_EDIT")));

        EvidencePayload.Technology technology = onlyTechnology();

        assertThat(technology.userParticipation()).isNull();
        assertThat(technology.implementedBy()).isEqualTo("UNKNOWN");
        assertThat(technology.proofs().getFirst().attribution()).isEqualTo("OTHER");
    }

    @Test
    @DisplayName("OTHER_AUTHOR는 OTHER로, UNVERIFIED는 UNKNOWN으로 나간다")
    void keepsAConfirmedOtherAuthorApartFromAnUnverifiedOne() {
        // C 가 이 둘을 구분해야 미확인을 부족으로 세지 않는다. 앞은 커밋 작성자를
        // 물어 본인이 아님을 확인한 것이고, 뒤는 물어보지 못한 것이다.
        given(List.of(analysis()), List.of(
                row(1L, "API_CALL", "L2", "OTHER_AUTHOR"),
                row(2L, "IMPORT", "L1", "UNVERIFIED")));

        List<EvidencePayload.Proof> proofs = onlyTechnology().proofs();

        assertThat(proofs).hasSize(2);
        assertThat(proofs.get(0).attribution()).isEqualTo("OTHER");
        assertThat(proofs.get(1).attribution()).isEqualTo("UNKNOWN");
    }

    @Test
    @DisplayName("근거 행은 C가 인정하는 형태로 나간다")
    void buildsAcceptableProofs() {
        given(List.of(analysis()), List.of(
                row(1L, "DEPENDENCY", "L1", "CO_AUTHORED"),
                row(2L, "CONFIG_KEY", "L1", null)));

        List<EvidencePayload.Proof> proofs = onlyTechnology().proofs();

        EvidencePayload.Proof dependency = proofs.getFirst();
        // C는 DIRECT_DEPENDENCY 를 MANIFEST/SBOM + direct_dependency=true 일 때만 인정한다.
        assertThat(dependency.kind()).isEqualTo("DIRECT_DEPENDENCY");
        assertThat(dependency.sourceKind()).isEqualTo("MANIFEST");
        assertThat(dependency.directDependency()).isTrue();
        assertThat(dependency.attribution()).isEqualTo("SELF");
        assertThat(dependency.attributionCommitSha()).isEqualTo(BLAME);
        // 이 셋 중 하나라도 다르면 C가 그 근거를 버린다.
        assertThat(dependency.acceptance()).isEqualTo("ACCEPTED");
        assertThat(dependency.origin()).isEqualTo("PROJECT");
        assertThat(dependency.inherited()).isFalse();
        // factId 가 factIds 에 없으면 범위 불일치로 버려진다.
        assertThat(onlyTechnology().factIds()).contains(dependency.factId());

        EvidencePayload.Proof config = proofs.get(1);
        assertThat(config.kind()).isEqualTo("IMPLEMENTATION");
        assertThat(config.sourceKind()).isEqualTo("CONFIG");
        assertThat(config.directDependency()).isNull();
        assertThat(config.attributionCommitSha()).isNull();
    }

    @Test
    @DisplayName("blame 커밋이 없으면 SELF로 보내지 않는다")
    void selfNeedsAttributionCommit() {
        EvidenceRow authoredWithoutBlame = new EvidenceRow("an_1", "101", SHA, 1L, REGISTRY,
                "rule-1", "L2", "spring", "API_CALL", "src/App.java", 1, 2, null, "SOLE_AUTHOR");
        given(List.of(analysis()), List.of(authoredWithoutBlame));

        // C 는 attribution=SELF 인데 커밋이 없는 근거를 참여 근거로 인정하지 않는다.
        // 그 조합을 보내느니 미확인으로 두는 편이 사실에 가깝다.
        assertThat(onlyTechnology().proofs().getFirst().attribution()).isEqualTo("UNKNOWN");
    }

    @Test
    @DisplayName("저장소 상대 경로가 아니면 그 근거만 뺀다")
    void dropsUnsafePaths() {
        EvidenceRow absolute = new EvidenceRow("an_1", "101", SHA, 1L, REGISTRY, "rule-1", "L1",
                "spring", "DEPENDENCY", "/etc/passwd", 1, 1, null, null);
        EvidenceRow traversal = new EvidenceRow("an_1", "101", SHA, 2L, REGISTRY, "rule-2", "L1",
                "spring", "DEPENDENCY", "../outside/build.gradle", 1, 1, null, null);
        given(List.of(analysis()), List.of(absolute, traversal, row(3L, "IMPORT", "L1", null)));

        List<EvidencePayload.Proof> proofs = onlyTechnology().proofs();

        // 한 줄 때문에 묶음 전체가 422 가 되면 안 된다.
        assertThat(proofs).hasSize(1);
        assertThat(proofs.getFirst().path()).isEqualTo("src/main/java/App.java");
    }

    @Test
    @DisplayName("근거가 0건인 저장소도 판정 범위에 넣고, 범위는 분석마다 다르다")
    void keepsRepositoriesWithoutEvidence() {
        RepositoryAnalysis empty = new RepositoryAnalysis("an_2", "202", "octocat/docs", SHA,
                Instant.EPOCH, REGISTRY, RULE_PACK, PACK_SHA, true, false);
        given(List.of(analysis(), empty), List.of(row(1L, "DEPENDENCY", "L1", null)));
        when(evidence.technologySupport(anyLong())).thenReturn(List.of(
                new TechnologySupport("an_1", "spring", "L3", "SUPPORTED"),
                new TechnologySupport("an_2", "docker", "L1", "SUPPORTED"),
                // 규칙이 없어 보지 못한 기술. 평가 범위에 넣으면 "안 쓴다"고 단정하게 된다.
                new TechnologySupport("an_2", "rust", "L0", "UNSUPPORTED")));

        List<EvidencePayload.Repository> repositories =
                assembler.assemble(USER_ID).payload().repositories();

        // "분석했는데 아는 기술이 없었다"와 "분석하지 않았다"는 다른 사실이다.
        assertThat(repositories).hasSize(2);
        assertThat(repositories.get(1).technologies()).isEmpty();
        // 범위는 그 분석의 Rule Pack 이 실제로 본 기술이다. Registry 전체가 아니다.
        assertThat(repositories.getFirst().evaluatedTechIds()).containsExactly("spring");
        assertThat(repositories.get(1).evaluatedTechIds()).containsExactly("docker");
    }

    @Test
    @DisplayName("실패한 저장소가 있으면 COMPLETE로 보내지 않는다")
    void reportsPartialWhenARepositoryFailed() {
        given(List.of(analysis()), List.of(row(1L, "DEPENDENCY", "L1", null)));
        when(evidence.failedRepositoryIds(USER_ID)).thenReturn(List.of("303"));

        EvidencePayload payload = assembler.assemble(USER_ID).payload();

        assertThat(payload.status()).isEqualTo("PARTIAL");
        assertThat(payload.dataGaps()).contains("REPOSITORY_ANALYSIS_FAILED");
    }

    @Test
    @DisplayName("개인 판정은 top-level에만 두고 저장소 기술에 넣지 않는다")
    void personalLevelLivesOnlyAtTopLevel() {
        given(List.of(analysis()), List.of(row(1L, "API_CALL", "L2", "SOLE_AUTHOR")));
        when(profiles.personalLevels(USER_ID)).thenReturn(
                List.of(new TechnologyProfileStore.TechnologyLevel("spring", "L2")));

        EvidencePayload payload = assembler.assemble(USER_ID).payload();

        assertThat(payload.schemaVersion()).isEqualTo("evidence-consumption-input/v4");
        assertThat(payload.personalAssessments()).hasSize(1);
        EvidencePayload.PersonalAssessment assessment = payload.personalAssessments().getFirst();
        assertThat(assessment.personalLevel()).isEqualTo("L2");
        assertThat(assessment.attributionStatus()).isEqualTo("COMPLETE");
        assertThat(assessment.missingScope()).isEmpty();
        // 상한은 관측치(L2)가 아니라 Rule Pack 이 볼 수 있었던 최고 Level(L3)이다.
        // 관측치를 상한으로 삼으면 규칙이 볼 수 있었던 구간을 "판정하지 않았다"고
        // 말하게 되고, C 는 그만큼 미보유 판정을 못 하게 된다.
        assertThat(assessment.assessmentCeiling()).isEqualTo("L3");
    }

    @Test
    @DisplayName("기여 판정이 없으면 무엇을 못 봤는지 함께 적는다")
    void incompleteAttributionCarriesMissingScope() {
        given(List.of(analysis()), List.of(row(1L, "API_CALL", "L2", null)));

        EvidencePayload.PersonalAssessment assessment =
                assembler.assemble(USER_ID).payload().personalAssessments().getFirst();

        // C 는 COMPLETE 가 아닌데 missing_scope 가 비어 있으면 묶음을 거절한다.
        assertThat(assessment.attributionStatus()).isEqualTo("UNKNOWN");
        assertThat(assessment.missingScope()).containsExactly("repository:101");
        assertThat(assessment.personalLevel()).isEqualTo("L0");
        // 귀속을 확인하지 못하면 상한이 L1 로 내려간다. 구현과 참여는 작성자를 알아야
        // 판정할 수 있어서, 그 위를 "판정했는데 없었다"고 말할 수 없다. 관측된 L2 를
        // 그대로 상한으로 쓰던 것이 잘못이었다.
        assertThat(assessment.assessmentCeiling()).isEqualTo("L1");
    }

    @Test
    @DisplayName("Evidence 버전은 같은 입력이면 같고 커밋이 바뀌면 달라진다")
    void evidenceVersionIsDeterministic() {
        given(List.of(analysis()), List.of(row(1L, "DEPENDENCY", "L1", null)));
        String first = assembler.assemble(USER_ID).evidenceVersion();
        String second = assembler.assemble(USER_ID).evidenceVersion();

        RepositoryAnalysis recommitted =
                new RepositoryAnalysis("an_1", "101", "octocat/api", "c".repeat(40),
                        Instant.EPOCH, REGISTRY, RULE_PACK, PACK_SHA, true, false);
        given(List.of(recommitted), List.of(row(1L, "DEPENDENCY", "L1", null)));
        String afterNewCommit = assembler.assemble(USER_ID).evidenceVersion();

        // 값이 흔들리면 event ID 가 매번 달라져 C 가 같은 계산을 반복한다.
        assertThat(first).isEqualTo(second).matches("[0-9a-f]{64}");
        assertThat(afterNewCommit).isNotEqualTo(first);
    }

    @Test
    @DisplayName("C에 보내는 분석 ID는 저장소 분석 ID가 아니라 사용자 단위다")
    void analysisIdIsUserScoped() {
        given(List.of(analysis()), List.of(row(1L, "DEPENDENCY", "L1", null)));

        EvidencePayload payload = assembler.assemble(USER_ID).payload();

        assertThat(payload.analysisId())
                .startsWith("u7-")
                .isNotEqualTo("an_1")
                // C 의 Identifier 패턴과 길이 제한.
                .matches("[A-Za-z0-9][A-Za-z0-9._:-]{0,127}");
        // 저장소 쪽에는 BE 의 분석 ID 가 그대로 남아야 근거의 범위 검사를 통과한다.
        assertThat(payload.repositories().getFirst().repositoryAnalysisId()).isEqualTo("an_1");
        assertThat(payload.repositories().getFirst().technologies().getFirst()
                .proofs().getFirst().analysisId()).isEqualTo(payload.analysisId());
    }

    private EvidencePayload.Technology onlyTechnology() {
        return assembler.assemble(USER_ID).payload()
                .repositories().getFirst().technologies().getFirst();
    }
}
