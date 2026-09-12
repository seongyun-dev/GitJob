"""Versioned B-result adapter and C's repository-scoped held-technology policy.

C owns the shared Rule Pack and its required extractors. B runs repository
analysis, owns personal attribution and aggregation, then supplies Evidence.
This consumer never infers a personal level from source code or blame.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from registry.contracts import TechId

LEVEL_POLICY_VERSION = "level-policy/v2"
LEGACY_HELD_POLICY_VERSION = "c-held/project-participation/v1"
HELD_POLICY_VERSION = "c-confirmed/eligible-observation/v1"
HeldPolicyVersion = Literal[
    "c-held/project-participation/v1", "c-confirmed/eligible-observation/v1"
]
NonBlank = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RepositoryStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"


CommitSha = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{40}$")]
ObservationStatus = Literal["CONFIRMED", "NOT_OBSERVED", "UNKNOWN"]
EvidenceLevel = Literal["L0", "L1", "L2", "L3"]
_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


class EvidenceProof(EvidenceModel):
    """B-accepted fact metadata, not source text or a C Rule/blame execution."""

    evidence_id: NonBlank
    fact_id: NonBlank
    rule_id: NonBlank
    rule_version: NonBlank
    tech_id: TechId
    user_id: NonBlank
    analysis_id: NonBlank
    repository_id: NonBlank
    repository_analysis_id: NonBlank
    source_commit_sha: CommitSha
    kind: Literal["DIRECT_DEPENDENCY", "IMPLEMENTATION", "PARTICIPATION"]
    source_kind: Literal[
        "MANIFEST", "SBOM", "SOURCE", "CONFIG", "TEST", "README", "LOCKFILE"
    ]
    path: NonBlank
    line_start: StrictInt | None = Field(default=None, ge=1)
    line_end: StrictInt | None = Field(default=None, ge=1)
    source_ref: NonBlank
    acceptance: Literal["ACCEPTED", "EXCLUDED", "UNCONFIRMED"]
    exclusion_reason: NonBlank | None
    origin: Literal["PROJECT", "GENERATED", "VENDOR", "COPIED", "FORK_BASE", "UNKNOWN"]
    inherited: StrictBool
    attribution: Literal["SELF", "OTHER", "NONE", "UNKNOWN"]
    attribution_commit_sha: CommitSha | None
    direct_dependency: StrictBool | None

    @model_validator(mode="after")
    def validate_source_locator(self) -> "EvidenceProof":
        path = self.path.replace("\\", "/")
        if (
            path.startswith("/")
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 for char in path)
        ):
            raise ValueError("proof path must be a safe repository-relative path")
        if (self.line_start is None) != (self.line_end is None) or (
            self.line_start is not None and self.line_end < self.line_start
        ):
            raise ValueError("proof line range must be ordered and complete")
        if self.source_kind in {"SOURCE", "CONFIG", "TEST"} and self.line_start is None:
            raise ValueError("source proof requires an exact line range")
        return self


class TechnologyEvidence(EvidenceModel):
    tech_id: TechId
    fact_ids: tuple[NonBlank, ...] = Field(min_length=1)
    evidence_level: Literal["L0", "L1", "L2", "L3"] | None
    # B's explicit user-attributed level.  C must never substitute the
    # repository-level/evidence_level axis when evaluating a job requirement.
    personal_level: Literal["L0", "L1", "L2", "L3"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    direct_dependency: StrictBool | None
    implementation_present: StrictBool | None
    user_participation: StrictBool | None
    implemented_by: Literal["SELF", "OTHER", "NONE", "UNKNOWN"]
    attribution_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    source_refs: tuple[NonBlank, ...] = ()
    proofs: tuple[EvidenceProof, ...] = ()

    @field_validator("proofs")
    @classmethod
    def canonicalize_proofs(
        cls, values: tuple[EvidenceProof, ...]
    ) -> tuple[EvidenceProof, ...]:
        by_id = {}
        for proof in values:
            if proof.evidence_id in by_id and by_id[proof.evidence_id] != proof:
                raise ValueError("conflicting proof for the same evidence ID")
            by_id[proof.evidence_id] = proof
        return tuple(sorted(by_id.values(), key=lambda proof: proof.evidence_id))

    @field_validator("fact_ids", "source_refs")
    @classmethod
    def canonicalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class RepositoryEvidence(EvidenceModel):
    user_id: NonBlank
    repository_id: NonBlank
    repository_analysis_id: NonBlank
    commit_sha: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{40}$")
    ]
    status: RepositoryStatus
    coverage_complete: StrictBool
    evaluated_tech_ids: tuple[TechId, ...] = ()
    technologies: tuple[TechnologyEvidence, ...]
    data_gaps: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def complete_coverage_requires_complete_repository(self) -> "RepositoryEvidence":
        if self.coverage_complete and self.status is not RepositoryStatus.COMPLETE:
            raise ValueError("coverage_complete requires COMPLETE repository status")
        technologies: dict[str, TechnologyEvidence] = {}
        proof_ids: dict[str, EvidenceProof] = {}
        for evidence in self.technologies:
            previous = technologies.get(evidence.tech_id)
            if previous is not None and previous != evidence:
                raise ValueError("conflicting assessments for the same technology")
            technologies[evidence.tech_id] = evidence
            for proof in evidence.proofs:
                if (
                    proof.evidence_id in proof_ids
                    and proof_ids[proof.evidence_id] != proof
                ):
                    raise ValueError(
                        "conflicting proof ID within one repository snapshot"
                    )
                proof_ids[proof.evidence_id] = proof
        return self


class PersonalTechnologyAssessment(EvidenceModel):
    """B's user-level conclusion and the highest level its rules can exclude."""

    tech_id: TechId
    personal_level: EvidenceLevel
    assessment_ceiling: EvidenceLevel
    attribution_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    missing_scope: tuple[NonBlank, ...] = ()

    @field_validator("missing_scope")
    @classmethod
    def canonicalize_missing_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def level_must_not_exceed_ceiling(self) -> "PersonalTechnologyAssessment":
        if _LEVEL_ORDER[self.personal_level] > _LEVEL_ORDER[self.assessment_ceiling]:
            raise ValueError("personal level is above assessment ceiling")
        if self.attribution_status != "COMPLETE" and not self.missing_scope:
            raise ValueError("incomplete attribution requires missing scope")
        return self


