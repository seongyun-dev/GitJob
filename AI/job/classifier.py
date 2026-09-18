"""C-team job requirement classification over the immutable A-to-C contract."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictInt,
    StrictStr,
    field_validator,
)
from registry.mapper import (
    MapperInput,
    MapperResult,
    MapperSource,
    MatchEvidence,
    MatchStatus,
    RegistryMapper,
)

from job.contracts import (
    BodyStatus,
    ContentHash,
    JobAnalysisInputBatch,
    PostingStatus,
    RequirementType,
    SourceSurface,
    TechnologyMentionInput,
)

JOB_CLASSIFICATION_SCHEMA_VERSION = "job-technology-classification/v1"
JOB_REQUIREMENT_PARSER_VERSION = "job-requirement-rules/v8"
_ISO_8601_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]")


class RequirementClass(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    SKILL = "SKILL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ClassificationLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_surface: SourceSurface
    char_start: StrictInt | None
    char_end: StrictInt | None


class TechnologyClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mention_index: StrictInt = Field(ge=0)
    raw_technology: StrictStr
    source_technology_id: StrictStr | None
    tech_id: StrictStr | None
    match_status: MatchStatus
    candidates: tuple[StrictStr, ...]
    requirement_class: RequirementClass
    input_requirement_type: RequirementType
    evidence_section: StrictStr | None
    parsed_section: StrictStr | None
    evidence_text: StrictStr
    # 분류 도중에만 필요한 전체 문맥 · 티켓 S15P21E102-333.
    #
    # 두 곳이 이 값을 쓴다. `registry.mapper`가 짧은 언어명(`c`·`r`·`go`)을 가릴 때 보고,
    # `registry.review`가 사람이 검토할 근거로 `registry_review.record.context`에 남긴다.
    # 둘 다 분류 단계에서 끝난다. 서빙은 읽지 않는다 — BE의 어떤 DTO도
    # `jobs[].technologies`를 선언하지 않아 Jackson이 통째로 버리고 FE에는 참조가 없다.
    #
    # 그런데 mention 하나마다 본문이 한 벌씩 붙으므로, 공고당 평균 2.5벌이 snapshot에
    # 쌓인다. 2026-09-18 운영 실측에서 COHORT payload의 66.4%가 이 값이었다. 그래서
    # `build_cohort`가 cohort에 싣는 사본에서만 비우고, 비면 직렬화에서 빠진다.
    #
    # 필드를 없애지 않는 이유는 기존 snapshot 때문이다. 이 모델은 `extra="forbid"`이고
    # `worker.api`가 과거 payload를 그대로 `model_validate`하므로, 필드가 사라지면 이미
    # 저장된 COHORT·RECOMMENDATION을 다시 읽을 수 없다.
    mapping_context: StrictStr = Field(default="", exclude_if=lambda value: not value)
    location: ClassificationLocation
    mapping_attempts: tuple[MapperResult, ...]
    mapping_evidence: MatchEvidence
    registry_version: StrictStr
    parser_version: StrictStr
    classification_reason: StrictStr


class JobClassificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: StrictStr
    canonical_job_id: StrictStr | None
    source_site: StrictStr
    source_posting_id: StrictStr
    source_url: HttpUrl
    company_name: StrictStr
    title: StrictStr
    raw_job_category: StrictStr | None
    career_level: StrictStr | None
    region: StrictStr | None
    body_status: BodyStatus
    posting_status: PostingStatus
    posted_at: datetime | None
    deadline: datetime | None
    collected_at: datetime
    content_hash: ContentHash
    technologies: tuple[TechnologyClassification, ...]

    @field_validator("collected_at", "posted_at", "deadline", mode="before")
    @classmethod
    def require_iso_datetime_input(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _ISO_8601_DATETIME_PATTERN.match(value):
            raise ValueError("timestamp must be an ISO 8601 date-time string")
        return value

    @field_validator("collected_at", "posted_at", "deadline")
    @classmethod
    def require_timezone_when_present(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class JobClassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["job-technology-classification/v1"]
    input_schema_version: Literal["job-analysis-input/v1"]
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    registry_version: StrictStr
    parser_version: StrictStr
    records: tuple[JobClassificationRecord, ...]


_REQUIRED_SECTION_MARKERS = (
    "자격요건",
    "자격 요건",
    "지원자격",
    "요구사항",
    "필수",
    "requirements",
    "required",
)

_RESPONSIBILITY_HEADINGS = frozenset(
    {"담당업무", "주요업무", "업무내용", "직무내용", "responsibilities"}
)
_TERMINATING_SECTION_HEADINGS = frozenset(
    {"회사소개", "기업소개", "company", "aboutus"}
)

_SECTION_HEADINGS = {
    "자격요건": RequirementClass.REQUIRED,
    "지원자격": RequirementClass.REQUIRED,
    "필수": RequirementClass.REQUIRED,
    "필수사항": RequirementClass.REQUIRED,
    "필수역량": RequirementClass.REQUIRED,
    "요구사항": RequirementClass.REQUIRED,
    "requirements": RequirementClass.REQUIRED,
    "required": RequirementClass.REQUIRED,
    "스킬": RequirementClass.SKILL,
    "우대": RequirementClass.PREFERRED,
    "우대사항": RequirementClass.PREFERRED,
    "우대조건": RequirementClass.PREFERRED,
    "우대자격요건": RequirementClass.PREFERRED,
    "preferred": RequirementClass.PREFERRED,
    "nicetohave": RequirementClass.PREFERRED,
    **dict.fromkeys(_RESPONSIBILITY_HEADINGS, RequirementClass.REQUIRED),
    "기술스택": RequirementClass.SKILL,
    "사용기술": RequirementClass.SKILL,
    "복리후생": RequirementClass.SKILL,
    "근무조건": RequirementClass.SKILL,
    "채용절차": RequirementClass.SKILL,
    "benefits": RequirementClass.SKILL,
}

_REQUIREMENT_NEGATION = re.compile(
    r"필수(?:\s*(?:가|는|은))?\s*아(?:니|닌|닙|님|닐)\w*",
    re.IGNORECASE,
)
_TECHNOLOGY_MINIMUM_COUNT = re.compile(
    r"(?:(?<!\d)(?:[2-9]|[1-9]\d+)\s*(?:개|가지)|(?:두|둘|세|셋|네|넷)\s*(?:개|가지))\s*이상"
)


def _heading_key(value: str) -> str:
    label = value.casefold().strip().strip("[]()#*•ㆍ-:：")
    # These decorations occur on the saved public job pages. Remove only
    # leading list markers; the remaining label must still be an exact heading.
    label = re.sub(r"^(?:(?:[0-9]{1,2}[.)]|[📋🏠🎁🚀])\s*)+", "", label)
    return "".join(label.split()).strip("[]()#*•ㆍ-:：")


def _parse_section(text: str | None, location: ClassificationLocation) -> str | None:
    if (
        text is None
        or location.source_surface is not SourceSurface.BODY
        or location.char_start is None
    ):
        return None
    current_section = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset > location.char_start:
            break
        # Only complete headings or a heading followed by a colon establish
        # a boundary; a requirement word inside prose must not become one.
        label = re.split(r"[:：]", line.strip(), maxsplit=1)[0].strip()
        if _heading_key(label) in (
            set(_SECTION_HEADINGS) | _TERMINATING_SECTION_HEADINGS
        ):
            current_section = label
        offset += len(line)
    return current_section


_PREFERRED_SECTION_MARKERS = (
    "우대",
    "preferred",
    "nice to have",
)

_COLLECTOR_SPELLING_DISPLAY = {
    "c": "C",
    "springboot": "Spring Boot",
    "html5": "HTML",
    "css3": "CSS",
    "nodejs": "Node.js",
    "react.js": "React",
    "reactjs": "React",
    "nest.js": "NestJS",
    "nestjs": "NestJS",
    "nextjs": "Next.js",
}


def _section_requirement(section: str | None) -> RequirementClass | None:
    if section is None:
        return None
    heading_requirement = _SECTION_HEADINGS.get(_heading_key(section))
    if heading_requirement is not None:
        return heading_requirement
    normalized = " ".join(section.casefold().split())
    if any(marker in normalized for marker in _PREFERRED_SECTION_MARKERS):
        return RequirementClass.PREFERRED
    if any(marker in normalized for marker in _REQUIRED_SECTION_MARKERS):
        return RequirementClass.REQUIRED
    return None


def _classify_requirement(
    mention: TechnologyMentionInput,
    match_status: MatchStatus,
    parsed_section: str | None,
) -> tuple[RequirementClass, str]:
    if match_status is not MatchStatus.MATCHED:
        return (
            RequirementClass.REVIEW_REQUIRED,
            "Registry mapping requires review",
        )
    parsed_section_key = _heading_key(parsed_section or "")
    if parsed_section_key in _TERMINATING_SECTION_HEADINGS:
        # A located company section outranks carried source requirement labels.
        # The original A fields remain in TechnologyClassification provenance.
        return RequirementClass.SKILL, "company introduction is not a requirement"
    if _REQUIREMENT_NEGATION.search(mention.evidence_text):
        return RequirementClass.REVIEW_REQUIRED, "requirement negation requires review"
    if _TECHNOLOGY_MINIMUM_COUNT.search(mention.evidence_text):
        return (
            RequirementClass.REVIEW_REQUIRED,
            "technology count requirement requires review",
        )

    # Located body headings take precedence for the agreed duties policy.
    # A source label is a fallback only when no body heading was located.
    responsibility_section = parsed_section or mention.evidence_section
    if (
        mention.source_surface is SourceSurface.BODY
        and responsibility_section is not None
        and _heading_key(responsibility_section) in _RESPONSIBILITY_HEADINGS
    ):
        return RequirementClass.REQUIRED, "responsibilities treated as required"

    section_requirement = _section_requirement(mention.evidence_section)
    # Unknown extractor labels must not hide a section found at the evidence
    # offset. Keep recognized source labels, except for the duties policy above.
    if parsed_section is not None and (
        section_requirement is None
        or _heading_key(mention.evidence_section or "") == _heading_key(parsed_section)
    ):
        section_requirement = _SECTION_HEADINGS.get(parsed_section_key)
    input_requirement = {
        RequirementType.REQUIRED: RequirementClass.REQUIRED,
        RequirementType.PREFERRED: RequirementClass.PREFERRED,
        RequirementType.MENTIONED: RequirementClass.SKILL,
    }[mention.requirement_type]

    if (
        mention.requirement_type is not RequirementType.MENTIONED
        and section_requirement is not None
        and section_requirement is not input_requirement
    ):
        return (
            RequirementClass.REVIEW_REQUIRED,
            "input requirement conflicts with section",
        )
    if (
        mention.requirement_type is RequirementType.MENTIONED
        and section_requirement is not None
    ):
        return section_requirement, "section boundary supplied requirement"
    return input_requirement, "input requirement retained"


def _locate_evidence(
    mention: TechnologyMentionInput,
    *,
    title: str,
    description_text: str | None,
    start_at: int,
) -> ClassificationLocation:
    surface_text = (
        title if mention.source_surface is SourceSurface.TITLE else description_text
    )
    start = (
        surface_text.find(mention.evidence_text, start_at)
        if surface_text is not None
        else -1
    )
    return ClassificationLocation(
        source_surface=mention.source_surface,
        char_start=start if start >= 0 else None,
        char_end=start + len(mention.evidence_text) if start >= 0 else None,
    )


def _map_job_mention(
    mention: TechnologyMentionInput,
    *,
    context: str,
    mapper: RegistryMapper,
) -> tuple[MapperResult, tuple[MapperResult, ...]]:
    result = mapper.map(
        MapperInput(
            source=MapperSource.ALIAS,
            raw_value=mention.raw_technology,
            context=context,
        )
    )
    attempts = [result]
    if result.status is MatchStatus.UNKNOWN:
        result = mapper.map(
            MapperInput(
                source=MapperSource.DISPLAY_NAME,
                raw_value=mention.raw_technology,
                context=context,
            )
        )
        attempts.append(result)
    canonical_display = _COLLECTOR_SPELLING_DISPLAY.get(
        "".join(mention.raw_technology.casefold().split()).strip("*•ㆍ·-")
    )
    if result.status is MatchStatus.UNKNOWN and canonical_display is not None:
        result = mapper.map(
            MapperInput(
                source=MapperSource.DISPLAY_NAME,
                raw_value=canonical_display,
                context=context.replace(mention.raw_technology, canonical_display),
            )
        )
        attempts.append(result)
    return result, tuple(attempts)


def _mapping_context(
    mention: TechnologyMentionInput,
    *,
    title: str,
    description_text: str | None,
) -> str:
    return "\n".join(
        part
        for part in (
            title,
            mention.evidence_section,
            mention.evidence_text,
            description_text,
        )
        if part
    )


def classify_job_batch(
    batch: JobAnalysisInputBatch,
    mapper: RegistryMapper,
) -> JobClassificationBatch:
    """Classify every mention without mutating or collapsing the source contract."""

    output_records = []
    for record in batch.records:
        technologies = []
        evidence_search_starts: dict[tuple[SourceSurface, str, str], int] = {}
        for mention_index, mention in enumerate(record.technology_mentions):
            mapping_context = _mapping_context(
                mention,
                title=record.title,
                description_text=record.description_text,
            )
            mapping, mapping_attempts = _map_job_mention(
                mention,
                context=mapping_context,
                mapper=mapper,
            )
            evidence_key = (
                mention.source_surface,
                mention.evidence_text,
                mention.raw_technology.casefold(),
            )
            location = _locate_evidence(
                mention,
                title=record.title,
                description_text=record.description_text,
                start_at=evidence_search_starts.get(evidence_key, 0),
            )
            if location.char_end is not None:
                evidence_search_starts[evidence_key] = location.char_end
            parsed_section = _parse_section(record.description_text, location)
            requirement_class, reason = _classify_requirement(
                mention,
                mapping.status,
                parsed_section,
            )
            technologies.append(
                TechnologyClassification(
                    mention_index=mention_index,
                    raw_technology=mention.raw_technology,
                    source_technology_id=mention.source_technology_id,
                    tech_id=mapping.tech_id,
                    match_status=mapping.status,
                    candidates=mapping.candidates,
                    requirement_class=requirement_class,
                    input_requirement_type=mention.requirement_type,
                    evidence_section=mention.evidence_section,
                    parsed_section=parsed_section,
                    evidence_text=mention.evidence_text,
                    mapping_context=mapping_context,
                    location=location,
                    mapping_attempts=mapping_attempts,
                    mapping_evidence=mapping.evidence,
                    registry_version=mapping.registry_version,
                    parser_version=JOB_REQUIREMENT_PARSER_VERSION,
                    classification_reason=reason,
                )
            )
        output_records.append(
            JobClassificationRecord(
                source_record_id=record.source_record_id,
                canonical_job_id=record.canonical_job_id,
                source_site=record.source_site,
                source_posting_id=record.source_posting_id,
                source_url=record.source_url,
                company_name=record.company_name,
                title=record.title,
                raw_job_category=record.raw_job_category,
                career_level=record.career_level,
                region=record.region,
                body_status=record.body_status,
                posting_status=record.posting_status,
                posted_at=record.posted_at,
                deadline=record.deadline,
                collected_at=record.collected_at,
                content_hash=record.content_hash,
                technologies=tuple(technologies),
            )
        )

    return JobClassificationBatch(
        schema_version=JOB_CLASSIFICATION_SCHEMA_VERSION,
        input_schema_version=batch.schema_version,
        dataset_snapshot_id=batch.dataset_snapshot_id,
        pipeline_run_id=batch.pipeline_run_id,
        collector_version=batch.collector_version,
        registry_version=mapper.registry_version,
        parser_version=JOB_REQUIREMENT_PARSER_VERSION,
        records=tuple(output_records),
    )
