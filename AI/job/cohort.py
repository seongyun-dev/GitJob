"""Reproducible quality cohorts for active matching or observed monthly demand."""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from job.classifier import (
    JobClassificationBatch,
    JobClassificationRecord,
    RequirementClass,
    TechnologyClassification,
    classify_job_batch,
)
from job.contracts import (
    BodyStatus,
    JobAnalysisInputBatch,
    JobPostingInput,
    PostingStatus,
)
from job.eligibility import FilterMatch, match_career_level, match_region
from job.matching import MatchingJobInput
from job.requirements import (
    JOB_REQUIREMENTS_SCHEMA_VERSION,
    JobRequirements,
    RequirementClause,
    RequirementKind,
    extract_job_requirements,
)
from registry.contracts import TechId, load_registry
from registry.mapper import RegistryMapper

JOB_COHORT_SCHEMA_VERSION = "job-cohort/v1"
# v8: cohort에 싣는 기술 분류에서 `mapping_context`를 비운다(티켓 S15P21E102-333).
# 판정 결과는 그대로지만 저장되는 payload의 의미가 달라지므로, 같은 조건이라도 예전
# snapshot을 재사용하지 않고 다시 계산하도록 버전을 올린다.
JOB_QUALITY_VERSION = "job-cohort-quality/v8"


class CohortPurpose(StrEnum):
    ACTIVE_MATCHING = "ACTIVE_MATCHING"
    MONTHLY_DEMAND = "MONTHLY_DEMAND"
    # 현재 확보한 공고 전체의 기술 수요. 직무도 기간도 없다 -- 개인화 결과가 아니라
    # 시장 Snapshot이므로 역할로 모집단을 줄이면 그 순간 다른 질문에 답하게 된다.
    CURRENT_MARKET = "CURRENT_MARKET"


def requires_original_posting_date(criteria: "CohortCriteria") -> bool:
    """Whether a date range promises original-posting-date semantics.

    Active matching date filters retain their strict historical meaning. Monthly
    demand instead follows the date displayed by the source, which may be either
    a posting date or a modification date, so those observations stay usable.
    """

    return bool(criteria.posted_from or criteria.posted_to) and (
        criteria.purpose is not CohortPurpose.MONTHLY_DEMAND
    )


# 시장 밖으로 나가는 제외 사유. 호출자가 선언한 범위(출처·지역·경력)를 벗어났거나
# 기준 시각에 아직 관측되지 않은 공고는 "우리 시장"이 아니다. 나머지 제외·검토 사유는
# 시장 안에 있지만 아직 해석하지 못했다는 뜻이므로 분모에 남는다.
MARKET_SCOPE_EXCLUSIONS = frozenset(
    {
        "SOURCE_NOT_MATCHED",
        "REGION_NOT_MATCHED",
        "CAREER_LEVEL_NOT_MATCHED",
        "COLLECTED_AFTER_AS_OF",
        "POSTED_AFTER_AS_OF",
    }
)


class CohortStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    EMPTY = "EMPTY"

    @classmethod
    def for_size(cls, count: int, minimum: int) -> "CohortStatus":
        if count == 0:
            return cls.EMPTY
        return cls.INSUFFICIENT_DATA if count < minimum else cls.READY


class CohortModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_ROLE_ALIASES = {
    "BACKEND": (
        "BACKEND",
        "BACKEND_ENGINEER",
        "백엔드",
        "백엔드 개발",
        "백엔드 개발자",
        "백엔드개발자",
        "백엔드/서버개발",
    ),
    "FRONTEND": (
        "FRONTEND",
        "FRONTEND_ENGINEER",
        "프론트엔드",
        "프론트엔드 개발",
        "프론트엔드 개발자",
        "프론트엔드개발자",
    ),
    "AI_DATA": (
        "AI_DATA",
        "AI_ENGINEER",
        "DATA_ENGINEER",
        "AI/데이터",
        "데이터 엔지니어",
        "AI 개발자",
        "데이터엔지니어",
        "데이터사이언티스트",
        "AI/ML엔지니어",
        "AI/ML연구원",
        "데이터분석가",
        "프롬프트엔지니어",
        "MLOps엔지니어",
        "AI서비스개발자",
    ),
    "INFRASTRUCTURE": (
        "INFRASTRUCTURE",
        "DEVOPS",
        "DEVOPS_ENGINEER",
        "인프라",
        "인프라 엔지니어",
        "데브옵스",
        "시스템엔지니어",
        "네트워크엔지니어",
        "DBA",
        "보안엔지니어",
        "클라우드엔지니어",
    ),
    "MOBILE": (
        "MOBILE",
        "MOBILE_ENGINEER",
        "모바일",
        "모바일 개발",
        "모바일 개발자",
        "앱개발자",
    ),
}
_ROLE_LOOKUP = {
    alias.casefold(): role
    for role, aliases in _ROLE_ALIASES.items()
    for alias in aliases
}
_TITLE_ROLES = {
    "BACKEND": r"백엔드|backend",
    "FRONTEND": (
        r"프론트엔드|frontend|"
        r"(?:React|Vue(?:\.js)?|Next(?:\.js)?)\s*(?:웹\s*)?개발자"
    ),
    "AI_DATA": (
        r"데이터\s*엔지니어|"
        r"AI\s*(?:(?:Research|ML|LLM|Data|Agent|Application)\s+)*"
        r"(?:개발자|개발\s+엔지니어|엔지니어|engineer)|data\s+engineer"
    ),
    "INFRASTRUCTURE": r"데브옵스|devops|인프라\s*엔지니어",
    "MOBILE": r"모바일\s*(?:개발자|엔지니어)|mobile\s+(?:developer|engineer)",
}


