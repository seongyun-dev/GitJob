"""Conservative, source-grounded job requirement clause extraction."""

import re
from collections import defaultdict
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from registry.contracts import TechId
from registry.mapper import MatchStatus

from job.classifier import (
    JOB_REQUIREMENT_PARSER_VERSION,
    JobClassificationRecord,
    RequirementClass,
    TechnologyClassification,
)
from job.contracts import (
    ContentHash,
    JobPostingInput,
    RequirementType,
    SourceSurface,
)

JOB_REQUIREMENTS_SCHEMA_VERSION = "job-requirements/v2"
JOB_REQUIREMENTS_LEGACY_SCHEMA_VERSION = "job-requirements/v1"
JOB_REQUIRED_LEVEL_POLICY_VERSION = "job-required-level-policy/v2"


class RequirementKind(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class RequirementOperator(StrEnum):
    """A clause is satisfied by any one positive technology operand.

    Conjunction is represented as multiple independent clauses instead of a
    second operator nested inside a clause.
    """

    ANY_OF = "ANY_OF"


class RequirementLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class RequirementLevelEvidenceSource(StrEnum):
    DIRECT_CLAUSE = "DIRECT_CLAUSE"
    CONSERVATIVE_DEFAULT = "CONSERVATIVE_DEFAULT"


class UnresolvedReason(StrEnum):
    TECHNOLOGY_MAPPING_UNRESOLVED = "TECHNOLOGY_MAPPING_UNRESOLVED"
    EVIDENCE_NOT_LOCATED = "EVIDENCE_NOT_LOCATED"
    NEGATION_UNSUPPORTED = "NEGATION_UNSUPPORTED"
    CARDINALITY_UNSUPPORTED = "CARDINALITY_UNSUPPORTED"
    LOGIC_UNSUPPORTED = "LOGIC_UNSUPPORTED"


class RequirementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequirementEvidence(RequirementModel):
    source_surface: SourceSurface
    char_start: StrictInt | None
    char_end: StrictInt | None
    text: StrictStr
    mention_indices: tuple[StrictInt, ...] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence text must not be blank")
        return value

    @field_validator("mention_indices")
    @classmethod
    def canonicalize_mention_indices(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 for value in values):
            raise ValueError("mention indices must be non-negative")
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_location_pair(self) -> "RequirementEvidence":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("evidence offsets must both be present or both be absent")
        if self.char_start is not None and (
            self.char_start < 0 or self.char_end <= self.char_start
        ):
            raise ValueError("evidence offsets must describe a non-empty range")
        return self


class RequirementLevelEvidence(RequirementModel):
    source: RequirementLevelEvidenceSource
    level: RequirementLevel
    text: StrictStr
    source_surface: SourceSurface | None = None
    char_start: StrictInt | None = None
    char_end: StrictInt | None = None
    mention_indices: tuple[StrictInt, ...] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("level evidence text must not be blank")
        return value

    @field_validator("mention_indices")
    @classmethod
    def canonicalize_mention_indices(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 for value in values):
            raise ValueError("mention indices must be non-negative")
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_location(self) -> "RequirementLevelEvidence":
        located = self.source in {
            RequirementLevelEvidenceSource.DIRECT_CLAUSE,
        }
        if located != (self.source_surface is not None):
            raise ValueError("located level evidence requires a source surface")
        if located != (self.char_start is not None and self.char_end is not None):
            raise ValueError("located level evidence requires offsets")
        if self.char_start is not None and (
            self.char_start < 0 or self.char_end <= self.char_start
        ):
            raise ValueError("level evidence offsets must describe a non-empty range")
        return self


class RequirementClause(RequirementModel):
    operator: RequirementOperator = RequirementOperator.ANY_OF
    tech_ids: tuple[TechId, ...] = Field(min_length=1)
    evidence_refs: tuple[RequirementEvidence, ...] = Field(min_length=1)
    required_level: RequirementLevel | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    level_evidence_refs: tuple[RequirementLevelEvidence, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @field_validator("tech_ids")
    @classmethod
    def canonicalize_tech_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_level_evidence(self) -> "RequirementClause":
        if (self.required_level is None) != (not self.level_evidence_refs):
            raise ValueError("required level and level evidence must appear together")
        if self.required_level is None:
            return self
        evidence_level = max(
            (item.level for item in self.level_evidence_refs),
            key=lambda level: {"L1": 1, "L2": 2, "L3": 3}[level.value],
        )
        if self.required_level is not evidence_level:
            raise ValueError("required level must equal the strongest level evidence")
        clause_mentions = {
            index
            for evidence in self.evidence_refs
            for index in evidence.mention_indices
        }
        if any(
            not set(evidence.mention_indices).issubset(clause_mentions)
            for evidence in self.level_evidence_refs
        ):
            raise ValueError("level evidence mention lineage must belong to the clause")
        return self


class UnresolvedRequirement(RequirementModel):
    requirement_kind: RequirementKind
    reason: UnresolvedReason
    known_tech_ids: tuple[TechId, ...] = ()
    raw_operands: tuple[StrictStr, ...] = ()
    evidence: RequirementEvidence

    @field_validator("known_tech_ids")
    @classmethod
    def canonicalize_known_tech_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("raw_operands")
    @classmethod
    def canonicalize_raw_operands(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values if value.strip())
        return tuple(dict.fromkeys(normalized))


class JobRequirements(RequirementModel):
    schema_version: Literal["job-requirements/v1", "job-requirements/v2"] = (
        JOB_REQUIREMENTS_SCHEMA_VERSION
    )
    source_record_id: StrictStr
    content_hash: ContentHash
    parser_version: StrictStr
    level_policy_version: (
        Literal["job-required-level-policy/v1", "job-required-level-policy/v2"] | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    required: tuple[RequirementClause, ...] = ()
    preferred: tuple[RequirementClause, ...] = ()
    unresolved: tuple[UnresolvedRequirement, ...] = ()

    @model_validator(mode="after")
    def validate_versioned_level_contract(self) -> "JobRequirements":
        levelled = tuple(
            clause
            for clause in (*self.required, *self.preferred)
            if clause.required_level is not None or clause.level_evidence_refs
        )
        if self.schema_version == JOB_REQUIREMENTS_LEGACY_SCHEMA_VERSION:
            if self.level_policy_version is not None or levelled:
                raise ValueError("v1 requirements must not contain level fields")
            return self
        if self.level_policy_version is None:
            raise ValueError("v2 requirements require a known level policy version")
        if any(
            clause.required_level is None or not clause.level_evidence_refs
            for clause in self.required
        ):
            raise ValueError("every v2 required clause needs a level and evidence")
        if any(
            clause.required_level is not None or clause.level_evidence_refs
            for clause in self.preferred
        ):
            raise ValueError("preferred clauses do not carry a required level")
        return self

    @property
    def required_count(self) -> int:
        return len(self.required)

    @property
    def preferred_count(self) -> int:
        return len(self.preferred)

    def unresolved_for(
        self, requirement_kind: RequirementKind
    ) -> tuple[UnresolvedRequirement, ...]:
        return tuple(
            item
            for item in self.unresolved
            if item.requirement_kind is requirement_kind
        )


_OR = re.compile(r"\bor\b|또는|혹은|아니면", re.IGNORECASE)
_AND = re.compile(r"\band\b|및|그리고|&|\+", re.IGNORECASE)
_ACTIVITY_CONJUNCTION = re.compile(
    r"(?<!\w)(?:개발\s+및\s+운영|구축\s+및\s+(?:운영|운용)|"
    r"설계\s+및\s+구현|배포\s+및\s+운영|"
    r"(?:RDB|데이터베이스)\s+설계\s+및\s+쿼리\s+최적화\s+경험)(?!\w)"
)
_NEGATION = re.compile(
    r"없어도|무관|불필요|경험(?:이)?\s*없는|"
    r"미숙련(?:(?:인\s*)?지원자|자)(?:도)?[^,;.\n]{0,20}"
    r"(?:지원|응시|입사)[^,;.\n]{0,15}(?:가능|허용|할\s*수)|"
    r"필수(?:\s*(?:가|는|은))?\s*아(?:니|닌|닙|님|닐)\w*|"
    r"\boptional\b|\bnot\s+(?:required|necessary|needed|(?:a\s+)?requirement)\b|"
    r"(?:능숙|능통|숙련)(?:하|되)?지\s*않|"
    r"(?:능숙|능통|숙련)자(?:가|는)?\s*아니|"
    r"(?:필요|필수)(?:가|는)?\s*없|요구하지\s*않|"
    r"\b(?:not|without|no)\s+(?:proficien(?:t|cy)|expertise)\b|"
    r"\b(?:(?:do(?:es)?\s+not|don['’]t|doesn['’]t)\s+need\s+to|"
    r"need\s+not)\s+be\s+proficient\b|"
    r"\bno\s+[^,;\n]{1,80}\b(?:proficiency|expertise)\s+(?:is\s+)?required\b",
    re.IGNORECASE,
)
_CARDINALITY = re.compile(
    r"(?:(?<!\d)(?:[2-9]|[1-9]\d+)\s*(?:개|가지)|"
    r"(?:두|둘|세|셋|네|넷)\s*(?:개|가지))\s*이상"
)
_UNCERTAIN_EXAMPLE = re.compile(
    r"예시|예를|\betc\b|등(?=\s|[,.]|$|[을의])|"
    r"(?<![가-힣])등(?=[)\]}])|외(?=\s|[,.]|$)",
    re.IGNORECASE,
)
_GRADE_RANGE = re.compile(
    r"(?:사원|주임|대리|과장|차장|부장|임원)\s*(?:~|[-–—∼])\s*"
    r"(?:사원|주임|대리|과장|차장|부장|임원)"
)
_ONE_OF = re.compile(r"중\s*(?:하나|1개)|\b(?:one|any)\s+of\b", re.IGNORECASE)
_ONE_OF_PRELUDE = re.compile(
    r"(?:[-*•]\s*)?(?:(?:one|any)\s+of\s+(?:the\s+)?following|"
    r"(?:다음|아래)\s*(?:기술|항목)?\s*중\s*(?:하나|1개))\s*[:：]?",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(r"(?:[;；。]|\.(?=\s))\s*")
_YEAR_RANGE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:~|[-–—∼])\s*\d{1,2}\s*(?:년|years?)",
    re.IGNORECASE,
)
_MINIMUM_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:년|years?)"
    r"(?!\s*(?:이하|미만|↓|less\s+than|or\s+less))",
    re.IGNORECASE,
)
_L3_ACTIVITY = re.compile(
    r"아키텍처|대규모\s*(?:서비스\s*)?운영|최적화|리딩|"
    r"운영\s*(?:총괄|책임)|(?:총괄|책임)\s*운영|"
    r"\barchitect(?:ure|ing)?\b|\boptimi[sz](?:e|ation|ing)\b|\blead(?:ing)?\b",
    re.IGNORECASE,
)
_OVERALL_CAREER_SUFFIX = re.compile(
    r"[,，]\s*(?:총|전체)\s*경력\s*\d{1,2}\s*년(?:\s*이상)?(?=\s*(?:[,，]|$))"
)
_L3_PROFICIENCY = re.compile(
    r"능숙|능통|(?<!미)숙련|"
    r"(?:깊은|깊이\s*있는|심도\s*있는|심층적인|고급|전문(?:적인)?)\s*"
    r"(?:이해(?:도)?|지식)|"
    r"\bproficien(?:t(?:ly)?|cy)\b|"
    r"\b(?:deep|in-depth|advanced)\s+(?:understanding|knowledge)\b|"
    r"\bexpertise\s+(?:in|with)\b",
    re.IGNORECASE,
)
_KOREAN_COLLABORATOR_PROFICIENCY = re.compile(
    r"(?:미)?(?:능숙|능통|숙련)(?:하|되)?(?:ㄴ|은|한|된)?\s*"
    r"(?:(?:동료|팀원)|(?:개발자|엔지니어|전문가)(?=\s*(?:와|과)\s*협업))",
    re.IGNORECASE,
)
_ENGLISH_COLLABORATOR_PROFICIENCY = re.compile(
    r"(?P<context>\b(?:experience\s+)?(?:collaborating|working)\s+with\s+"
    r"(?:colleagues?|teammates?|engineers?|developers?|experts?)\s+"
    r"(?:who\s+(?:are|were)\s+)?(?:highly\s+)?)proficient\b",
    re.IGNORECASE,
)
_ENGLISH_PREFIXED_COLLABORATOR_PROFICIENCY = re.compile(
    r"(?P<context>\b(?:experience\s+)?(?:collaborating|working)\s+with\s+)"
    r"proficient\b(?P<tail>\s+(?:in\s+)?(?:[A-Za-z0-9.+#/-]+\s+){1,4}"
    r"(?:colleagues?|teammates?|engineers?|developers?|experts?)\b)",
    re.IGNORECASE,
)
_BASIC_INTENSITY = re.compile(
    r"(?:기초|기본)(?:적인)?\s*(?:이해|지식|사용|활용)|"
    r"\bbasic\s+(?:understanding|knowledge|use)\b",
    re.IGNORECASE,
)
_L2_ACTIVITY = re.compile(
    r"경험|실무|개발|운영|운용|구축|배포|설계|"
    r"\bexperience\b|\bdevelop(?:ment|ing)?\b|\boperat(?:e|ion|ing)\b",
    re.IGNORECASE,
)
_L1_CAPABILITY = re.compile(
    r"(?:활용|사용|개발|프로그래밍)(?:이|가|을|를)?\s*(?:가능|할\s*수)|"
    r"가능(?:자|하신\s*분)|\b(?:able\s+to|capable\s+of)\b",
    re.IGNORECASE,
)
_EXPLICIT_L1_INTENSITY = re.compile(
    r"기초\s*(?:이해|지식)|기본\s*(?:이해|지식)|(?:관련\s*)?지식|"
    r"\bbasic\s+(?:understanding|knowledge)\b",
    re.IGNORECASE,
)
_L1_ACTIVITY = re.compile(
    r"기초\s*(?:이해|지식)|기본\s*(?:이해|지식)|이해|지식|교육|자격|사용|"
    r"\bbasic\s+(?:understanding|knowledge)\b|신입",
    re.IGNORECASE,
)
_JOB_GRADES = {
    "사원": RequirementLevel.L1,
    "주임": RequirementLevel.L2,
    "대리": RequirementLevel.L2,
    "과장": RequirementLevel.L3,
    "차장": RequirementLevel.L3,
    "부장": RequirementLevel.L3,
    "임원": RequirementLevel.L3,
}
_LEVEL_ORDER = {
    RequirementLevel.L1: 1,
    RequirementLevel.L2: 2,
    RequirementLevel.L3: 3,
}