class EvidenceAnalysis(EvidenceModel):
    schema_version: Literal[
        "evidence-consumption-input/v1",
        "evidence-consumption-input/v2",
        "evidence-consumption-input/v3",
        "evidence-consumption-input/v4",
    ]
    user_id: NonBlank
    analysis_id: NonBlank
    registry_version: NonBlank
    level_policy_version: NonBlank
    evidence_rule_version: NonBlank
    status: AnalysisStatus
    repositories: tuple[RepositoryEvidence, ...]
    personal_assessments: tuple[PersonalTechnologyAssessment, ...] = ()
    data_gaps: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def reject_conflicting_repository_snapshots(self) -> "EvidenceAnalysis":
        repository_ids = [repository.repository_id for repository in self.repositories]
        if len(repository_ids) != len(set(repository_ids)):
            raise ValueError("duplicate repository snapshot in one analysis")
        assessment_ids = [item.tech_id for item in self.personal_assessments]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("duplicate personal technology assessment")
        if self.schema_version != "evidence-consumption-input/v4" and assessment_ids:
            raise ValueError("personal assessments require evidence input v4")
        if self.schema_version == "evidence-consumption-input/v4" and any(
            evidence.personal_level is not None
            for repository in self.repositories
            for evidence in repository.technologies
        ):
            raise ValueError(
                "v4 personal level must use aggregate personal assessments"
            )
        return self


class HeldStatus(StrEnum):
    HELD = "HELD"
    NOT_HELD = "NOT_HELD"
    UNKNOWN = "UNKNOWN"


class EvidenceProvenance(EvidenceModel):
    user_id: NonBlank
    analysis_id: NonBlank
    repository_id: NonBlank
    repository_analysis_id: NonBlank
    commit_sha: NonBlank
    tech_id: TechId
    fact_ids: tuple[NonBlank, ...]
    source_refs: tuple[NonBlank, ...]
    evidence_level: Literal["L0", "L1", "L2", "L3"] | None
    repository_status: RepositoryStatus
    level_policy_version: NonBlank
    evidence_rule_version: NonBlank


class HeldTechnology(EvidenceModel):
    tech_id: TechId
    status: HeldStatus
    reason_codes: tuple[NonBlank, ...]
    provenance: tuple[EvidenceProvenance, ...]
    data_gaps: tuple[NonBlank, ...]


class RepositoryCoverage(EvidenceModel):
    """Evaluation scope under the user/analysis/Rule versions of the envelope."""

    repository_id: NonBlank
    repository_analysis_id: NonBlank
    commit_sha: NonBlank
    status: RepositoryStatus
    coverage_complete: StrictBool
    evaluated_tech_ids: tuple[TechId, ...]
    data_gaps: tuple[NonBlank, ...]


class LegacyHeldTechnologySelection(EvidenceModel):
    schema_version: Literal["held-technology-selection/v1"] = (
        "held-technology-selection/v1"
    )
    user_id: NonBlank
    analysis_id: NonBlank
    registry_version: NonBlank
    level_policy_version: NonBlank
    evidence_rule_version: NonBlank
    held_policy_version: Literal["c-held/project-participation/v1"] = (
        LEGACY_HELD_POLICY_VERSION
    )
    analysis_status: AnalysisStatus
    repository_coverage: tuple[RepositoryCoverage, ...]
    held_tech_ids: tuple[TechId, ...]
    technologies: tuple[HeldTechnology, ...]
    data_gaps: tuple[NonBlank, ...]

    @property
    def by_tech_id(self) -> dict[str, HeldTechnology]:
        return {item.tech_id: item for item in self.technologies}

    @model_validator(mode="after")
    def validate_selected_set(self) -> "LegacyHeldTechnologySelection":
        ids = [item.tech_id for item in self.technologies]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate held technology decision")
        selected = tuple(
            sorted(
                item.tech_id
                for item in self.technologies
                if item.status is HeldStatus.HELD
            )
        )
        if selected != self.held_tech_ids:
            raise ValueError("held_tech_ids must match HELD decisions")
        repository_ids = [item.repository_id for item in self.repository_coverage]
        if len(repository_ids) != len(set(repository_ids)):
            raise ValueError("duplicate repository coverage")
        for item in self.technologies:
            if item.status is HeldStatus.NOT_HELD and (
                self.analysis_status is not AnalysisStatus.COMPLETE
                or not self.repository_coverage
                or any(
                    not repository.coverage_complete
                    or repository.status is not RepositoryStatus.COMPLETE
                    or item.tech_id not in repository.evaluated_tech_ids
                    for repository in self.repository_coverage
                )
            ):
                raise ValueError(
                    "NOT_HELD requires complete explicit technology coverage"
                )
        return self


