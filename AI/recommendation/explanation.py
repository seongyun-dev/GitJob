"""Fact-grounded Korean explanations; optional planning never supplies claims."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from recommendation.engine import RecommendationSnapshot
from recommendation.evidence import ProfiledHeldTechnology

EXPLANATION_VERSION = "c-fact-explanation/v2"


class ExplanationFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    kind: Literal["DEMAND", "WHAT_IF", "PREREQUISITE", "EVIDENCE", "QUALITY"]
    tech_id: str | None
    text: str
    values: dict[str, JsonValue]
    source_refs: tuple[str, ...]


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["recommendation-explanation/v1"] = (
        "recommendation-explanation/v1"
    )
    explanation_version: Literal["c-fact-explanation/v1", "c-fact-explanation/v2"] = (
        EXPLANATION_VERSION
    )
    snapshot_id: str
    mode: Literal["RULE", "GROUNDED_SELECTION"]
    fallback_reason: Literal["INVALID_NARRATIVE_PLAN"] | None = None
    facts: tuple[ExplanationFact, ...]


class NarrativePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["explanation-order/v1"]
    snapshot_id: str
    fact_ids: tuple[str, ...]


def _fact(kind, tech_id, text, values, refs=()) -> ExplanationFact:
    source_refs = tuple(sorted(set(refs)))
    identity = json.dumps(
        {
            "kind": kind,
            "tech_id": tech_id,
            "values": values,
            "source_refs": source_refs,
            "text": text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ExplanationFact(
        fact_id="fact-" + hashlib.sha256(identity.encode()).hexdigest(),
        kind=kind,
        tech_id=tech_id,
        text=text,
        values=values,
        source_refs=source_refs,
    )


def explain_recommendations(
    snapshot: RecommendationSnapshot, *, narrative_plan: dict | None = None
) -> Explanation:
    facts = []
    # 계산에 쓴 집합과 같은 것을 본다. `jobs` 만 보면 확장 계산에서 `matching_jobs`
    # 에만 있는 공고를 만나 설명 생성이 통째로 실패한다 (S15P21E102-361).
    jobs = {job.job_id: job for job in snapshot.calculation_jobs}
    for candidate in snapshot.candidates:
        demand = candidate.demand
        values = {
            "total_count": demand.total_count,
            "required_count": demand.required_count,
            "preferred_count": demand.preferred_count,
            "general_count": demand.general_count,
            "denominator": snapshot.demand.denominator,
            "cohort_id": snapshot.cohort_id,
        }
        facts.append(
            _fact(
                "DEMAND",
                candidate.tech_id,
                f"동일 기준 공고 {snapshot.demand.denominator}건 중 {demand.total_count}건에서 {candidate.tech_id} 기술이 관측됐습니다. 필수 {demand.required_count}건, 우대 {demand.preferred_count}건이며 유형별 공고는 겹칠 수 있습니다.",
                values,
            )
        )
        what_if = candidate.what_if
        values = {
            "current_count": what_if.current_count,
            "projected_count": what_if.projected_count,
            "increased_count": what_if.increased_count,
            "newly_matched_job_ids": list(what_if.newly_matched_job_ids),
            "cohort_id": snapshot.cohort_id,
        }
        facts.append(
            _fact(
                "WHAT_IF",
                candidate.tech_id,
                f"{candidate.tech_id} 하나를 추가하면 기술요건 기준 부합 공고는 {what_if.current_count}건에서 {what_if.projected_count}건으로 {what_if.increased_count}건 증가합니다.",
                values,
                (
                    str(jobs[job_id].source_url)
                    for job_id in what_if.newly_matched_job_ids
                ),
            )
        )
        if candidate.prerequisite_tech_ids:
            values = {
                "prerequisite_tech_ids": list(candidate.prerequisite_tech_ids),
                "missing_prerequisite_tech_ids": list(
                    candidate.missing_prerequisite_tech_ids
                ),
                "unknown_prerequisite_tech_ids": list(
                    candidate.unknown_prerequisite_tech_ids
                ),
            }
            text = f"선행 학습 확인 대상은 {', '.join(candidate.prerequisite_tech_ids)}입니다."
            if candidate.missing_prerequisite_tech_ids:
                text += f" 현재 근거가 부족한 선행 기술: {', '.join(candidate.missing_prerequisite_tech_ids)}."
            if candidate.unknown_prerequisite_tech_ids:
                text += f" 분석 미확정 선행 기술: {', '.join(candidate.unknown_prerequisite_tech_ids)}."
            facts.append(_fact("PREREQUISITE", candidate.tech_id, text, values))

    for technology in snapshot.held.technologies:
        reasons = set(technology.reason_codes)
        refs = tuple(ref for p in technology.provenance for ref in p.source_refs)
        used_fact_ids = sorted(
            {fid for p in technology.provenance for fid in p.fact_ids}
        )
        if "SELF_IMPLEMENTATION" in reasons:
            text = f"{technology.tech_id}는 분석한 저장소에서 본인이 직접 작성한 구현 근거가 확인됐습니다."
        elif "PROJECT_IMPLEMENTATION_WITH_PARTICIPATION" in reasons:
            text = f"{technology.tech_id}는 본인이 참여한 프로젝트에서 구현 근거가 확인됐습니다. 본인 작성 여부와는 별도의 보유 판정입니다."
        elif "ELIGIBLE_DIRECT_DEPENDENCY" in reasons:
            text = f"{technology.tech_id}는 유효한 참여 근거가 있는 저장소에서 직접 의존성이 확인되어 추천 계산에 포함했습니다. 구현이나 숙련도를 뜻하지 않습니다."
        elif technology.status.value == "UNKNOWN":
            text = f"{technology.tech_id}는 분석 범위나 근거가 충분하지 않아 미확정 상태입니다."
        elif "DEPENDENCY_ONLY" in reasons:
            text = f"{technology.tech_id}는 의존성 선언만 확인되어 현재 구현·참여 기준의 보유 기술에 포함되지 않았습니다."
        else:
            text = f"{technology.tech_id}는 분석한 저장소에서 현재 구현·참여 기준을 충족하는 근거가 확인되지 않았습니다."
        profile_values = []
        supporting = ()
        if isinstance(technology, ProfiledHeldTechnology):
            # Accepted for inclusion is not enough to support every stronger
            # claim. A SELF sentence cites SELF implementation only, not a
            # failed peer, dependency declaration, or OTHER-authored proof.
            supporting = technology.supporting_proofs
            if "SELF_IMPLEMENTATION" in reasons:
                supporting = tuple(
                    proof
                    for proof in supporting
                    if proof.tech_id == technology.tech_id
                    and proof.kind == "IMPLEMENTATION"
                    and proof.attribution == "SELF"
                )
            elif "PROJECT_IMPLEMENTATION_WITH_PARTICIPATION" in reasons:
                supporting = tuple(
                    proof
                    for proof in supporting
                    if proof.tech_id == technology.tech_id
                    and proof.kind == "IMPLEMENTATION"
                )
            elif "ELIGIBLE_DIRECT_DEPENDENCY" in reasons:
                eligibility_ids = {
                    (proof.repository_id, proof.evidence_id)
                    for profile in technology.profiles
                    if profile.supporting_proofs
                    for proof in profile.eligibility_proofs
                }
                supporting = tuple(
                    proof
                    for proof in supporting
                    if (
                        proof.tech_id == technology.tech_id
                        and proof.kind == "DIRECT_DEPENDENCY"
                    )
                    or (proof.repository_id, proof.evidence_id) in eligibility_ids
                )
            else:
                supporting = ()
                if technology.status.value != "UNKNOWN":
                    text = f"{technology.tech_id}는 분석한 저장소 범위에서 추천용 확인 기술 정책을 충족하는 근거가 확인되지 않았습니다. 개인 지식의 부재를 뜻하지 않습니다."
            refs = tuple(proof.source_ref for proof in supporting)
            used_fact_ids = sorted({proof.fact_id for proof in supporting})
            profile_values = [
                {
                    "repository_id": profile.repository_id,
                    "repository_analysis_id": profile.repository_analysis_id,
                    "commit_sha": profile.commit_sha,
                    "reported_level": profile.evidence_level,
                    "verified_level": profile.verified_level,
                    "validation_status": profile.validation_status,
                    "validation_reasons": list(profile.validation_reasons),
                    "observation_validation_status": profile.observation_validation_status,
                    "observation_validation_reasons": list(
                        profile.observation_validation_reasons
                    ),
                    "direct_dependency_status": profile.direct_dependency_status,
                    "implementation_status": profile.implementation_status,
                    "participation_status": profile.participation_status,
                    "self_implementation_status": profile.self_implementation_status,
                }
                for profile in technology.profiles
            ]
        values = {
            "status": technology.status.value,
            "reason_codes": list(technology.reason_codes),
            "fact_ids": used_fact_ids,
            "held_policy_version": snapshot.held.held_policy_version,
        }
        if isinstance(technology, ProfiledHeldTechnology):
            values["profiles"] = profile_values
            values["used_evidence_ids"] = [proof.evidence_id for proof in supporting]
            values["supporting_scope"] = [
                {
                    "repository_id": proof.repository_id,
                    "commit_sha": proof.source_commit_sha,
                    "tech_id": proof.tech_id,
                    "evidence_id": proof.evidence_id,
                    "fact_id": proof.fact_id,
                }
                for proof in supporting
            ]
        facts.append(
            _fact(
                "EVIDENCE",
                technology.tech_id,
                text,
                values,
                refs,
            )
        )

    values = {
        "status": snapshot.status,
        "denominator": snapshot.demand.denominator,
        "excluded_count": snapshot.demand.excluded_count,
        "review_count": snapshot.demand.review_count,
        "data_gaps": list(snapshot.data_gaps),
        "cohort_id": snapshot.cohort_id,
    }
    text = f"포함 공고 {snapshot.demand.denominator}건을 기준으로 계산했습니다. 제외 {snapshot.demand.excluded_count}건, 검토 필요 {snapshot.demand.review_count}건입니다."
    if snapshot.data_gaps:
        text += " 일부 입력·분석 근거가 부족하므로 미확정 기술을 미보유로 간주하지 않았습니다."
    text += (
        " 부합 건수는 분석한 기술요건 기준이며 채용 가능성이나 숙련도 점수가 아닙니다."
    )
    facts.append(_fact("QUALITY", None, text, values))

    mode = "RULE"
    fallback_reason = None
    if narrative_plan is not None:
        try:
            plan = NarrativePlan.model_validate(narrative_plan)
            by_id = {fact.fact_id: fact for fact in facts}
            if (
                plan.snapshot_id != snapshot.snapshot_id
                or len(plan.fact_ids) != len(facts)
                or set(plan.fact_ids) != set(by_id)
            ):
                raise ValueError("plan must contain exactly this snapshot's facts")
            facts = [by_id[fact_id] for fact_id in plan.fact_ids]
            mode = "GROUNDED_SELECTION"
        except (ValidationError, ValueError):
            fallback_reason = "INVALID_NARRATIVE_PLAN"
    return Explanation(
        snapshot_id=snapshot.snapshot_id,
        mode=mode,
        fallback_reason=fallback_reason,
        facts=tuple(facts),
    )