_REQUIRED_HEADINGS = frozenset(
    {
        "자격요건",
        "지원자격",
        "필수",
        "필수자격",
        "필수사항",
        "필수역량",
        "요구사항",
        "requirements",
        "required",
    }
)
_DUTY_HEADINGS = frozenset(
    {"담당업무", "주요업무", "업무내용", "직무내용", "responsibilities"}
)
_PREFERRED_HEADINGS = frozenset(
    {"우대", "우대사항", "우대조건", "우대자격요건", "preferred", "nicetohave"}
)
_TRAILING_PREFERRED = re.compile(r"우대(?:\s*(?:합니다|임|자))?\s*[.!]?$")
_DUTY_EXPLICIT_L3_REQUIREMENT = re.compile(
    r"(?=.*(?:RDB|데이터베이스))(?=.*(?:쿼리|SQL))(?=.*최적화)(?=.*경험)",
    re.IGNORECASE,
)
_GENERAL_HEADINGS = frozenset(
    {
        "기술스택",
        "사용기술",
        "복리후생",
        "근무조건",
        "채용절차",
        "benefits",
        "회사소개",
        "기업소개",
        "company",
        "aboutus",
    }
)


def _heading_key(value: str | None) -> str:
    if value is None:
        return ""
    label = value.casefold().strip().strip("[]()#*•-:：")
    label = re.sub(
        r"^(?:(?:[0-9]{1,2}[.)]|[0-9]\ufe0f?\u20e3|[📋🏠🎁🚀])\s*)+",
        "",
        label,
    )
    return "".join(label.split()).strip("[]()#*•-:：")