class LegacyGapSnapshot(EvidenceModel):
    schema_version: Literal["technology-gap/v1"] = "technology-gap/v1"
    user_id: NonBlank
    analysis_id: NonBlank
    registry_version: NonBlank
    held_policy_version: Literal["c-held/project-participation/v1"] = (
        LEGACY_HELD_POLICY_VERSION
    )
    held_tech_ids: tuple[TechId, ...]
    missing_tech_ids: tuple[TechId, ...]
    unknown_tech_ids: tuple[TechId, ...]
    technologies: tuple[HeldTechnology, ...]
    data_gaps: tuple[NonBlank, ...]


class ProofValidation(EvidenceModel):
    proof: EvidenceProof
    accepted: StrictBool
    reason_codes: tuple[NonBlank, ...]


class RepositoryTechnologyProfile(EvidenceProvenance):
    """Consumed B result and validated axes; none is a proficiency estimate."""

    reported: TechnologyEvidence
    verified_level: EvidenceLevel | None
    validation_status: Literal["VALID", "UNCONFIRMED", "INCONSISTENT"]
    validation_reasons: tuple[NonBlank, ...]
    observation_validation_status: Literal["VALID", "UNCONFIRMED", "INCONSISTENT"]
    observation_validation_reasons: tuple[NonBlank, ...]
    direct_dependency_status: ObservationStatus
    implementation_status: ObservationStatus
    participation_status: ObservationStatus
    self_implementation_status: ObservationStatus
    proof_results: tuple[ProofValidation, ...]
    eligibility_proofs: tuple[EvidenceProof, ...]
    supporting_proofs: tuple[EvidenceProof, ...]
    data_gaps: tuple[NonBlank, ...]


class ProfiledHeldTechnology(HeldTechnology):
    profiles: tuple[RepositoryTechnologyProfile, ...] = ()
    supporting_proofs: tuple[EvidenceProof, ...] = ()


class HeldTechnologySelection(LegacyHeldTechnologySelection):
    schema_version: Literal["held-technology-selection/v2"] = (
        "held-technology-selection/v2"
    )
    held_policy_version: Literal["c-confirmed/eligible-observation/v1"] = (
        HELD_POLICY_VERSION
    )
    technologies: tuple[ProfiledHeldTechnology, ...]
    eligible_repository_ids: tuple[NonBlank, ...]

    @model_validator(mode="after")
    def require_supported_positive(self) -> "HeldTechnologySelection":
        coverage = {item.repository_id: item for item in self.repository_coverage}
        eligible = tuple(
            sorted(
                {
                    profile.repository_id
                    for item in self.technologies
                    for profile in item.profiles
                    if profile.participation_status == "CONFIRMED"
                }
            )
        )
        if self.eligible_repository_ids != eligible:
            raise ValueError(
                "eligible repository scope must match accepted participation proof"
            )
        for item in self.technologies:
            if item.status is HeldStatus.NOT_HELD and set(eligible) != set(coverage):
                raise ValueError(
                    "NOT_HELD requires confirmed eligibility of all selected repositories"
                )
            if item.status is HeldStatus.NOT_HELD and (
                self.level_policy_version != LEVEL_POLICY_VERSION
                or any(
                    profile.validation_status != "VALID"
                    or profile.observation_validation_status != "VALID"
                    for profile in item.profiles
                )
            ):
                raise ValueError(
                    "NOT_HELD requires confirmed observation absence, not an unconfirmed profile"
                )
            if len({profile.repository_id for profile in item.profiles}) != len(
                item.profiles
            ):
                raise ValueError("duplicate repository technology profile")
            for profile in item.profiles:
                scope = coverage.get(profile.repository_id)
                if scope is None or (
                    profile.user_id != self.user_id
                    or profile.analysis_id != self.analysis_id
                    or profile.tech_id != item.tech_id
                    or profile.repository_analysis_id != scope.repository_analysis_id
                    or profile.commit_sha != scope.commit_sha
                    or profile.repository_status != scope.status
                    or profile.level_policy_version != self.level_policy_version
                    or profile.evidence_rule_version != self.evidence_rule_version
                ):
                    raise ValueError("persisted profile scope mismatch")
                repository = RepositoryEvidence(
                    user_id=self.user_id,
                    repository_id=scope.repository_id,
                    repository_analysis_id=scope.repository_analysis_id,
                    commit_sha=scope.commit_sha,
                    status=scope.status,
                    coverage_complete=scope.coverage_complete,
                    evaluated_tech_ids=scope.evaluated_tech_ids,
                    technologies=tuple(
                        candidate.reported
                        for technology in self.technologies
                        for candidate in technology.profiles
                        if candidate.repository_id == scope.repository_id
                    ),
                    data_gaps=scope.data_gaps,
                )
                analysis = EvidenceAnalysis(
                    schema_version="evidence-consumption-input/v2",
                    user_id=self.user_id,
                    analysis_id=self.analysis_id,
                    registry_version=self.registry_version,
                    level_policy_version=self.level_policy_version,
                    evidence_rule_version=self.evidence_rule_version,
                    status=self.analysis_status,
                    repositories=(repository,),
                )
                if profile != _profile(analysis, repository, profile.reported):
                    raise ValueError("persisted profile differs from validated B proof")
            expected_proofs = tuple(
                sorted(
                    (
                        proof
                        for profile in item.profiles
                        for proof in profile.supporting_proofs
                    ),
                    key=lambda proof: (
                        proof.repository_id,
                        proof.repository_analysis_id,
                        proof.evidence_id,
                    ),
                )
            )
            if item.supporting_proofs != expected_proofs:
                raise ValueError("supporting proof must match validated profiles")
            if item.status is HeldStatus.HELD and not any(
                profile.observation_validation_status == "VALID"
                and (
                    profile.direct_dependency_status == "CONFIRMED"
                    or profile.implementation_status == "CONFIRMED"
                )
                and profile.participation_status == "CONFIRMED"
                and profile.supporting_proofs
                for profile in item.profiles
            ):
                raise ValueError(
                    "HELD requires same-repository confirmed observation and participation"
                )
            if item.status is not HeldStatus.HELD and expected_proofs:
                raise ValueError("confirmed profiles must be represented as HELD")
            if item.status is HeldStatus.HELD:
                qualifying = tuple(
                    profile for profile in item.profiles if profile.supporting_proofs
                )
                reasons = set()
                if any(
                    profile.direct_dependency_status == "CONFIRMED"
                    for profile in qualifying
                ):
                    reasons.add("ELIGIBLE_DIRECT_DEPENDENCY")
                if any(
                    profile.implementation_status == "CONFIRMED"
                    for profile in qualifying
                ):
                    reasons.add("ELIGIBLE_IMPLEMENTATION_SOURCE")
                if any(
                    profile.self_implementation_status == "CONFIRMED"
                    for profile in qualifying
                ):
                    reasons.add("SELF_IMPLEMENTATION")
                elif any(
                    profile.implementation_status == "CONFIRMED"
                    for profile in qualifying
                ):
                    reasons.add("PROJECT_IMPLEMENTATION_WITH_PARTICIPATION")
                if item.reason_codes != tuple(sorted(reasons)):
                    raise ValueError(
                        "HELD explanation reasons must match validated observations"
                    )
        return self