def normalize_cohort_filters(
    values: tuple[str, ...] | None, *, uppercase: bool = False
) -> tuple[str, ...] | None:
    """Canonical cohort filters shared by writers and exact-stream readers."""
    if values is None:
        return None
    if any(not value.strip() for value in values):
        raise ValueError("filter values must not be blank")
    normalized = (value.strip() for value in values)
    if uppercase:
        normalized = (value.upper() for value in normalized)
    return tuple(sorted(set(normalized)))


class CohortCriteria(CohortModel):
    # CURRENT_MARKET에서만 비어 있다. 기존 snapshot은 항상 값이 있으므로 저장된
    # JSON의 바이트 모양과 cohort_id 해시는 그대로 유지된다.
    target_role: StrictStr | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    as_of: datetime
    purpose: CohortPurpose = Field(
        default=CohortPurpose.ACTIVE_MATCHING,
        # Preserve the byte shape/hash of stored pre-purpose recommendations.
        exclude_if=lambda value: value == CohortPurpose.ACTIVE_MATCHING,
    )
    posted_from: datetime | None = None
    posted_to: datetime | None = None
    sources: tuple[StrictStr, ...] = ()
    regions: tuple[StrictStr, ...] = ()
    career_levels: tuple[StrictStr, ...] = ()
    min_jobs: StrictInt = Field(default=1, ge=1)

    @field_validator("target_role")
    @classmethod
    def normalize_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        role = _ROLE_LOOKUP.get(value.strip().casefold())
        if role is None:
            raise ValueError(
                "unsupported target_role; use an explicit supported role alias"
            )
        return role

    @field_validator("sources", "regions", "career_levels")
    @classmethod
    def normalize_filters(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = normalize_cohort_filters(values)
        assert normalized is not None
        return normalized

    @field_validator("sources")
    @classmethod
    def normalize_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = normalize_cohort_filters(values, uppercase=True)
        assert normalized is not None
        return normalized

    @field_validator("as_of", "posted_from", "posted_to")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamp must include a timezone")
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "CohortCriteria":
        if self.posted_from and self.posted_to and self.posted_from >= self.posted_to:
            raise ValueError("posted_from must precede posted_to (exclusive)")
        if self.purpose is CohortPurpose.MONTHLY_DEMAND:
            self.complete_month()
        if self.purpose is CohortPurpose.CURRENT_MARKET:
            # 역할을 받으면 시장이 아니라 직무 코호트가 되고, 저장된 lineage가
            # 실제 모집단과 어긋난다. 기간을 받으면 게시일 의미를 약속하게 된다.
            if self.target_role is not None:
                raise ValueError("CURRENT_MARKET must not carry a target_role")
            if self.posted_from or self.posted_to:
                raise ValueError("CURRENT_MARKET must not carry a posting period")
        elif self.target_role is None:
            raise ValueError("target_role is required outside CURRENT_MARKET")
        return self

    def complete_month(self) -> str:
        """Validate a completed Seoul calendar month; as_of is an observation cutoff."""
        if self.posted_from is None or self.posted_to is None:
            raise ValueError("MONTH_WINDOW_REQUIRED")
        timezone = ZoneInfo("Asia/Seoul")
        start, end = (
            self.posted_from.astimezone(timezone),
            self.posted_to.astimezone(timezone),
        )
        next_month = datetime(
            start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=timezone
        )
        if (
            start != datetime(start.year, start.month, 1, tzinfo=timezone)
            or end != next_month
        ):
            raise ValueError("FULL_MONTH_WINDOW_REQUIRED")
        if self.as_of < end:
            raise ValueError("MONTH_NOT_COMPLETE")
        return start.strftime("%Y-%m")


class CohortJob(CohortModel):
    job_id: StrictStr
    source_record_id: StrictStr
    canonical_job_id: StrictStr | None = None
    source_site: StrictStr
    source_posting_id: StrictStr
    source_url: HttpUrl
    company_name: StrictStr
    title: StrictStr
    raw_job_category: StrictStr | None = None
    region: StrictStr | None = None
    career_level: StrictStr | None = None
    posted_at: datetime | None = None
    deadline: datetime | None = None
    posting_status: PostingStatus | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    collected_at: datetime
    content_hash: StrictStr
    raw_artifact_uri: StrictStr | None = None
    required_clauses: tuple[tuple[TechId, ...], ...] = Field(min_length=1)
    # Additive v2 view.  The compact v1 clauses remain the legacy
    # recommendation snapshot contract.
    levelled_required_clauses: tuple[RequirementClause, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preferred_tech_ids: tuple[TechId, ...] = ()
    general_tech_ids: tuple[TechId, ...] = ()
    technologies: tuple[TechnologyClassification, ...] = ()

    @field_validator("required_clauses")
    @classmethod
    def require_resolved_clauses(
        cls, clauses: tuple[tuple[str, ...], ...]
    ) -> tuple[tuple[str, ...], ...]:
        if any(not clause for clause in clauses):
            raise ValueError("required clauses must contain at least one technology")
        return tuple(sorted({tuple(sorted(set(clause))) for clause in clauses}))

    @model_validator(mode="after")
    def levelled_clauses_match_legacy_ids(self) -> "CohortJob":
        if self.levelled_required_clauses is not None:
            for clause in self.levelled_required_clauses:
                RequirementClause.model_validate(clause.model_dump(mode="json"))
                if clause.required_level is None or not clause.level_evidence_refs:
                    raise ValueError("levelled clauses require level and evidence")
            if (
                tuple(
                    sorted(clause.tech_ids for clause in self.levelled_required_clauses)
                )
                != self.required_clauses
            ):
                raise ValueError("levelled clauses must preserve required clause IDs")
        return self


class CohortExclusion(CohortModel):
    source_record_id: StrictStr
    canonical_job_id: StrictStr | None = None
    source_site: StrictStr
    source_posting_id: StrictStr
    source_url: HttpUrl
    content_hash: StrictStr
    company_name: StrictStr
    title: StrictStr
    raw_job_category: StrictStr | None = None
    region: StrictStr | None = None
    career_level: StrictStr | None = None
    body_status: BodyStatus
    posting_status: PostingStatus
    posted_at: datetime | None = None
    deadline: datetime | None = None
    collected_at: datetime
    raw_artifact_uri: StrictStr | None = None
    decision: Literal["EXCLUDED", "REVIEW_REQUIRED"]
    reasons: tuple[StrictStr, ...] = Field(min_length=1)
    technologies: tuple[TechnologyClassification, ...] = ()


UnionDigest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class InputUnionBatch(CohortModel):
    input_id: UnionDigest
    source_site: StrictStr
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    collected_at: datetime
    batch_sha256: UnionDigest
    manifest_sha256: UnionDigest
    batch_content_sha256: UnionDigest
    record_count: StrictInt = Field(ge=0)
    batch_size_bytes: StrictInt = Field(gt=0)


class InputUnionObservation(CohortModel):
    input_id: UnionDigest
    record_index: StrictInt = Field(ge=0)
    source_site: StrictStr
    source_posting_id: StrictStr
    source_record_id: StrictStr
    collected_at: datetime
    record_sha256: UnionDigest
    disposition: Literal[
        "SELECTED", "CONFLICT", "DUPLICATE", "SUPERSEDED", "AFTER_AS_OF"
    ]


class InputUnionProvenance(CohortModel):
    schema_version: Literal["job-input-union/v1"] = "job-input-union/v1"
    policy_version: StrictStr
    scope: Literal["OBSERVED_UNION"] = "OBSERVED_UNION"
    input_batches: tuple[InputUnionBatch, ...]
    observations: tuple[InputUnionObservation, ...]
    input_record_count: StrictInt = Field(ge=0)
    input_bytes: StrictInt = Field(ge=0)
    selected_record_count: StrictInt = Field(ge=0)
    conflict_record_count: StrictInt = Field(ge=0)
    duplicate_record_count: StrictInt = Field(ge=0)
    superseded_record_count: StrictInt = Field(ge=0)
    after_as_of_record_count: StrictInt = Field(ge=0)
    sources_without_as_of_observations: tuple[StrictStr, ...]
    superseded_input_batch_count: StrictInt = Field(
        default=0, ge=0, exclude_if=lambda value: value == 0
    )

    @model_validator(mode="after")
    def reconcile_observations(self) -> "InputUnionProvenance":
        inputs = {item.input_id: item for item in self.input_batches}
        if len(inputs) != len(self.input_batches):
            raise ValueError("union input references must be unique")
        if self.input_record_count != len(
            self.observations
        ) or self.input_record_count != sum(
            item.record_count for item in self.input_batches
        ):
            raise ValueError("union raw record counts do not reconcile")
        if self.input_bytes != sum(
            item.batch_size_bytes for item in self.input_batches
        ):
            raise ValueError("union input bytes do not reconcile")
        seen = set()
        for observation in self.observations:
            key = (observation.input_id, observation.record_index)
            source = inputs.get(observation.input_id)
            if (
                key in seen
                or source is None
                or observation.record_index >= source.record_count
                or observation.source_site != source.source_site
                or observation.collected_at != source.collected_at
            ):
                raise ValueError("union observation lacks a unique source reference")
            seen.add(key)
        counts = Counter(item.disposition for item in self.observations)
        for disposition, attribute in (
            ("SELECTED", "selected_record_count"),
            ("CONFLICT", "conflict_record_count"),
            ("DUPLICATE", "duplicate_record_count"),
            ("SUPERSEDED", "superseded_record_count"),
            ("AFTER_AS_OF", "after_as_of_record_count"),
        ):
            if getattr(self, attribute) != counts[disposition]:
                raise ValueError("union selection counts do not reconcile")
        observed_sources = {
            item.source_site
            for item in self.observations
            if item.disposition != "AFTER_AS_OF"
        }
        if self.sources_without_as_of_observations != tuple(
            sorted({item.source_site for item in self.input_batches} - observed_sources)
        ):
            raise ValueError("union source observation coverage does not reconcile")
        return self


class JobCohort(CohortModel):
    schema_version: Literal["job-cohort/v1"] = JOB_COHORT_SCHEMA_VERSION
    cohort_id: StrictStr
    status: CohortStatus
    criteria: CohortCriteria
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    registry_version: StrictStr
    parser_version: StrictStr
    quality_version: StrictStr = JOB_QUALITY_VERSION
    input_count: StrictInt = Field(ge=0)
    duplicate_count: StrictInt = Field(ge=0)
    excluded_count: StrictInt = Field(ge=0)
    review_count: StrictInt = Field(ge=0)
    jobs: tuple[CohortJob, ...]
    exclusions: tuple[CohortExclusion, ...]
    input_union: InputUnionProvenance | None = None
    matching_jobs: tuple[MatchingJobInput, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_counts(self) -> "JobCohort":
        if self.status is not CohortStatus.for_size(
            len(self.jobs), self.criteria.min_jobs
        ):
            raise ValueError("cohort status must reflect included jobs and min_jobs")
        if len({job.job_id for job in self.jobs}) != len(self.jobs):
            raise ValueError("cohort job IDs must be unique")
        if self.matching_jobs is not None:
            if self.criteria.purpose is not CohortPurpose.ACTIVE_MATCHING:
                raise ValueError("partial matching inputs require active matching")
            if len({job.job_id for job in self.matching_jobs}) != len(
                self.matching_jobs
            ):
                raise ValueError("partial matching job IDs must be unique")
        if (
            self.input_count
            != len(self.jobs)
            + self.duplicate_count
            + self.excluded_count
            + self.review_count
        ):
            raise ValueError("cohort counts do not reconcile")
        if self.excluded_count != sum(
            item.decision == "EXCLUDED" for item in self.exclusions
        ):
            raise ValueError("excluded_count must equal excluded records")
        if self.review_count != sum(
            item.decision == "REVIEW_REQUIRED" for item in self.exclusions
        ):
            raise ValueError("review_count must equal records requiring review")
        if self.input_union is not None and self.input_count != (
            self.input_union.selected_record_count
            + self.input_union.conflict_record_count
        ):
            raise ValueError(
                "cohort input count must equal union selected observations"
            )
        return self


def _stable_hash(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _record_payload(record: JobPostingInput) -> dict[str, object]:
    # A retry may have a new collection timestamp; actual content and metadata
    # still have to agree. content_hash alone does not cover the whole contract.
    return record.model_dump(mode="json", exclude={"collected_at"})


def _matches_role(record: JobPostingInput, target: str) -> bool:
    categories = re.split(r"[,;|]", record.raw_job_category or "")
    if any(
        _ROLE_LOOKUP.get(category.strip().casefold()) == target
        for category in categories
    ):
        return True
    return (
        re.search(
            # Python의 ``\w``는 한글도 단어 문자로 본다. 그래서 실제 공고에서 흔한
            # ``백엔드개발자``를 경계가 없다고 버렸다. 영문 식별자 내부만 막고,
            # 명시적인 한국어 역할명 뒤에 조사·직책이 붙는 표기는 허용한다.
            rf"(?<![A-Za-z0-9_])(?:{_TITLE_ROLES[target]})(?![A-Za-z0-9_])",
            record.title,
            re.IGNORECASE,
        )
        is not None
    )


def _quality_reasons(
    record: JobPostingInput, criteria: CohortCriteria
) -> tuple[list[str], list[str]]:
    excluded, review = [], []
    if criteria.sources and record.source_site.strip().upper() not in criteria.sources:
        excluded.append("SOURCE_NOT_MATCHED")
    # 역할이 없는 것은 "모든 역할"이다. 시장 Snapshot은 지원 직무에 매칭되지 않는
    # 공고도 같은 기술을 놓고 경쟁하므로 분모에 남긴다.
    if criteria.target_role is not None and not _matches_role(
        record, criteria.target_role
    ):
        excluded.append("ROLE_NOT_MATCHED")
    if record.body_status is not BodyStatus.TEXT_AVAILABLE:
        review.append("BODY_UNAVAILABLE")
    if (
        record.posting_status is PostingStatus.CLOSED
        and criteria.purpose is CohortPurpose.ACTIVE_MATCHING
    ):
        excluded.append("POSTING_CLOSED")
    elif record.posting_status is PostingStatus.UNKNOWN:
        review.append("POSTING_STATUS_UNKNOWN")
    if (
        criteria.purpose is CohortPurpose.ACTIVE_MATCHING
        and record.deadline is not None
        and record.deadline <= criteria.as_of
    ):
        excluded.append("DEADLINE_PASSED")
    if record.collected_at > criteria.as_of:
        excluded.append("COLLECTED_AFTER_AS_OF")
    if record.posted_at is not None and record.posted_at > criteria.as_of:
        excluded.append("POSTED_AFTER_AS_OF")
    if criteria.posted_from or criteria.posted_to:
        if record.posted_at is None:
            review.append("POSTED_AT_UNKNOWN")
        elif (criteria.posted_from and record.posted_at < criteria.posted_from) or (
            criteria.posted_to and record.posted_at >= criteria.posted_to
        ):
            excluded.append("OUTSIDE_POSTED_PERIOD")
    for attribute, allowed, compare in (
        ("region", criteria.regions, match_region),
        ("career_level", criteria.career_levels, match_career_level),
    ):
        if not allowed:
            continue
        result = compare(getattr(record, attribute), allowed)
        if result is FilterMatch.UNKNOWN:
            review.append(f"{attribute.upper()}_UNKNOWN")
        elif result is FilterMatch.NOT_MATCHED:
            excluded.append(f"{attribute.upper()}_NOT_MATCHED")
    return excluded, review


_OR = re.compile(r"\bor\b|또는|혹은|아니면", re.IGNORECASE)
_AND = re.compile(r"\band\b|및|그리고|&|\+", re.IGNORECASE)
_ACTIVITY_CONJUNCTION = re.compile(
    r"(?<!\w)(?:개발\s+및\s+운영|구축\s+및\s+운용|설계\s+및\s+구현)(?!\w)"
)
_UNCERTAIN = re.compile(
    r"없어도|무관|불필요|경험(?:이)?\s*없는|필수(?:\s*(?:가|는|은))?\s*아(?:니|닌|닙|님|닐)\w*|\boptional\b|\bnot\s+(?:required|necessary|needed|(?:a\s+)?requirement)\b|예시|예를|\betc\b|등(?=\s|[,.]|$|[을의])|(?:(?<!\d)(?:[2-9]|[1-9]\d+)\s*(?:개|가지)|(?:두|둘|세|셋|네|넷)\s*(?:개|가지))\s*이상",
    re.IGNORECASE,
)
_ONE_OF = re.compile(r"중\s*(?:하나|1개)|\b(?:one|any)\s+of\b", re.IGNORECASE)
_ONE_OF_PRELUDE = re.compile(
    r"(?:[-*•]\s*)?(?:(?:one|any)\s+of\s+(?:the\s+)?following"
    r"|(?:다음|아래)\s*(?:기술|항목)?\s*중\s*(?:하나|1개))\s*[:：]?",
    re.IGNORECASE,
)


def _required_clauses(
    record: JobPostingInput, classified: JobClassificationRecord
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    if any(
        item.requirement_class is RequirementClass.REVIEW_REQUIRED
        for item in classified.technologies
    ):
        return (), ("TECHNOLOGY_REVIEW_REQUIRED",)
    required = [
        item
        for item in classified.technologies
        if item.requirement_class is RequirementClass.REQUIRED
    ]
    if not required:
        return (), ("NO_REQUIRED_TECHNOLOGY",)
    groups: defaultdict[tuple[str, int, int], list[TechnologyClassification]] = (
        defaultdict(list)
    )
    for item in required:
        surface = (
            record.title
            if item.location.source_surface.value == "TITLE"
            else record.description_text
        )
        start, end = item.location.char_start, item.location.char_end
        if surface is not None and start is None:
            # Repeated A-side mentions can exhaust the classifier's occurrence
            # cursor. Reuse an identical located mention, retaining both traces.
            duplicate = next(
                (
                    other
                    for other in required
                    if other.raw_technology == item.raw_technology
                    and other.evidence_text == item.evidence_text
                    and other.location.source_surface == item.location.source_surface
                    and other.location.char_start is not None
                ),
                None,
            )
            if duplicate is not None:
                start, end = duplicate.location.char_start, duplicate.location.char_end
        if surface is None or start is None or end is None:
            return (), ("EVIDENCE_NOT_LOCATED",)
        line_start = surface.rfind("\n", 0, start) + 1
        previous_line = next(
            (
                line.strip()
                for line in reversed(surface[:line_start].splitlines())
                if line.strip()
            ),
            "",
        )
        if _ONE_OF_PRELUDE.fullmatch(previous_line):
            # Word-only A evidence can omit the selection scope above a list.
            # Do not interpret those separate alternatives as required ANDs.
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        line_end = surface.find("\n", end)
        line_end = len(surface) if line_end < 0 else line_end
        line = surface[line_start:line_end]
        if "\n" in line:
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        groups[(line, line_start, line_end)].append(item)
    clauses: set[tuple[str, ...]] = set()
    for (text, _, _), items in groups.items():
        if _UNCERTAIN.search(text):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        # Resolve operators on the original line, even if A extracted each word
        # as its own evidence_text. Never turn slash or mixed logic into AND.
        spans = []
        for item in items:
            pattern = (
                rf"(?<![A-Za-z0-9]){re.escape(item.raw_technology)}(?![A-Za-z0-9])"
            )
            for match in re.finditer(pattern, text, re.IGNORECASE):
                spans.append((match.start(), match.end(), item.tech_id))
        spans = sorted(set(spans))
        if not spans or any(left[1] > right[0] for left, right in pairwise(spans)):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        # Mask technology text so C++ and Node.js do not become operators.
        masked = text
        for start, end, _ in reversed(spans):
            masked = masked[:start] + " " * (end - start) + masked[end:]
        # An AND between these observed activity nouns is not a missing tech
        # operand. Preserve offsets and leave every other AND unresolved.
        for activity in _ACTIVITY_CONJUNCTION.finditer(text):
            start, end = activity.span()
            masked = masked[:start] + " " * (end - start) + masked[end:]
        if "/" in masked:
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        if _AND.search(masked[: spans[0][0]]) or _AND.search(masked[spans[-1][1] :]):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        if any(
            _AND.search(masked[left[1] : right[0]])
            and re.fullmatch(
                r"\s*(?:and|및|그리고|&|\+|,|\s)+",
                masked[left[1] : right[0]],
                re.IGNORECASE,
            )
            is None
            for left, right in pairwise(spans)
        ):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        if re.search(r",\s*$", masked[: spans[0][0]]) or re.match(
            r"\s*,", masked[spans[-1][1] :]
        ):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        if any(
            "," in masked[left[1] : right[0]]
            and re.search(r"[A-Za-z]", masked[left[1] : right[0]])
            and re.fullmatch(
                r"\s*(?:,|and|or|및|또는|혹은|아니면|\s)+",
                masked[left[1] : right[0]],
                re.IGNORECASE,
            )
            is None
            for left, right in pairwise(spans)
        ):
            return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
        is_or = bool(_OR.search(masked) or _ONE_OF.search(masked))
        if is_or:
            if len(spans) < 2 or _AND.search(masked):
                return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
            prefix, suffix = masked[: spans[0][0]], masked[spans[-1][1] :]
            if _OR.search(prefix) or _OR.search(suffix):
                return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
            for left, right in pairwise(spans):
                connector = masked[left[1] : right[0]].strip()
                allowed = (
                    r"(?:또는|혹은|아니면|or)"
                    if not _ONE_OF.search(masked)
                    else r"(?:또는|혹은|아니면|or|,)"
                )
                if re.fullmatch(allowed, connector, re.IGNORECASE) is None:
                    return (), ("REQUIREMENT_LOGIC_UNRESOLVED",)
            clauses.add(tuple(sorted({item.tech_id for item in items if item.tech_id})))
        else:
            clauses.update((item.tech_id,) for item in items if item.tech_id)
    return tuple(sorted(clauses)), ()


def _matching_required_clauses(
    requirements: JobRequirements,
    classification: JobClassificationRecord,
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Use the matching payload as the active strict cohort source of truth."""

    unresolved = tuple(
        item
        for item in requirements.unresolved
        if item.requirement_kind is RequirementKind.REQUIRED
    )
    if unresolved:
        reason = (
            "TECHNOLOGY_REVIEW_REQUIRED"
            if any(
                item.requirement_class is RequirementClass.REVIEW_REQUIRED
                and item.input_requirement_type.value == "REQUIRED"
                for item in classification.technologies
            )
            else "REQUIREMENT_LOGIC_UNRESOLVED"
        )
        return (), (reason,)
    clauses = tuple(clause.tech_ids for clause in requirements.required)
    if not clauses:
        return (), ("NO_REQUIRED_TECHNOLOGY",)
    if any(
        item.requirement_class is RequirementClass.REVIEW_REQUIRED
        and item.input_requirement_type.value == "MENTIONED"
        for item in classification.technologies
    ):
        return clauses, ("TECHNOLOGY_REVIEW_REQUIRED",)
    return clauses, ()


def _served_technologies(
    technologies: tuple[TechnologyClassification, ...],
) -> tuple[TechnologyClassification, ...]:
    """Cohort에 실을 사본. 분류 근거는 두고 전체 문맥만 비운다 · 티켓 S15P21E102-333.

    `mapping_context`는 `title + evidence_section + evidence_text + description_text`라
    mention 하나마다 본문이 한 벌씩 붙는다. 공고당 평균 2.5개 mention이므로 같은 본문이
    두세 벌씩 snapshot에 쌓이고, 2026-09-18 실측에서 COHORT payload의 66.4%였다.

    비워도 잃는 것이 없다. 남는 셋(`title`·`evidence_section`·`evidence_text`)은 이미
    같은 객체의 별도 필드이고, 빠지는 `description_text`는 바로 위 `CohortExclusion`이
    `exclude={"description_text", ...}`로 이미 뺀 값이다. 그 본문은 HDFS
    `analysis_input`에 불변으로 남아 있어 `classify_job_batch`를 다시 돌리면 같은 문맥이
    바이트 단위로 재생성된다.

    값이 필요한 두 소비자는 이 사본을 보지 않는다. `registry.mapper`는 분류 도중
    메모리의 원본을 받고, `registry.review`는 `worker.jobs.job_review_records`가 따로
    돌린 분류 결과로 `registry_review.record.context`를 만든다.

    빈 문자열로 두는 이유는 필드를 지울 수 없기 때문이다. `TechnologyClassification`이
    `extra="forbid"`라 필드를 없애면 이미 저장된 snapshot을 다시 읽지 못한다. 대신
    `exclude_if`가 빈 값을 직렬화에서 빼므로 payload에는 키 자체가 남지 않는다.
    """

    return tuple(
        technology.model_copy(update={"mapping_context": ""})
        for technology in technologies
    )


def build_cohort(
    batch: JobAnalysisInputBatch,
    criteria: CohortCriteria,
    mapper: RegistryMapper | None = None,
    *,
    qualify_job_ids: bool = False,
) -> JobCohort:
    """Apply quality, exact filters, retry deduplication and conservative logic.

    This pure operation performs no fetch or review-store write. Unresolved
    classifications retain all mapping attempts so callers can enqueue review.
    """
    criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
    prepared = prepare_cohort_batch(
        batch,
        mapper,
        qualify_job_ids=qualify_job_ids,
        include_active_requirements=(
            criteria.purpose is CohortPurpose.ACTIVE_MATCHING
        ),
    )
    return build_cohort_from_prepared(prepared, criteria)


@dataclass(frozen=True)
class PreparedCohortRecord:
    digest: str
    record: JobPostingInput
    classification: JobClassificationRecord
    requirements: JobRequirements | None


@dataclass(frozen=True)
class PreparedCohortBatch:
    """Criteria-independent parsing reused by live selector projections."""

    batch: JobAnalysisInputBatch
    classified: JobClassificationBatch
    records: tuple[PreparedCohortRecord, ...]
    conflicts: frozenset[str]
    qualify_job_ids: bool
    input_count: int


def prepare_cohort_batch(
    batch: JobAnalysisInputBatch,
    mapper: RegistryMapper | None = None,
    *,
    qualify_job_ids: bool = False,
    include_active_requirements: bool = False,
) -> PreparedCohortBatch:
    """Classify, deduplicate and optionally parse requirements exactly once."""

    if mapper is None:
        ai_root = Path(__file__).resolve().parents[1]
        mapper = RegistryMapper(
            load_registry(
                ai_root / "registry/data/technology_registry_v1.json",
                repository_root=ai_root.parent,
            )
        )
    classified = classify_job_batch(batch, mapper)
    # Group only exact contract duplicates. Changed content on the same source
    # identity is reviewed; canonical_job_id never authorizes a collapse.
    unique: dict[str, tuple[JobPostingInput, JobClassificationRecord]] = {}
    for record, classification in zip(batch.records, classified.records, strict=True):
        digest = _stable_hash(_record_payload(record))
        existing = unique.get(digest)
        if existing is None or record.collected_at < existing[0].collected_at:
            unique[digest] = (record, classification)
    source_groups: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    id_groups: defaultdict[str | tuple[str, str], list[str]] = defaultdict(list)
    for digest, (record, _) in unique.items():
        source_groups[(record.source_site.upper(), record.source_posting_id)].append(
            digest
        )
        id_key = (
            (record.source_site.strip().upper(), record.source_record_id)
            if qualify_job_ids
            else record.source_record_id
        )
        id_groups[id_key].append(digest)
    conflicts = {
        digest
        for group in (*source_groups.values(), *id_groups.values())
        if len(group) > 1
        for digest in group
    }
    prepared_records = []
    for digest, (record, classification) in sorted(
        unique.items(), key=lambda pair: (pair[1][0].source_record_id, pair[0])
    ):
        requirements = (
            extract_job_requirements(record, classification)
            if include_active_requirements
            else None
        )
        # Once active requirements and evidence locations are parsed, selector
        # filtering never reads the raw body or source mentions again. Keep a
        # compact immutable record so the warm projection does not duplicate
        # thousands of full job descriptions already held by verified outputs.
        stored_record = (
            record.model_copy(
                update={
                    "description_text": (
                        "prepared" if record.body_status is BodyStatus.TEXT_AVAILABLE else None
                    ),
                    "technology_mentions": (),
                }
            )
            if include_active_requirements
            else record
        )
        prepared_records.append(
            PreparedCohortRecord(
                digest=digest,
                record=stored_record,
                classification=classification,
                requirements=requirements,
            )
        )
    records = tuple(prepared_records)
    prepared_batch = (
        batch.model_copy(update={"records": tuple(item.record for item in records)})
        if include_active_requirements
        else batch
    )
    return PreparedCohortBatch(
        batch=prepared_batch,
        classified=classified,
        records=records,
        conflicts=frozenset(conflicts),
        qualify_job_ids=qualify_job_ids,
        input_count=len(batch.records),
    )


def build_cohort_from_prepared(
    prepared: PreparedCohortBatch, criteria: CohortCriteria
) -> JobCohort:
    """Apply selector-specific filters without classification or requirement parsing."""

    criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
    batch = prepared.batch
    classified = prepared.classified
    jobs, exclusions, matching_jobs = [], [], []
    for item in prepared.records:
        digest = item.digest
        record = item.record
        classification = item.classification
        excluded, review = _quality_reasons(record, criteria)
        requirements = (
            item.requirements
            if item.requirements is not None
            else extract_job_requirements(record, classification)
            if criteria.purpose is CohortPurpose.ACTIVE_MATCHING
            else None
        )
        clauses, logic_reasons = (
            _matching_required_clauses(requirements, classification)
            if requirements is not None
            else _required_clauses(record, classification)
        )
        review.extend(logic_reasons)
        if digest in prepared.conflicts:
            review.append("SOURCE_RECORD_CONFLICT")
        if (
            criteria.purpose is CohortPurpose.ACTIVE_MATCHING
            and not excluded
            and not {"BODY_UNAVAILABLE", "SOURCE_RECORD_CONFLICT"}.intersection(review)
        ):
            assert requirements is not None
            conditional = tuple(
                sorted(
                    set(review).intersection(
                        {
                            "POSTING_STATUS_UNKNOWN",
                            "REGION_UNKNOWN",
                            "CAREER_LEVEL_UNKNOWN",
                            "POSTED_AT_UNKNOWN",
                        }
                    )
                )
            )
            matching_jobs.append(
                MatchingJobInput(
                    job_id=(
                        f"{record.source_site.strip().upper()}:{record.source_posting_id}"
                        if prepared.qualify_job_ids
                        else record.source_record_id
                    ),
                    source_record_id=record.source_record_id,
                    source_site=record.source_site,
                    source_posting_id=record.source_posting_id,
                    source_url=record.source_url,
                    company_name=record.company_name,
                    title=record.title,
                    region=record.region,
                    career_level=record.career_level,
                    deadline=record.deadline,
                    collected_at=record.collected_at,
                    content_hash=record.content_hash,
                    eligibility="CONDITIONAL" if conditional else "ELIGIBLE",
                    eligibility_reasons=conditional,
                    strict_match_eligible=not review,
                    strict_review_reasons=tuple(sorted(set(review))),
                    requirements=requirements,
                )
            )
        if excluded or review:
            exclusions.append(
                CohortExclusion(
                    **record.model_dump(
                        exclude={"description_text", "technology_mentions"}
                    ),
                    decision="EXCLUDED" if excluded else "REVIEW_REQUIRED",
                    reasons=tuple(sorted(set(excluded + review))),
                    technologies=_served_technologies(classification.technologies),
                )
            )
            continue
        fields = record.model_dump(
            exclude={
                "description_text",
                "body_status",
                "posting_status",
                "technology_mentions",
            }
        )
        if criteria.purpose is CohortPurpose.MONTHLY_DEMAND:
            fields["posting_status"] = record.posting_status
        jobs.append(
            CohortJob(
                **fields,
                job_id=(
                    f"{record.source_site.strip().upper()}:{record.source_posting_id}"
                    if prepared.qualify_job_ids
                    else record.source_record_id
                ),
                required_clauses=clauses,
                levelled_required_clauses=(
                    requirements.required
                    if criteria.purpose is CohortPurpose.ACTIVE_MATCHING
                    and tuple(
                        sorted(clause.tech_ids for clause in requirements.required)
                    )
                    == clauses
                    else None
                ),
                preferred_tech_ids=tuple(
                    sorted(
                        {
                            item.tech_id
                            for item in classification.technologies
                            if item.requirement_class is RequirementClass.PREFERRED
                            and item.tech_id
                        }
                    )
                ),
                general_tech_ids=tuple(
                    sorted(
                        {
                            item.tech_id
                            for item in classification.technologies
                            if item.requirement_class is RequirementClass.SKILL
                            and item.tech_id
                        }
                    )
                ),
                technologies=_served_technologies(classification.technologies),
            )
        )
    status = CohortStatus.for_size(len(jobs), criteria.min_jobs)
    identity = {
        "criteria": criteria.model_dump(mode="json"),
        "input_digests": sorted(item.digest for item in prepared.records),
        "collected_at": {
            item.digest: item.record.collected_at.astimezone(UTC).isoformat()
            for item in prepared.records
        },
        "dataset_snapshot_id": batch.dataset_snapshot_id,
        "pipeline_run_id": batch.pipeline_run_id,
        "collector_version": batch.collector_version,
        "registry_version": classified.registry_version,
        "parser_version": classified.parser_version,
        "quality_version": JOB_QUALITY_VERSION,
        "requirements_version": JOB_REQUIREMENTS_SCHEMA_VERSION,
    }
    if prepared.qualify_job_ids:
        identity["job_id_policy"] = "source-site-posting/v1"
    return JobCohort(
        cohort_id=f"cohort-{_stable_hash(identity)}",
        status=status,
        criteria=criteria,
        dataset_snapshot_id=batch.dataset_snapshot_id,
        pipeline_run_id=batch.pipeline_run_id,
        collector_version=batch.collector_version,
        registry_version=classified.registry_version,
        parser_version=classified.parser_version,
        input_count=prepared.input_count,
        duplicate_count=prepared.input_count - len(prepared.records),
        excluded_count=sum(item.decision == "EXCLUDED" for item in exclusions),
        review_count=sum(item.decision == "REVIEW_REQUIRED" for item in exclusions),
        jobs=tuple(jobs),
        exclusions=tuple(exclusions),
        matching_jobs=(
            tuple(sorted(matching_jobs, key=lambda item: item.job_id))
            if criteria.purpose is CohortPurpose.ACTIVE_MATCHING
            else None
        ),
    )