def _requirement_kind(item: TechnologyClassification) -> RequirementKind | None:
    if item.location.source_surface is SourceSurface.TITLE:
        return None
    effective_section = item.parsed_section or item.evidence_section
    effective_heading = _heading_key(effective_section)
    if effective_heading in _GENERAL_HEADINGS or effective_heading in _DUTY_HEADINGS:
        return None
    if item.requirement_class is RequirementClass.REQUIRED:
        return RequirementKind.REQUIRED
    if item.requirement_class is RequirementClass.PREFERRED:
        return RequirementKind.PREFERRED
    if item.requirement_class is RequirementClass.SKILL:
        return None

    for section in (item.parsed_section, item.evidence_section):
        heading = _heading_key(section)
        if heading in _GENERAL_HEADINGS:
            return None
        if heading in _REQUIRED_HEADINGS:
            return RequirementKind.REQUIRED
        if heading in _PREFERRED_HEADINGS:
            return RequirementKind.PREFERRED
    if item.input_requirement_type is RequirementType.REQUIRED:
        return RequirementKind.REQUIRED
    if item.input_requirement_type is RequirementType.PREFERRED:
        return RequirementKind.PREFERRED
    return None


def _surface(record: JobPostingInput, source: SourceSurface) -> str | None:
    return record.title if source is SourceSurface.TITLE else record.description_text