class GapSnapshot(LegacyGapSnapshot):
    schema_version: Literal["technology-gap/v2"] = "technology-gap/v2"
    held_policy_version: Literal["c-confirmed/eligible-observation/v1"] = (
        HELD_POLICY_VERSION
    )
    technologies: tuple[ProfiledHeldTechnology, ...]


def build_gap(
    selection: HeldTechnologySelection,
    *,
    demanded_tech_ids: Iterable[str],
) -> GapSnapshot:
    """Partition demand under one confirmed-technology policy; UNKNOWN is no gap."""
    by_id = selection.by_tech_id
    entries = tuple(
        by_id.get(tech_id)
        or ProfiledHeldTechnology(
            tech_id=tech_id,
            status=HeldStatus.UNKNOWN,
            reason_codes=("TECHNOLOGY_NOT_EVALUATED",),
            provenance=(),
            data_gaps=("TECHNOLOGY_NOT_EVALUATED",),
        )
        for tech_id in sorted(set(demanded_tech_ids))
    )
    return GapSnapshot(
        user_id=selection.user_id,
        analysis_id=selection.analysis_id,
        registry_version=selection.registry_version,
        held_tech_ids=tuple(
            item.tech_id for item in entries if item.status is HeldStatus.HELD
        ),
        missing_tech_ids=tuple(
            item.tech_id for item in entries if item.status is HeldStatus.NOT_HELD
        ),
        unknown_tech_ids=tuple(
            item.tech_id for item in entries if item.status is HeldStatus.UNKNOWN
        ),
        technologies=entries,
        data_gaps=tuple(
            sorted(
                set(selection.data_gaps)
                | {
                    f"TECHNOLOGY:{item.tech_id}:{gap}"
                    for item in entries
                    for gap in item.data_gaps
                }
            )
        ),
    )


