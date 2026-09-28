package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * C가 받는 사용자 Evidence 묶음 {@code evidence-consumption-input/v4} (S15P21E102-279).
 *
 * <p>이 계약의 원본은 운영 C의 {@code GET /internal/v1/c/contracts}가 생성하는 schema이고,
 * 구현은 {@code AI/recommendation/evidence.py}다. 이 파일이 그것과 어긋나면 C가 422로
 * 거절하므로, 필드를 임의로 늘리거나 줄이지 않는다({@code extra="forbid"}).</p>
 *
 * <h2>v4에서 반드시 지켜야 하는 것</h2>
 *
 * <ul>
 *   <li>개인 종합은 {@link PersonalAssessment}에만 둔다. 저장소 기술에 개인 Level을
 *       중복해서 실으면 C가 통째로 거절한다 — 그래서 {@link Technology}에 그 필드가 없다.</li>
 *   <li>{@code null}은 "아니다"가 아니라 "확인하지 못했다"이다. 판정하지 못한 것을
 *       {@code false}로 바꾸면 C가 "그 기술을 쓰지 않았다"로 읽는다.</li>
 *   <li>{@link Proof}가 없으면 C는 어떤 기술도 보유로 인정하지 않는다. 화면의
 *       "충족"은 전부 근거 행에서 나온다.</li>
 * </ul>
 */
public record EvidencePayload(
        String schemaVersion,
        String userId,
        String analysisId,
        String registryVersion,
        String levelPolicyVersion,
        String evidenceRuleVersion,
        /** {@code COMPLETE} · {@code PARTIAL} · {@code FAILED}. */
        String status,
        List<Repository> repositories,
        List<PersonalAssessment> personalAssessments,
        List<String> dataGaps
) {

    public static final String SCHEMA_VERSION = "evidence-consumption-input/v4";

    /**
     * 저장소 한 곳의 판정 범위.
     *
     * <p>{@code evaluatedTechIds}가 판정 범위를 정한다. 여기에 없는 기술은 C에서
     * "평가하지 않음"이 되고 부족으로 세지 않는다. 근거가 나온 기술만 넣으면 사용자가
     * 실제로 안 쓰는 기술까지 전부 미판정이 되어 Skill Gap이 빈다. 반대로 Registry
     * 전체를 넣으면 규칙이 없는 기술까지 "없다"고 단정하게 된다. 그래서 Rule Pack이
     * 실제로 평가할 수 있는 기술만 넣는다.</p>
     */
    public record Repository(
            String userId,
            String repositoryId,
            /** BE의 분석 ID. 사용자 단위 {@code analysisId}와 다른 값이다. */
            String repositoryAnalysisId,
            String commitSha,
            /** {@code COMPLETE} · {@code PARTIAL} · {@code FAILED} · {@code UNSUPPORTED} · {@code PERMISSION_DENIED}. */
            String status,
            boolean coverageComplete,
            List<String> evaluatedTechIds,
            List<Technology> technologies,
            List<String> dataGaps
    ) {
    }

    /**
     * 저장소 하나에서 본 기술 하나.
     *
     * <p>세 개의 {@code Boolean}은 3-상태다. {@code true}는 확인, {@code null}은 미확인,
     * {@code false}는 <em>없음을 확인함</em>이다. BE는 없음을 증명할 수 없으므로
     * {@code false}를 쓰지 않는다 — 규칙이 안 걸린 것과 실제로 안 쓴 것을 구분할 수단이
     * 없기 때문이다.</p>
     */
    public record Technology(
            String techId,
            /** 최소 1건. C는 {@link Proof#factId()}가 이 목록에 있는 근거만 인정한다. */
            List<String> factIds,
            /** {@code L0}~{@code L3} 또는 {@code null}(미판정). */
            String evidenceLevel,
            Boolean directDependency,
            Boolean implementationPresent,
            Boolean userParticipation,
            /** {@code SELF} · {@code OTHER} · {@code NONE} · {@code UNKNOWN}. */
            String implementedBy,
            /** {@code COMPLETE} · {@code PARTIAL} · {@code UNKNOWN}. */
            String attributionStatus,
            List<String> sourceRefs,
            List<Proof> proofs
    ) {
    }

    /**
     * 근거 한 줄. C가 보유 판정에 실제로 쓰는 유일한 입력이다.
     *
     * <p>C는 이 행을 그대로 믿지 않고 범위를 다시 맞춰 본다. {@code userId}·
     * {@code analysisId}·{@code repositoryId}·{@code repositoryAnalysisId}·
     * {@code sourceCommitSha}·{@code techId}·{@code ruleVersion}이 상위 묶음과 하나라도
     * 다르거나 {@code factId}가 {@link Technology#factIds()}에 없으면 그 근거를 버린다.</p>
     *
     * <p>{@code origin}이 {@code PROJECT}가 아니거나 {@code inherited}가 참이면 역시
     * 버린다. 남의 코드나 생성된 코드를 사용자의 근거로 세지 않기 위한 조건이다.</p>
     */
    public record Proof(
            String evidenceId,
            String factId,
            String ruleId,
            /** Registry 버전. 상위 {@code evidenceRuleVersion}과 같아야 한다. */
            String ruleVersion,
            String techId,
            String userId,
            String analysisId,
            String repositoryId,
            String repositoryAnalysisId,
            /** 분석 대상 커밋. 40자 소문자 hex. */
            String sourceCommitSha,
            /** {@code DIRECT_DEPENDENCY} · {@code IMPLEMENTATION} · {@code PARTICIPATION}. */
            String kind,
            /** {@code MANIFEST} · {@code SBOM} · {@code SOURCE} · {@code CONFIG} · {@code TEST} · {@code README} · {@code LOCKFILE}. */
            String sourceKind,
            String path,
            Integer lineStart,
            Integer lineEnd,
            String sourceRef,
            /** {@code ACCEPTED} · {@code EXCLUDED} · {@code UNCONFIRMED}. */
            String acceptance,
            String exclusionReason,
            /** {@code PROJECT} · {@code GENERATED} · {@code VENDOR} · {@code COPIED} · {@code FORK_BASE} · {@code UNKNOWN}. */
            String origin,
            boolean inherited,
            /** {@code SELF} · {@code OTHER} · {@code NONE} · {@code UNKNOWN}. */
            String attribution,
            /** blame이 지목한 커밋. {@code SELF}일 때 없으면 C가 참여 근거로 인정하지 않는다. */
            String attributionCommitSha,
            Boolean directDependency
    ) {
    }

    /**
     * 사용자 단위 개인 판정. v4에서 개인 Level이 사는 유일한 자리다.
     *
     * <p>{@code assessmentCeiling}은 "BE의 규칙이 배제할 수 있는 최고 Level"이다.
     * 기여 판정이 끝나지 않았으면 그 위는 판단하지 않았다는 뜻이고, C는 그 위를
     * 미보유로 세지 않는다. {@code personalLevel}은 이 값을 넘을 수 없다.</p>
     *
     * <p>{@code attributionStatus}가 {@code COMPLETE}가 아니면 {@code missingScope}가
     * 비어 있으면 안 된다. 무엇을 못 봤는지 적지 않은 불완전 판정은 C가 거절한다.</p>
     */
    public record PersonalAssessment(
            String techId,
            String personalLevel,
            String assessmentCeiling,
            String attributionStatus,
            List<String> missingScope
    ) {
    }
}