def _section_kind(
    label: str,
) -> RequirementKind | Literal["GENERAL", "DUTY"] | None:
    heading = _heading_key(label)
    if heading in _REQUIRED_HEADINGS:
        return RequirementKind.REQUIRED
    if heading in _PREFERRED_HEADINGS:
        return RequirementKind.PREFERRED
    if heading in _GENERAL_HEADINGS:
        return "GENERAL"
    if heading in _DUTY_HEADINGS:
        return "DUTY"
    return None


def _minimum_years(text: str) -> int | None:
    # A separately labelled overall-career suffix is not technology experience.
    text = _OVERALL_CAREER_SUFFIX.sub("", text)
    range_match = _YEAR_RANGE.search(text)
    if range_match is not None:
        return int(range_match.group(1))
    match = _MINIMUM_YEARS.search(text)
    return int(match.group(1)) if match is not None else None


def _signal_level(text: str) -> RequirementLevel | None:
    if _BASIC_INTENSITY.search(text):
        return RequirementLevel.L1
    # Explicit proficiency qualifies otherwise generic "able to use"/knowledge.
    # Negated requirements are rejected before this intensity is emitted.
    applicant_text = _KOREAN_COLLABORATOR_PROFICIENCY.sub("", text)
    applicant_text = _ENGLISH_COLLABORATOR_PROFICIENCY.sub(
        lambda match: match.group("context"), applicant_text
    )
    applicant_text = _ENGLISH_PREFIXED_COLLABORATOR_PROFICIENCY.sub(
        lambda match: match.group("context") + match.group("tail"), applicant_text
    )
    if _L3_PROFICIENCY.search(applicant_text):
        return RequirementLevel.L3
    if _L1_CAPABILITY.search(text) or _EXPLICIT_L1_INTENSITY.search(text):
        return RequirementLevel.L1
    years = _minimum_years(text)
    if years is not None:
        if years >= 5:
            return RequirementLevel.L3
        return RequirementLevel.L2 if years >= 1 else RequirementLevel.L1

    grades = tuple(level for grade, level in _JOB_GRADES.items() if grade in text)
    if grades:
        # Multiple directly bound grades without a range use the minimum.
        return min(grades, key=_LEVEL_ORDER.__getitem__)
    if _L3_ACTIVITY.search(text):
        return RequirementLevel.L3
    if _L2_ACTIVITY.search(text):
        return RequirementLevel.L2
    if _L1_ACTIVITY.search(text):
        return RequirementLevel.L1
    return None


def _level_evidence_sort_key(
    evidence: RequirementLevelEvidence,
) -> tuple[object, ...]:
    source_order = {
        RequirementLevelEvidenceSource.DIRECT_CLAUSE: 0,
        RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT: 1,
    }
    return (
        source_order[evidence.source],
        evidence.source_surface.value if evidence.source_surface is not None else "",
        evidence.char_start is None,
        evidence.char_start if evidence.char_start is not None else 0,
        evidence.char_end if evidence.char_end is not None else 0,
        evidence.text,
        evidence.mention_indices,
    )