def _check_proof(
    proof: EvidenceProof,
    evidence: TechnologyEvidence,
    repository: RepositoryEvidence,
    analysis: EvidenceAnalysis,
) -> ProofValidation:
    reasons = set()
    scope = (
        proof.user_id == analysis.user_id == repository.user_id
        and proof.analysis_id == analysis.analysis_id
        and proof.repository_id == repository.repository_id
        and proof.repository_analysis_id == repository.repository_analysis_id
        and proof.source_commit_sha == repository.commit_sha
        and proof.tech_id == evidence.tech_id
        and proof.rule_version == analysis.evidence_rule_version
        and proof.fact_id in evidence.fact_ids
    )
    if not scope:
        reasons.add("PROOF_SCOPE_MISMATCH")
    if proof.acceptance != "ACCEPTED":
        reasons.add(f"PROOF_{proof.acceptance}")
    if proof.exclusion_reason or proof.inherited or proof.origin != "PROJECT":
        reasons.add("PROOF_ORIGIN_EXCLUDED")
    if proof.kind == "DIRECT_DEPENDENCY":
        if (
            proof.source_kind not in {"MANIFEST", "SBOM"}
            or proof.direct_dependency is not True
        ):
            reasons.add("DIRECT_DEPENDENCY_PROOF_REQUIRED")
    elif proof.source_kind not in {"SOURCE", "CONFIG", "TEST"}:
        reasons.add("IMPLEMENTATION_OR_PARTICIPATION_SOURCE_REQUIRED")
    if proof.kind == "PARTICIPATION" and (
        proof.attribution != "SELF" or proof.attribution_commit_sha is None
    ):
        reasons.add("PARTICIPATION_PROOF_REQUIRED")
    if (
        proof.kind == "IMPLEMENTATION"
        and proof.attribution == "SELF"
        and (proof.attribution_commit_sha is None)
    ):
        reasons.add("SELF_ATTRIBUTION_PROOF_REQUIRED")
    if repository.status not in {RepositoryStatus.COMPLETE, RepositoryStatus.PARTIAL}:
        reasons.add(f"REPOSITORY_{repository.status.value}")
    if analysis.status is AnalysisStatus.FAILED:
        reasons.add("ANALYSIS_FAILED")
    return ProofValidation(
        proof=proof, accepted=not reasons, reason_codes=tuple(sorted(reasons))
    )


