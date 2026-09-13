"""The analysis result as the worker writes it.

The agreed shape is `docs/data/contracts/repository-analysis-result-v1.schema.json`
and the consuming side is B's Spring service. This module is the producer's half.

### Why the result travels as an event at all

The worker could write `analysis_evidence` directly -- it already holds a
connection to the same database for `repo_analysis.event_claim`. It does not,
for the reason `claim.py` gives about `analysis_job`: those tables belong to the
Spring service, which maps them as JPA entities and boots with
`ddl-auto=validate`. A second writer in another language turns every column
change into a two-repository migration.

Reading the registry is a different matter and is allowed: a reader does not
constrain the schema's owner.

### Why failures ride the same topic

The DLQ already carries failed requests, but the DLQ is for operators. A user
whose repository was deleted needs to see "failed" in the UI, and the only way
that reaches `analysis_job` is this topic. A failure that exists solely in the
DLQ leaves the job at `QUEUED` forever, which is what happens today.

### What is deliberately absent

There is no `user_id`. The worker never learns who owns an analysis, and
`analysis_id` is enough for B to find out. Widening this to carry identity would
put user data in a topic that outlives the request.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "EVENT_TYPE",
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_V2",
    "SCHEMA_VERSION_V3",
    "SCHEMA_VERSION_V4",
    "AnalysisStats",
    "AnalysisStatsV2",
    "AnalysisStatsV3",
    "EvidenceItem",
    "EvidenceItemV2",
    "EvidenceItemV3",
    "EvidenceItemV4",
    "PersonalTechnologyAssessmentItem",
    "RepositoryAnalysisResult",
    "RepositoryAnalysisResultPayload",
    "RepositoryAnalysisResultPayloadV2",
    "RepositoryAnalysisResultPayloadV3",
    "RepositoryAnalysisResultPayloadV4",
    "RepositoryAnalysisResultV2",
    "RepositoryAnalysisResultV3",
    "RepositoryAnalysisResultV4",
    "TechnologyCandidate",
    "TechnologyCandidateV2",
    "TechnologySupportItem",
    "TechnologySupportItemV3",
    "TechnologyVerdict",
    "schema_for_rule_pack",
]

SCHEMA_VERSION = "repository-analysis-result/v1"
SCHEMA_VERSION_V2 = "repository-analysis-result/v2"
SCHEMA_VERSION_V3 = "repository-analysis-result/v3"
SCHEMA_VERSION_V4 = "repository-analysis-result/v4"
EVENT_TYPE = "repository.analysis.completed"

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

# Same charset as the request contract. These identifiers are echoed back from a
# request that already enforced it, so anything else means something upstream changed.
Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]{1,80}$"),
]

Level = Literal["L0", "L1", "L2", "L3"]
_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
FactType = Literal["IMPORT", "DEPENDENCY", "ANNOTATION", "CONFIG_KEY", "API_CALL"]
FactTypeV2 = Literal[
    "IMPORT", "DEPENDENCY", "ANNOTATION", "CONFIG_KEY", "API_CALL", "SOURCE_FILE"
]
FactTypeV3 = Literal[
    "IMPORT",
    "DEPENDENCY",
    "ANNOTATION",
    "CONFIG_KEY",
    "API_CALL",
    "SOURCE_FILE",
    "SYNTAX_NODE",
]
Ecosystem = Literal["MAVEN", "NPM", "PYPI", "NUGET"]
EcosystemV2 = Literal["MAVEN", "NPM", "PYPI", "NUGET", "GO", "CARGO", "COMPOSER"]


class TechnologyVerdict(BaseModel):
    """One technology and the level the rules put it at."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tech_id: str = Field(min_length=1, max_length=80)
    level: Level
    #: Every rule that matched, not only the one that set the level. A level with
    #: no rule behind it cannot be explained, and explaining is the point.
    matched_rule_ids: tuple[str, ...] = Field(min_length=1, max_length=50)


class EvidenceItem(BaseModel):
    """One fact that supported one rule. Becomes a row in `analysis_evidence`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=80)
    fact_type: FactType
    file_path: str = Field(min_length=1, max_length=1024)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    #: Keyed by the rules' `fact_field` vocabulary (MODULE, COORDINATE, ECOSYSTEM,
    #: SCOPE, LANGUAGE, FILE_PATH). Free-form so a new fact type needs no contract change.
    fact_payload: dict[str, Any]
    code_snippet: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _line_range(self) -> EvidenceItem:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class TechnologyCandidate(BaseModel):
    """An unmatched dependency, observed once in this repository.

    Only dependencies. An import path has no reliable package boundary in Java or
    C# -- `org.springframework.web` and `org.springframework.data.redis` are the
    same depth apart as `org.hamcrest` and `org.hamcrest.Matchers` -- while a
    manifest entry is already the unit an admin would promote.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ecosystem: Ecosystem
    #: Version stripped. `jjwt-api:0.12.6` and `:0.12.7` are one candidate, not two.
    coordinate: str = Field(min_length=1, max_length=300)
    scope: str | None = Field(default=None, max_length=40)
    occurrence_count: int = Field(ge=1)