def _required_level(
    evidences: tuple[RequirementEvidence, ...],
) -> tuple[RequirementLevel, tuple[RequirementLevelEvidence, ...]]:
    direct_evidences = []
    for evidence in evidences:
        direct_level = _signal_level(evidence.text)
        if direct_level is not None:
            direct_evidences.append(
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.DIRECT_CLAUSE,
                    level=direct_level,
                    text=evidence.text,
                    source_surface=evidence.source_surface,
                    char_start=evidence.char_start,
                    char_end=evidence.char_end,
                    mention_indices=evidence.mention_indices,
                )
            )
    mention_indices = tuple(
        sorted({index for evidence in evidences for index in evidence.mention_indices})
    )
    selected_evidences = direct_evidences
    if not selected_evidences:
        selected_evidences = [
            RequirementLevelEvidence(
                source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                level=RequirementLevel.L1,
                text="no stronger level signal",
                mention_indices=mention_indices,
            )
        ]

    canonical = tuple(sorted(set(selected_evidences), key=_level_evidence_sort_key))
    return max(
        (item.level for item in canonical), key=_LEVEL_ORDER.__getitem__
    ), canonical


def _segment_bounds(surface: str, start: int, end: int) -> tuple[int, int]:
    line_start = surface.rfind("\n", 0, start) + 1
    line_end = surface.find("\n", end)
    line_end = len(surface) if line_end < 0 else line_end
    for boundary in _SENTENCE_BOUNDARY.finditer(surface, line_start, line_end):
        if boundary.end() <= start:
            line_start = boundary.end()
        elif boundary.start() >= end:
            line_end = boundary.start()
            break
    while line_start < line_end and surface[line_start].isspace():
        line_start += 1
    while line_end > line_start and surface[line_end - 1].isspace():
        line_end -= 1
    return line_start, line_end


def _evidence_sort_key(evidence: RequirementEvidence) -> tuple[object, ...]:
    surface_order = 0 if evidence.source_surface is SourceSurface.TITLE else 1
    return (
        surface_order,
        evidence.char_start is None,
        evidence.char_start if evidence.char_start is not None else 0,
        evidence.char_end if evidence.char_end is not None else 0,
        evidence.text,
        evidence.mention_indices,
    )


def _merge_evidence(
    evidences: tuple[RequirementEvidence, ...],
) -> tuple[RequirementEvidence, ...]:
    merged: dict[tuple[object, ...], set[int]] = defaultdict(set)
    for evidence in evidences:
        key = (
            evidence.source_surface,
            evidence.char_start,
            evidence.char_end,
            evidence.text,
        )
        merged[key].update(evidence.mention_indices)
    return tuple(
        sorted(
            (
                RequirementEvidence(
                    source_surface=key[0],
                    char_start=key[1],
                    char_end=key[2],
                    text=key[3],
                    mention_indices=tuple(indices),
                )
                for key, indices in merged.items()
            ),
            key=_evidence_sort_key,
        )
    )


def _technology_spans(
    text: str, items: list[TechnologyClassification]
) -> list[tuple[int, int, str, str | None]]:
    spans = set()
    for item in items:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(item.raw_technology)}(?![A-Za-z0-9])"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            spans.add((match.start(), match.end(), item.raw_technology, item.tech_id))
    return sorted(spans, key=lambda value: (value[0], value[1], value[2].casefold()))


def _mask_spans(text: str, spans: list[tuple[int, int, str, str | None]]) -> str:
    masked = text
    for start, end, _, _ in reversed(spans):
        masked = masked[:start] + " " * (end - start) + masked[end:]
    for activity in _ACTIVITY_CONJUNCTION.finditer(text):
        start, end = activity.span()
        masked = masked[:start] + " " * (end - start) + masked[end:]
    return masked