def _profile(
    analysis: EvidenceAnalysis,
    repository: RepositoryEvidence,
    evidence: TechnologyEvidence,
) -> RepositoryTechnologyProfile:
    checks = tuple(
        _check_proof(proof, evidence, repository, analysis) for proof in evidence.proofs
    )
    accepted = tuple(check.proof for check in checks if check.accepted)
    dependency = tuple(proof for proof in accepted if proof.kind == "DIRECT_DEPENDENCY")
    implementation = tuple(
        proof for proof in accepted if proof.kind == "IMPLEMENTATION"
    )
    # Eligibility is repository-wide in v2. Reuse accepted user-authored source
    # or participation proof in this snapshot without changing its original tech.
    participation = tuple(
        sorted(
            {
                proof.evidence_id: proof
                for assessment in repository.technologies
                for proof in assessment.proofs
                if proof.kind in {"PARTICIPATION", "IMPLEMENTATION"}
                and proof.attribution == "SELF"
                and proof.attribution_commit_sha is not None
                and assessment.user_participation is not False
                and (
                    proof.kind != "IMPLEMENTATION"
                    or (
                        assessment.implementation_present is not False
                        and assessment.implemented_by not in {"OTHER", "NONE"}
                    )
                )
                and _check_proof(proof, assessment, repository, analysis).accepted
            }.values(),
            key=lambda proof: proof.evidence_id,
        )
    )
    authored = tuple(proof for proof in implementation if proof.attribution == "SELF")
    complete = (
        analysis.status is AnalysisStatus.COMPLETE
        and repository.status is RepositoryStatus.COMPLETE
        and repository.coverage_complete
        and evidence.tech_id in repository.evaluated_tech_ids
    )
    gaps = {reason for check in checks for reason in check.reason_codes}
    inconsistent = set()
    unconfirmed = set()
    if not evidence.proofs and (
        evidence.direct_dependency is True
        or evidence.implementation_present is True
        or evidence.evidence_level in {"L1", "L2", "L3"}
    ):
        unconfirmed.add("STRUCTURED_PROOF_REQUIRED")
    if analysis.level_policy_version != LEVEL_POLICY_VERSION:
        unconfirmed.add("UNSUPPORTED_LEVEL_POLICY")
    if analysis.status is AnalysisStatus.FAILED:
        unconfirmed.add("ANALYSIS_FAILED")
    if repository.status not in {RepositoryStatus.COMPLETE, RepositoryStatus.PARTIAL}:
        unconfirmed.add(f"REPOSITORY_{repository.status.value}")
    if repository.status is not RepositoryStatus.COMPLETE:
        gaps.add(f"REPOSITORY_{repository.status.value}")
    if evidence.attribution_status != "COMPLETE":
        gaps.add("ATTRIBUTION_INCOMPLETE")
    if evidence.implementation_present is None:
        gaps.add("IMPLEMENTATION_UNCONFIRMED")

    # Check B's supplied result against necessary v2 conditions; never output a
    # newly calculated replacement level. The False-dependency L0 priority is
    # compatible with independently observed implementation.
    if evidence.implementation_present is False and evidence.implemented_by in {
        "SELF",
        "OTHER",
    }:
        inconsistent.add("INCONSISTENT_LEVEL_FACTS")
    if evidence.implementation_present is True and evidence.implemented_by == "NONE":
        inconsistent.add("INCONSISTENT_LEVEL_FACTS")
    if evidence.implemented_by == "SELF" and evidence.user_participation is False:
        inconsistent.add("INCONSISTENT_LEVEL_FACTS")
    for observed, reported in (
        (dependency, evidence.direct_dependency),
        (implementation, evidence.implementation_present),
        (participation, evidence.user_participation),
    ):
        if observed and reported is False:
            inconsistent.add("INCONSISTENT_LEVEL_FACTS")
    if authored and evidence.implemented_by in {"OTHER", "NONE"}:
        inconsistent.add("INCONSISTENT_LEVEL_FACTS")
    observation_conflicts = set(inconsistent)

    level = evidence.evidence_level
    if analysis.level_policy_version != LEVEL_POLICY_VERSION:
        pass  # Its numeric/string labels are never interpreted using v2 rules.
    elif level is None:
        unconfirmed.add("LEVEL_UNCONFIRMED")
    elif level == "L0":
        if evidence.direct_dependency is True:
            inconsistent.add("INCONSISTENT_LEVEL_FACTS")
        elif evidence.direct_dependency is None or not complete:
            unconfirmed.add("DIRECT_DEPENDENCY_UNCONFIRMED")
    else:
        if evidence.direct_dependency is False:
            inconsistent.add("INCONSISTENT_LEVEL_FACTS")
        elif evidence.direct_dependency is None:
            unconfirmed.add("DIRECT_DEPENDENCY_UNCONFIRMED")
        if not dependency:
            unconfirmed.add("DIRECT_DEPENDENCY_PROOF_REQUIRED")
        if level in {"L2", "L3"}:
            if (
                evidence.implementation_present is False
                or evidence.user_participation is False
            ):
                inconsistent.add("INCONSISTENT_LEVEL_FACTS")
            if evidence.implementation_present is None or not implementation:
                unconfirmed.add("IMPLEMENTATION_PROOF_REQUIRED")
            if not participation:
                unconfirmed.add("PARTICIPATION_PROOF_REQUIRED")
        if level == "L3":
            if evidence.implemented_by in {"OTHER", "NONE"}:
                inconsistent.add("INCONSISTENT_LEVEL_FACTS")
            if evidence.implemented_by != "SELF" or not authored:
                unconfirmed.add("SELF_ATTRIBUTION_PROOF_REQUIRED")
        if level == "L2" and authored:
            inconsistent.add("INCONSISTENT_LEVEL_FACTS")
        if level == "L1" and implementation and participation:
            inconsistent.add("INCONSISTENT_LEVEL_FACTS")

    # Inclusion always needs the user's valid participation, even for L1.
    if evidence.user_participation is False or not participation:
        gaps.add("PARTICIPATION_PROOF_REQUIRED")
    if evidence.direct_dependency is True and not dependency:
        gaps.add("DIRECT_DEPENDENCY_PROOF_REQUIRED")
    gaps.update(inconsistent | unconfirmed)
    verified_level = level if not inconsistent and not unconfirmed else None
    supported = bool(
        (dependency or implementation) and participation and not observation_conflicts
    )
    observation_reasons = set(observation_conflicts)
    observations_confirmed = bool(dependency or implementation)
    observation_absence_confirmed = (
        complete
        and evidence.direct_dependency is False
        and evidence.implementation_present is False
    )
    if not observations_confirmed and not observation_absence_confirmed:
        observation_reasons.add("ACCEPTED_TECHNOLOGY_OBSERVATION_REQUIRED")
    supporting = (
        tuple(
            sorted(
                {
                    proof.evidence_id: proof
                    for proof in (*dependency, *implementation, *participation)
                }.values(),
                key=lambda proof: proof.evidence_id,
            )
        )
        if supported
        else ()
    )
    return RepositoryTechnologyProfile(
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
        repository_id=repository.repository_id,
        repository_analysis_id=repository.repository_analysis_id,
        commit_sha=repository.commit_sha,
        tech_id=evidence.tech_id,
        fact_ids=evidence.fact_ids,
        source_refs=evidence.source_refs,
        evidence_level=level,
        repository_status=repository.status,
        level_policy_version=analysis.level_policy_version,
        evidence_rule_version=analysis.evidence_rule_version,
        reported=evidence,
        verified_level=verified_level,
        validation_status="INCONSISTENT"
        if inconsistent
        else "UNCONFIRMED"
        if unconfirmed
        else "VALID",
        validation_reasons=tuple(sorted(inconsistent | unconfirmed)),
        observation_validation_status="INCONSISTENT"
        if observation_conflicts
        else "VALID"
        if observations_confirmed or observation_absence_confirmed
        else "UNCONFIRMED",
        observation_validation_reasons=tuple(sorted(observation_reasons)),
        direct_dependency_status="CONFIRMED"
        if dependency
        else (
            "NOT_OBSERVED"
            if evidence.direct_dependency is False and complete
            else "UNKNOWN"
        ),
        implementation_status="CONFIRMED"
        if implementation
        else (
            "NOT_OBSERVED"
            if evidence.implementation_present is False and complete
            else "UNKNOWN"
        ),
        participation_status="CONFIRMED" if participation else "UNKNOWN",
        self_implementation_status="CONFIRMED" if authored else "UNKNOWN",
        proof_results=checks,
        eligibility_proofs=participation,
        supporting_proofs=tuple(supporting),
        data_gaps=tuple(sorted(gaps)),
    )