class TechnologyCandidateV2(TechnologyCandidate):
    ecosystem: EcosystemV2


class AnalysisStats(BaseModel):
    """What the run saw. Operational rather than user facing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files_parsed: int = Field(default=0, ge=0)
    files_skipped: int = Field(default=0, ge=0)
    import_count: int = Field(default=0, ge=0)
    dependency_count: int = Field(default=0, ge=0)
    bytes_on_disk: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)


class AnalysisStatsV2(AnalysisStats):
    source_file_count: int = Field(default=0, ge=0)
    annotation_count: int = Field(default=0, ge=0)
    config_count: int = Field(default=0, ge=0)
    api_call_count: int = Field(default=0, ge=0)
    skipped_reasons: dict[str, int] = Field(default_factory=dict)


class RepositoryAnalysisResultPayload(BaseModel):
    """Everything B needs to close out one analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: Identifier
    #: The request this answers, so B can tell a redelivery from a re-analysis.
    request_event_id: Identifier
    registry_version: str = Field(min_length=1)
    commit_sha: str
    status: Literal["COMPLETED", "FAILED"]
    error_code: str | None = Field(default=None, max_length=64)
    #: git's stderr, typically. Operator facing; the UI switches on error_code.
    error_detail: str | None = Field(default=None, max_length=500)
    technologies: tuple[TechnologyVerdict, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    candidates: tuple[TechnologyCandidate, ...] = ()
    stats: AnalysisStats | None = None

    @model_validator(mode="after")
    def _consistent_outcome(self) -> RepositoryAnalysisResultPayload:
        if self.status == "FAILED":
            if not self.error_code:
                raise ValueError("a FAILED result must carry an error_code")
            # A failure that also reports technologies would have B write evidence
            # for an analysis it is about to mark failed.
            if self.technologies or self.evidence or self.candidates:
                raise ValueError("a FAILED result must not carry findings")
        elif self.error_code:
            raise ValueError("error_code belongs to a FAILED result")
        if not _COMMIT_SHA.match(self.commit_sha):
            raise ValueError("commit_sha must be 40 lowercase hex characters")
        return self


class EvidenceItemV2(EvidenceItem):
    """V2 adds SOURCE_FILE explicitly; v1 remains byte-for-byte strict."""

    fact_type: FactTypeV2


class TechnologySupportItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tech_id: str = Field(min_length=1, max_length=80)
    evaluation_scope: Literal["REPOSITORY"]
    required_fact_types: tuple[FactTypeV2, ...] = Field(min_length=1)
    max_supported_level: Level
    coverage: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    limitations: tuple[str, ...] = ()


class RepositoryAnalysisResultPayloadV2(RepositoryAnalysisResultPayload):
    """Common44 result with the immutable Rule Pack and assessment ceilings."""

    rule_pack_version: str | None = Field(default=None, min_length=1)
    rule_pack_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    technology_support: tuple[TechnologySupportItem, ...] = ()
    evidence: tuple[EvidenceItemV2, ...] = ()
    candidates: tuple[TechnologyCandidateV2, ...] = ()
    stats: AnalysisStatsV2 | None = None

    @model_validator(mode="after")
    def _completed_common44_has_lineage(self):
        if self.status == "COMPLETED":
            if not self.rule_pack_version or not self.rule_pack_content_sha256:
                raise ValueError(
                    "a COMPLETED v2 result requires Rule Pack version and hash"
                )
            if not self.technology_support:
                raise ValueError(
                    "a COMPLETED v2 result requires technology support metadata"
                )
        return self


class RepositoryAnalysisResult(BaseModel):
    """The envelope. `event_id` is the deduplication key on B's side."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    schema_version: str = SCHEMA_VERSION
    event_type: str = EVENT_TYPE
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisResultPayload

    @model_validator(mode="after")
    def _known_shape(self) -> RepositoryAnalysisResult:
        # Validated on the way out as well as the way in. The two sides deploy
        # separately, and a message sitting in a topic was written by whatever
        # version was running then.
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version!r}")
        if self.event_type != EVENT_TYPE:
            raise ValueError(f"unsupported event_type {self.event_type!r}")
        return self


class RepositoryAnalysisResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    schema_version: Literal["repository-analysis-result/v2"] = SCHEMA_VERSION_V2
    event_type: Literal["repository.analysis.completed"] = EVENT_TYPE
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisResultPayloadV2


class EvidenceItemV3(EvidenceItemV2):
    fact_type: FactTypeV3


class AnalysisStatsV3(AnalysisStatsV2):
    syntax_node_count: int = Field(default=0, ge=0)


class TechnologySupportItemV3(TechnologySupportItem):
    required_fact_types: tuple[FactTypeV3, ...] = Field(min_length=1)


class RepositoryAnalysisResultPayloadV3(RepositoryAnalysisResultPayloadV2):
    evidence: tuple[EvidenceItemV3, ...] = ()
    technology_support: tuple[TechnologySupportItemV3, ...] = ()
    stats: AnalysisStatsV3 | None = None

    @model_validator(mode="after")
    def _depth_version_pair(self):
        pair = (self.registry_version, self.rule_pack_version)
        if self.status == "COMPLETED" and pair not in {
            ("registry-20260911.3", "rule-pack-20260911.3"),
            ("registry-20260911.4", "rule-pack-20260911.4"),
        }:
            raise ValueError(
                "v3 structural evidence requires the depth Registry/Rule Pack version pair"
            )
        return self


class RepositoryAnalysisResultV3(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: Identifier
    schema_version: Literal["repository-analysis-result/v3"] = SCHEMA_VERSION_V3
    event_type: Literal["repository.analysis.completed"] = EVENT_TYPE
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisResultPayloadV3


class EvidenceItemV4(EvidenceItemV3):
    """V4 ties the existing Rule Pack fact to pinned-commit authorship."""

    fact_id: str = Field(min_length=1, max_length=80)
    repository_analysis_id: Identifier
    tech_id: str = Field(min_length=1, max_length=80)
    attribution: Literal["SELF", "OTHER", "UNKNOWN"]
    attribution_commit_sha: str | None = None
    attribution_missing_scope: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _coherent_attribution(self):
        if self.attribution in {"SELF", "OTHER"} and not self.attribution_commit_sha:
            raise ValueError("resolved attribution requires a commit SHA")
        if self.attribution == "UNKNOWN" and not self.attribution_missing_scope:
            raise ValueError("unknown attribution requires missing scope")
        if self.attribution_commit_sha and not _COMMIT_SHA.match(
            self.attribution_commit_sha
        ):
            raise ValueError(
                "attribution_commit_sha must be 40 lowercase hex characters"
            )
        return self


class PersonalTechnologyAssessmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tech_id: str = Field(min_length=1, max_length=80)
    personal_level: Level | None
    assessment_ceiling: Level
    attribution_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    missing_scope: tuple[str, ...] = ()
    decisive_fact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _coherent_assessment(self):
        if self.personal_level is not None and (
            _LEVEL_ORDER[self.personal_level] > _LEVEL_ORDER[self.assessment_ceiling]
        ):
            raise ValueError("personal_level must not exceed assessment_ceiling")
        if self.personal_level is None and self.attribution_status == "COMPLETE":
            raise ValueError("complete assessment must resolve a personal_level")
        if self.attribution_status != "COMPLETE" and not self.missing_scope:
            raise ValueError("incomplete assessment requires missing scope")
        return self


class RepositoryAnalysisResultPayloadV4(RepositoryAnalysisResultPayloadV3):
    evidence: tuple[EvidenceItemV4, ...] = ()
    personal_assessments: tuple[PersonalTechnologyAssessmentItem, ...] = ()

    @model_validator(mode="after")
    def _personal_results_cover_repository_positives(self):
        if self.status != "COMPLETED":
            return self
        if (
            self.registry_version,
            self.rule_pack_version,
        ) != ("registry-20260911.4", "rule-pack-20260911.4"):
            raise ValueError("v4 personal results require the scope Rule Pack pair")
        tech_ids = [item.tech_id for item in self.personal_assessments]
        if len(tech_ids) != len(set(tech_ids)):
            raise ValueError("personal assessments must be unique by tech_id")
        if set(tech_ids) != {item.tech_id for item in self.technologies}:
            raise ValueError(
                "v4 personal assessments must cover every positive technology"
            )
        return self


class RepositoryAnalysisResultV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: Identifier
    schema_version: Literal["repository-analysis-result/v4"] = SCHEMA_VERSION_V4
    event_type: Literal["repository.analysis.completed"] = EVENT_TYPE
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisResultPayloadV4


def schema_for_rule_pack(rule_pack_version: str | None) -> str:
    if not rule_pack_version:
        return SCHEMA_VERSION
    versions = {
        "rule-pack-20260911.2": SCHEMA_VERSION_V2,
        "rule-pack-20260911.3": SCHEMA_VERSION_V3,
        "rule-pack-20260911.4": SCHEMA_VERSION_V3,
    }
    try:
        return versions[rule_pack_version]
    except KeyError as invalid:
        raise ValueError(
            f"unsupported Rule Pack result version {rule_pack_version!r}"
        ) from invalid