def _missing_operand_fragments(
    text: str, spans: list[tuple[int, int, str, str | None]]
) -> tuple[str, ...]:
    masked = _mask_spans(text, spans)
    boundaries = (
        ((0, spans[0][0]),)
        + tuple((left[1], right[0]) for left, right in pairwise(spans))
        + ((spans[-1][1], len(text)),)
    )
    operands = []
    for start, end in boundaries:
        masked_fragment = masked[start:end]
        if not (_OR.search(masked_fragment) or _AND.search(masked_fragment)):
            continue
        fragment = text[start:end]
        fragment = re.sub(
            r"\bor\b|\band\b|또는|혹은|아니면|및|그리고|&|\+",
            " ",
            fragment,
            flags=re.IGNORECASE,
        )
        value = fragment.strip(" \t,./:：()[]{}-*•")
        value = re.sub(
            r"\s+(?:(?:개발|사용|운영|실무|관련)\s*)?(?:경험|역량|지식|능력).*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            r"^(?:experience|knowledge|proficiency)\s+(?:with|in)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        if value and re.search(r"[A-Za-z가-힣]", value):
            operands.append(value)
    return tuple(dict.fromkeys(operands))


def _independent_comma_evidence(
    text: str,
    evidence: RequirementEvidence,
    items: list[TechnologyClassification],
    spans: list[tuple[int, int, str, str | None]],
) -> dict[str, RequirementEvidence] | None:
    """Narrow only clearly self-contained comma-separated requirements.

    ``Java 개발 경력 5년 이상, Python 개발 경험`` contains two complete
    technology conditions. Keeping the whole line as evidence for both would
    leak Java's five-year signal into Python. A later fragment may itself be a
    list: ``React 능숙, Java와 Python 개발 경험`` binds the shared experience
    only to Java and Python. A bare list such as
    ``Java, Python 개발 경력 5년 이상`` is deliberately left intact because
    the trailing condition can apply to the whole list.
    """
    if evidence.char_start is None or evidence.char_end is None:
        return None
    boundaries = [0, *(match.end() for match in re.finditer(r"[,，]", text)), len(text)]
    fragments: list[tuple[int, int]] = []
    previous = boundaries[0]
    for boundary in boundaries[1:]:
        fragment_end = boundary
        if boundary != len(text):
            fragment_end -= 1
        start, end = previous, fragment_end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            fragments.append((start, end))
        previous = boundary
    if len(fragments) < 2:
        return None

    by_tech: dict[str, RequirementEvidence] = {}
    signals = []
    for start, end in fragments:
        fragment_spans = [span for span in spans if start <= span[0] and span[1] <= end]
        tech_ids = {span[3] for span in fragment_spans if span[3] is not None}
        if not tech_ids or any(span[3] is None for span in fragment_spans):
            return None
        if any(
            re.fullmatch(
                r"\s*(?:,|and|및|그리고|&|\+|와|과)\s*",
                text[left[1] : right[0]],
                re.IGNORECASE,
            )
            is None
            for left, right in pairwise(fragment_spans)
        ):
            return None
        signals.append(_signal_level(text[start:end]))
        for tech_id in sorted(tech_ids):
            if tech_id in by_tech:
                return None
            mention_indices = tuple(
                sorted(
                    {
                        item.mention_index
                        for item in items
                        if item.tech_id == tech_id
                        and item.mention_index in evidence.mention_indices
                    }
                )
            )
            if not mention_indices:
                return None
            by_tech[tech_id] = RequirementEvidence(
                source_surface=evidence.source_surface,
                char_start=evidence.char_start + start,
                char_end=evidence.char_start + end,
                text=text[start:end],
                mention_indices=mention_indices,
            )
    # A trailing condition can qualify a preceding bare list (Java, Python 경험).
    # A leading condition cannot qualify later bare operands (Java 능숙, Python).
    if not any(signal is not None for signal in signals[:-1]):
        return None
    return by_tech


def _unresolved_reason(
    text: str, items: list[TechnologyClassification]
) -> UnresolvedReason | None:
    if _NEGATION.search(text):
        return UnresolvedReason.NEGATION_UNSUPPORTED
    if _CARDINALITY.search(text):
        return UnresolvedReason.CARDINALITY_UNSUPPORTED
    if _GRADE_RANGE.search(text):
        return UnresolvedReason.LOGIC_UNSUPPORTED
    uncertainty_text = text
    for item in items:
        uncertainty_text = re.sub(
            rf"{re.escape(item.raw_technology)}\s+등\s+클라우드\s+환경",
            item.raw_technology,
            uncertainty_text,
            flags=re.IGNORECASE,
        )
    if _UNCERTAIN_EXAMPLE.search(uncertainty_text):
        return UnresolvedReason.LOGIC_UNSUPPORTED
    if any(item.match_status is not MatchStatus.MATCHED for item in items):
        return UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
    if any(
        item.requirement_class is RequirementClass.REVIEW_REQUIRED for item in items
    ):
        return UnresolvedReason.LOGIC_UNSUPPORTED
    return None


def _parse_segment(
    kind: RequirementKind,
    text: str,
    evidence: RequirementEvidence,
    items: list[TechnologyClassification],
) -> tuple[
    list[tuple[tuple[str, ...], RequirementEvidence]], UnresolvedRequirement | None
]:
    known_ids = tuple(
        sorted(
            {
                item.tech_id
                for item in items
                if item.match_status is MatchStatus.MATCHED and item.tech_id is not None
            }
        )
    )
    unknown_operands = tuple(
        dict.fromkeys(
            item.raw_technology
            for item in items
            if item.match_status is not MatchStatus.MATCHED or item.tech_id is None
        )
    )
    spans = _technology_spans(text, items)
    reason = _unresolved_reason(text, items)
    if reason is not None:
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=reason,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands,
            evidence=evidence,
        )
    if not spans or any(left[1] > right[0] for left, right in pairwise(spans)):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands,
            evidence=evidence,
        )

    masked = _mask_spans(text, spans)
    has_or = bool(_OR.search(masked) or _ONE_OF.search(masked))
    has_and = bool(_AND.search(masked))
    missing_fragments = _missing_operand_fragments(text, spans)
    if "/" in masked or (has_or and has_and):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )

    prefix, suffix = masked[: spans[0][0]], masked[spans[-1][1] :]
    if (
        _OR.search(prefix)
        or _OR.search(suffix)
        or _AND.search(prefix)
        or _AND.search(suffix)
    ):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=(
                UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
                if has_or and missing_fragments
                else UnresolvedReason.LOGIC_UNSUPPORTED
            ),
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )

    if has_or:
        if len(spans) < 2:
            return [], UnresolvedRequirement(
                requirement_kind=kind,
                reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                known_tech_ids=known_ids,
                raw_operands=unknown_operands or missing_fragments,
                evidence=evidence,
            )
        for left, right in pairwise(spans):
            connector = masked[left[1] : right[0]].strip()
            allowed = (
                r"(?:또는|혹은|아니면|or)"
                if not _ONE_OF.search(masked)
                else r"(?:또는|혹은|아니면|or|,)"
            )
            if re.fullmatch(allowed, connector, re.IGNORECASE) is None:
                return [], UnresolvedRequirement(
                    requirement_kind=kind,
                    reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                    known_tech_ids=known_ids,
                    raw_operands=unknown_operands or missing_fragments,
                    evidence=evidence,
                )
        return [(known_ids, evidence)], None

    if has_and and any(
        re.fullmatch(
            r"\s*(?:and|및|그리고|&|\+|,|\s)+",
            masked[left[1] : right[0]],
            re.IGNORECASE,
        )
        is None
        for left, right in pairwise(spans)
    ):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )
    if re.search(r",\s*$", prefix) or re.match(r"\s*,", suffix):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )
    independent = _independent_comma_evidence(text, evidence, items, spans)
    return [
        ((tech_id,), independent.get(tech_id, evidence) if independent else evidence)
        for tech_id in known_ids
    ], None