def consume_evidence(
    analysis: EvidenceAnalysis,
    *,
    user_id: str,
    analysis_id: str,
    tech_ids: Iterable[str],
) -> HeldTechnologySelection:
    """Validate B proof per repo, then union confirmed technologies; never levels."""
    if analysis.user_id != user_id or analysis.analysis_id != analysis_id:
        raise PermissionError("Evidence analysis identity does not match request")
    if any(repository.user_id != user_id for repository in analysis.repositories):
        raise PermissionError("Evidence repository user does not match request")

    supported_policy = analysis.level_policy_version == LEVEL_POLICY_VERSION
    gaps = set(analysis.data_gaps)
    if not supported_policy:
        gaps.add(f"UNSUPPORTED_LEVEL_POLICY:{analysis.level_policy_version}")
    if analysis.status is not AnalysisStatus.COMPLETE:
        gaps.add(f"ANALYSIS_{analysis.status.value}")
    if not analysis.repositories:
        gaps.add("NO_REPOSITORY_ANALYSIS")
    complete_analysis = (
        bool(analysis.repositories) and analysis.status is AnalysisStatus.COMPLETE
    )
    observations: dict[str, list[RepositoryTechnologyProfile]] = {}
    for repository in sorted(
        analysis.repositories, key=lambda item: item.repository_id
    ):
        complete_analysis &= (
            repository.coverage_complete
            and repository.status is RepositoryStatus.COMPLETE
        )
        if not repository.coverage_complete:
            gaps.add(f"REPOSITORY_COVERAGE_INCOMPLETE:{repository.repository_id}")
        if repository.status is not RepositoryStatus.COMPLETE:
            gaps.add(f"REPOSITORY_{repository.status.value}:{repository.repository_id}")
        gaps.update(repository.data_gaps)
        unique = {item.tech_id: item for item in repository.technologies}
        for evidence in unique.values():
            observations.setdefault(evidence.tech_id, []).append(
                _profile(analysis, repository, evidence)
            )

    decisions = []
    eligible_repositories = {
        profile.repository_id
        for profiles in observations.values()
        for profile in profiles
        if profile.participation_status == "CONFIRMED"
    }
    for tech_id in sorted(set(tech_ids) | set(observations)):
        profiles = tuple(observations.get(tech_id, ()))
        local_gaps = {gap for profile in profiles for gap in profile.data_gaps}
        complete_coverage = complete_analysis and all(
            tech_id in repository.evaluated_tech_ids
            for repository in analysis.repositories
        )
        for repository in analysis.repositories:
            if tech_id not in repository.evaluated_tech_ids:
                local_gaps.add(f"TECHNOLOGY_NOT_COVERED:{repository.repository_id}")
            if repository.repository_id not in eligible_repositories:
                local_gaps.add(
                    f"PARTICIPATION_SCOPE_UNCONFIRMED:{repository.repository_id}"
                )
        qualifying = tuple(profile for profile in profiles if profile.supporting_proofs)
        reasons = set()
        if qualifying:
            status = HeldStatus.HELD
            if any(
                profile.direct_dependency_status == "CONFIRMED"
                for profile in qualifying
            ):
                reasons.add("ELIGIBLE_DIRECT_DEPENDENCY")
            if any(
                profile.implementation_status == "CONFIRMED" for profile in qualifying
            ):
                reasons.add("ELIGIBLE_IMPLEMENTATION_SOURCE")
            if any(
                profile.self_implementation_status == "CONFIRMED"
                for profile in qualifying
            ):
                reasons.add("SELF_IMPLEMENTATION")
            elif any(
                profile.implementation_status == "CONFIRMED" for profile in qualifying
            ):
                reasons.add("PROJECT_IMPLEMENTATION_WITH_PARTICIPATION")
        elif (
            not supported_policy
            or not complete_coverage
            or len(eligible_repositories) != len(analysis.repositories)
            or any(profile.validation_status != "VALID" for profile in profiles)
            or any(
                profile.observation_validation_status != "VALID" for profile in profiles
            )
            or any(
                profile.reported.direct_dependency is True
                and profile.participation_status != "CONFIRMED"
                for profile in profiles
            )
        ):
            status = HeldStatus.UNKNOWN
            if not complete_coverage:
                local_gaps.add("INCOMPLETE_ANALYSIS_COVERAGE")
            if not supported_policy:
                local_gaps.add("UNSUPPORTED_LEVEL_POLICY")
            reasons.update(local_gaps or {"UNCONFIRMED_EVIDENCE"})
        else:
            status = HeldStatus.NOT_HELD
            reasons.add("NO_QUALIFYING_EVIDENCE_IN_ANALYZED_REPOSITORIES")
        for gap in local_gaps:
            gaps.add(f"TECHNOLOGY:{tech_id}:{gap}")
        supporting = tuple(
            sorted(
                (
                    proof
                    for profile in qualifying
                    for proof in profile.supporting_proofs
                ),
                key=lambda proof: (
                    proof.repository_id,
                    proof.repository_analysis_id,
                    proof.evidence_id,
                ),
            )
        )
        decisions.append(
            ProfiledHeldTechnology(
                tech_id=tech_id,
                status=status,
                reason_codes=tuple(sorted(reasons)),
                # Deliberately retain the historical view without new default fields.
                provenance=tuple(
                    EvidenceProvenance.model_validate(
                        {
                            name: getattr(profile, name)
                            for name in EvidenceProvenance.model_fields
                        }
                    )
                    for profile in profiles
                ),
                profiles=profiles,
                supporting_proofs=supporting,
                data_gaps=tuple(sorted(local_gaps)),
            )
        )
    return HeldTechnologySelection(
        user_id=user_id,
        analysis_id=analysis_id,
        registry_version=analysis.registry_version,
        level_policy_version=analysis.level_policy_version,
        evidence_rule_version=analysis.evidence_rule_version,
        analysis_status=analysis.status,
        repository_coverage=tuple(
            RepositoryCoverage(
                repository_id=repository.repository_id,
                repository_analysis_id=repository.repository_analysis_id,
                commit_sha=repository.commit_sha,
                status=repository.status,
                coverage_complete=repository.coverage_complete,
                evaluated_tech_ids=tuple(sorted(set(repository.evaluated_tech_ids))),
                data_gaps=tuple(sorted(set(repository.data_gaps))),
            )
            for repository in sorted(
                analysis.repositories, key=lambda item: item.repository_id
            )
        ),
        held_tech_ids=tuple(
            item.tech_id for item in decisions if item.status is HeldStatus.HELD
        ),
        technologies=tuple(decisions),
        data_gaps=tuple(sorted(gaps)),
        eligible_repository_ids=tuple(sorted(eligible_repositories)),
    )


