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
    "AnalysisStats",
    "EvidenceItem",
    "RepositoryAnalysisResult",
    "RepositoryAnalysisResultPayload",
    "TechnologyCandidate",
    "TechnologyVerdict",
]

SCHEMA_VERSION = "repository-analysis-result/v1"
EVENT_TYPE = "repository.analysis.completed"

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

# Same charset as the request contract. These identifiers are echoed back from a
# request that already enforced it, so anything else means something upstream changed.
Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]{1,80}$")
]

Level = Literal["L0", "L1", "L2", "L3"]
FactType = Literal["IMPORT", "DEPENDENCY", "ANNOTATION", "CONFIG_KEY", "API_CALL"]
Ecosystem = Literal["MAVEN", "NPM", "PYPI", "NUGET"]


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


class AnalysisStats(BaseModel):
    """What the run saw. Operational rather than user facing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files_parsed: int = Field(default=0, ge=0)
    files_skipped: int = Field(default=0, ge=0)
    import_count: int = Field(default=0, ge=0)
    dependency_count: int = Field(default=0, ge=0)
    bytes_on_disk: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)


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