def extract_job_requirements(
    record: JobPostingInput,
    classification: JobClassificationRecord,
) -> JobRequirements:
    """Preserve independently resolvable clauses and every unresolved source span.

    The extractor intentionally accepts only the current classifier output for
    the same immutable source record. It performs no Registry mapping itself and
    does not change the strict cohort inclusion calculation.
    """

    if (
        record.source_record_id != classification.source_record_id
        or record.content_hash != classification.content_hash
        or len(record.technology_mentions) != len(classification.technologies)
    ):
        raise ValueError("record and classification must describe the same source")
    if any(
        item.mention_index != index
        or item.raw_technology != record.technology_mentions[index].raw_technology
        for index, item in enumerate(classification.technologies)
    ):
        raise ValueError("classification mention lineage does not match the record")

    located_duplicates: dict[
        tuple[RequirementKind, SourceSurface, str, str], tuple[int, int]
    ] = {}
    for item in classification.technologies:
        kind = _requirement_kind(item)
        if (
            kind is not None
            and item.location.char_start is not None
            and item.location.char_end is not None
        ):
            located_duplicates.setdefault(
                (
                    kind,
                    item.location.source_surface,
                    item.evidence_text,
                    item.raw_technology.casefold(),
                ),
                (item.location.char_start, item.location.char_end),
            )

    groups: defaultdict[
        tuple[RequirementKind, SourceSurface, int, int, str],
        list[TechnologyClassification],
    ] = defaultdict(list)
    unlocated: defaultdict[
        tuple[RequirementKind, SourceSurface, str], list[TechnologyClassification]
    ] = defaultdict(list)
    for item in classification.technologies:
        kind = _requirement_kind(item)
        if kind is None:
            continue
        surface = _surface(record, item.location.source_surface)
        start, end = item.location.char_start, item.location.char_end
        if start is None or end is None:
            duplicate_location = located_duplicates.get(
                (
                    kind,
                    item.location.source_surface,
                    item.evidence_text,
                    item.raw_technology.casefold(),
                )
            )
            if duplicate_location is not None:
                start, end = duplicate_location
        if (
            surface is None
            or start is None
            or end is None
            or start < 0
            or end > len(surface)
            or start >= end
        ):
            unlocated[(kind, item.location.source_surface, item.evidence_text)].append(
                item
            )
            continue
        raw_pattern = (
            rf"(?<![A-Za-z0-9]){re.escape(item.raw_technology)}(?![A-Za-z0-9])"
        )
        occurrences = tuple(re.finditer(raw_pattern, surface[start:end], re.IGNORECASE))
        occurrence_ranges = {
            _segment_bounds(
                surface,
                start + occurrence.start(),
                start + occurrence.end(),
            )
            for occurrence in occurrences
        }
        if not occurrence_ranges:
            occurrence_ranges = {_segment_bounds(surface, start, end)}
        for segment_start, segment_end in occurrence_ranges:
            segment_text = surface[segment_start:segment_end]
            groups[
                (
                    kind,
                    item.location.source_surface,
                    segment_start,
                    segment_end,
                    segment_text,
                )
            ].append(item)

    # Some collectors intentionally emit one mention per technology even when
    # the same technology occurs in multiple source statements. Revisit only
    # explicit requirement sections and only for already classified technology
    # surface forms. This recovers repeated evidence and lets an expression such
    # as ``Java or unmapped-token`` remain unresolved without attempting a new
    # Registry mapping or treating arbitrary prose as a requirement.
    if record.description_text is not None:
        by_raw: defaultdict[str, list[TechnologyClassification]] = defaultdict(list)
        recovered_unlocated_indices: set[int] = set()
        preferred_span_overrides: set[tuple[SourceSurface, int, int]] = set()
        for item in classification.technologies:
            if item.location.source_surface is SourceSurface.BODY and (
                item.location.char_start is not None
                or item.source_technology_id is not None
            ):
                by_raw[item.raw_technology.casefold()].append(item)
        active_section: RequirementKind | Literal["GENERAL", "DUTY"] | None = None
        offset = 0
        for line_with_end in record.description_text.splitlines(keepends=True):
            line = line_with_end.rstrip("\r\n")
            heading = re.split(r"[:：]", line.strip(), maxsplit=1)[0].strip()
            section = _section_kind(heading)
            if section is not None:
                active_section = section
                offset += len(line_with_end)
                continue
            line_section = active_section
            has_trailing_preferred = _TRAILING_PREFERRED.search(line) is not None
            if active_section is RequirementKind.PREFERRED or has_trailing_preferred:
                line_section = RequirementKind.PREFERRED
            elif active_section == "DUTY" and _DUTY_EXPLICIT_L3_REQUIREMENT.search(
                line
            ):
                line_section = RequirementKind.REQUIRED
            if line_section not in (
                RequirementKind.REQUIRED,
                RequirementKind.PREFERRED,
            ):
                offset += len(line_with_end)
                continue
            for candidates in by_raw.values():
                raw = candidates[0].raw_technology
                pattern = rf"(?<![A-Za-z0-9]){re.escape(raw)}(?![A-Za-z0-9])"
                occurrences = tuple(re.finditer(pattern, line, re.IGNORECASE))
                if not occurrences:
                    continue
                candidate = next(
                    (
                        item
                        for item in candidates
                        if _requirement_kind(item) is line_section
                    ),
                    candidates[0],
                )
                for occurrence in occurrences:
                    start, end = _segment_bounds(
                        record.description_text,
                        offset + occurrence.start(),
                        offset + occurrence.end(),
                    )
                    groups[
                        (
                            line_section,
                            SourceSurface.BODY,
                            start,
                            end,
                            record.description_text[start:end],
                        )
                    ].append(candidate)
                    if has_trailing_preferred:
                        preferred_span_overrides.add((SourceSurface.BODY, start, end))
                    if (
                        candidate.location.char_start is None
                        or candidate.location.char_end is None
                    ):
                        recovered_unlocated_indices.add(candidate.mention_index)
            offset += len(line_with_end)
    else:
        recovered_unlocated_indices = set()
        preferred_span_overrides = set()

    clauses: defaultdict[
        RequirementKind, dict[tuple[str, ...], list[RequirementEvidence]]
    ] = defaultdict(lambda: defaultdict(list))
    unresolved = []
    for (kind, source_surface, start, end, text), items in groups.items():
        if (
            kind is RequirementKind.REQUIRED
            and (source_surface, start, end) in preferred_span_overrides
        ):
            continue
        surface = _surface(record, source_surface)
        if surface is not None:
            previous_line = next(
                (
                    line.strip()
                    for line in reversed(surface[:start].splitlines())
                    if line.strip()
                ),
                "",
            )
            if _ONE_OF_PRELUDE.fullmatch(previous_line):
                evidence = RequirementEvidence(
                    source_surface=source_surface,
                    char_start=start,
                    char_end=end,
                    text=text,
                    mention_indices=tuple(item.mention_index for item in items),
                )
                unresolved.append(
                    UnresolvedRequirement(
                        requirement_kind=kind,
                        reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                        known_tech_ids=tuple(
                            item.tech_id for item in items if item.tech_id is not None
                        ),
                        raw_operands=(),
                        evidence=evidence,
                    )
                )
                continue
        evidence = RequirementEvidence(
            source_surface=source_surface,
            char_start=start,
            char_end=end,
            text=text,
            mention_indices=tuple(item.mention_index for item in items),
        )
        parsed, unresolved_item = _parse_segment(kind, text, evidence, items)
        for tech_ids, clause_evidence in parsed:
            if tech_ids:
                clauses[kind][tech_ids].append(clause_evidence)
        if unresolved_item is not None:
            unresolved.append(unresolved_item)

    for (kind, source_surface, evidence_text), items in unlocated.items():
        items = [
            item
            for item in items
            if item.mention_index not in recovered_unlocated_indices
        ]
        if not items:
            continue
        unresolved.append(
            UnresolvedRequirement(
                requirement_kind=kind,
                reason=UnresolvedReason.EVIDENCE_NOT_LOCATED,
                known_tech_ids=tuple(
                    item.tech_id
                    for item in items
                    if item.match_status is MatchStatus.MATCHED
                    and item.tech_id is not None
                ),
                raw_operands=tuple(
                    item.raw_technology
                    for item in items
                    if item.match_status is not MatchStatus.MATCHED
                    or item.tech_id is None
                ),
                evidence=RequirementEvidence(
                    source_surface=source_surface,
                    char_start=None,
                    char_end=None,
                    text=evidence_text,
                    mention_indices=tuple(item.mention_index for item in items),
                ),
            )
        )

    def build_clauses(kind: RequirementKind) -> tuple[RequirementClause, ...]:
        built = []
        for tech_ids, evidences in sorted(clauses[kind].items()):
            merged_evidence = _merge_evidence(tuple(evidences))
            if kind is RequirementKind.REQUIRED:
                level, level_evidence = _required_level(merged_evidence)
                built.append(
                    RequirementClause(
                        tech_ids=tech_ids,
                        evidence_refs=merged_evidence,
                        required_level=level,
                        level_evidence_refs=level_evidence,
                    )
                )
            else:
                built.append(
                    RequirementClause(
                        tech_ids=tech_ids,
                        evidence_refs=merged_evidence,
                    )
                )
        return tuple(built)

    unresolved = sorted(
        unresolved,
        key=lambda item: (
            item.requirement_kind.value,
            _evidence_sort_key(item.evidence),
            item.reason.value,
            item.known_tech_ids,
            item.raw_operands,
        ),
    )
    return JobRequirements(
        source_record_id=record.source_record_id,
        content_hash=record.content_hash,
        parser_version=JOB_REQUIREMENT_PARSER_VERSION,
        level_policy_version=JOB_REQUIRED_LEVEL_POLICY_VERSION,
        required=build_clauses(RequirementKind.REQUIRED),
        preferred=build_clauses(RequirementKind.PREFERRED),
        unresolved=tuple(unresolved),
    )