def consume_personal_levels(
    analysis: EvidenceAnalysis, selection: HeldTechnologySelection
) -> dict[str, EvidenceLevel]:
    """Return only per-repository, proof-supported B personal levels.

    A partial analysis does not erase an accepted positive observation from a
    different (or the same partial) repository.  Missing coverage remains in
    ``selection`` and is handled as an incomplete clause only when no positive
    personal level can satisfy it.
    """
    if (
        analysis.schema_version != "evidence-consumption-input/v3"
        or analysis.level_policy_version != LEVEL_POLICY_VERSION
    ):
        return {}
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    levels: dict[str, EvidenceLevel] = {}
    for decision in selection.technologies:
        for profile in decision.profiles:
            level = profile.reported.personal_level
            if level is None or not profile.supporting_proofs:
                continue
            previous = levels.get(decision.tech_id)
            if previous is None or order[level] > order[previous]:
                levels[decision.tech_id] = level
    return levels


def consume_personal_level_scope_complete_tech_ids(
    analysis: EvidenceAnalysis, selection: HeldTechnologySelection
) -> frozenset[str]:
    """Return v3 technologies whose observed level is safe for negative claims.

    A proof-supported level is always usable as positive evidence. Declaring it
    below a job requirement additionally needs complete repository coverage and
    complete attribution across every selected repository.
    """
    if (
        analysis.schema_version != "evidence-consumption-input/v3"
        or analysis.level_policy_version != LEVEL_POLICY_VERSION
        or analysis.status is not AnalysisStatus.COMPLETE
        or not analysis.repositories
    ):
        return frozenset()
    repository_ids = {repository.repository_id for repository in analysis.repositories}
    if set(selection.eligible_repository_ids) != repository_ids or any(
        repository.status is not RepositoryStatus.COMPLETE
        or not repository.coverage_complete
        for repository in analysis.repositories
    ):
        return frozenset()

    levels = consume_personal_levels(analysis, selection)
    complete = set()
    for tech_id in levels:
        decision = selection.by_tech_id[tech_id]
        if all(
            tech_id in repository.evaluated_tech_ids
            for repository in analysis.repositories
        ) and all(
            profile.reported.attribution_status == "COMPLETE"
            and profile.validation_status == "VALID"
            and profile.observation_validation_status == "VALID"
            for profile in decision.profiles
        ):
            complete.add(tech_id)
    return frozenset(complete)


class PersonalLevelAssessment(EvidenceModel):
    tech_id: TechId
    personal_level: EvidenceLevel
    assessment_ceiling: EvidenceLevel
    scope_complete: StrictBool
    missing_scope: tuple[NonBlank, ...] = ()


def consume_personal_assessments(
    analysis: EvidenceAnalysis, selection: HeldTechnologySelection
) -> dict[str, PersonalLevelAssessment]:
    """Validate v4 aggregate personal conclusions against C's proof/coverage view.

    Positive levels remain usable when another repository is partial. A negative
    conclusion (LEVEL_BELOW_REQUIRED) is safe only when ``scope_complete`` is true
    and the requested level is no higher than ``assessment_ceiling``.
    """
    if (
        analysis.schema_version != "evidence-consumption-input/v4"
        or analysis.level_policy_version != LEVEL_POLICY_VERSION
    ):
        return {}
    decisions = selection.by_tech_id
    eligible_repositories = set(selection.eligible_repository_ids)
    result: dict[str, PersonalLevelAssessment] = {}
    for reported in analysis.personal_assessments:
        decision = decisions.get(reported.tech_id)
        if (
            decision is None
            or decision.status is not HeldStatus.HELD
            or not decision.supporting_proofs
        ):
            raise ValueError(
                f"personal assessment requires proof-supported held technology: {reported.tech_id}"
            )
        coverage_complete = analysis.status is AnalysisStatus.COMPLETE and all(
            repository.status is RepositoryStatus.COMPLETE
            and repository.coverage_complete
            and reported.tech_id in repository.evaluated_tech_ids
            and repository.repository_id in eligible_repositories
            for repository in analysis.repositories
        )
        result[reported.tech_id] = PersonalLevelAssessment(
            tech_id=reported.tech_id,
            personal_level=reported.personal_level,
            assessment_ceiling=reported.assessment_ceiling,
            scope_complete=(
                coverage_complete and reported.attribution_status == "COMPLETE"
            ),
            missing_scope=reported.missing_scope,
        )
    return result
