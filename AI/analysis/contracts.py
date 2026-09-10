"""The repository analysis request as the worker reads it.

The producing side is `BE/.../analysis/event/RepositoryAnalysisRequestedEvent.java`
and the agreed shape is `docs/data/contracts/repository-analysis-request-v1.schema.json`.
This module is the consumer's half of that contract.

### Why the constraints are repeated here

B validates on the way out and this validates on the way in. That is not
redundant: the two sides are deployed separately, and a message that has been
sitting in a topic for days was written by whatever version was running then.
A field that fails here is rejected before any clone is attempted.

### What is deliberately absent

There is no token. The payload carries `analysis_repository_id` instead, which
the worker exchanges for a short-lived credential when private repositories are
supported. Nothing here should ever be widened to carry a secret: the topic
outlives the credential.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

__all__ = [
    "EVENT_TYPE",
    "SCHEMA_VERSION",
    "RepositoryAnalysisRequest",
    "RepositoryAnalysisRequestPayload",
]

SCHEMA_VERSION = "repository-analysis-request/v1"
EVENT_TYPE = "repository.analysis.requested"

_FULL_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ANALYSIS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")

# Every identifier the publisher sends, narrowed to a charset that is safe wherever these
# values end up. analysis_id becomes a directory name, so a value like "/etc" or ".." would
# make the checkout and its cleanup act outside the work root. trace_id is written to logs,
# where a newline would let a caller forge log lines. The producer already emits
# "<prefix>_<uuid hex>", so nothing legitimate is excluded.
_IDENTIFIER = r"^[A-Za-z0-9_-]{1,80}$"

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=_IDENTIFIER)
]


class RepositoryAnalysisRequestPayload(BaseModel):
    """Everything needed to fetch exactly one tree, and nothing else."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: Identifier
    analysis_repository_id: Identifier
    github_repository_id: int = Field(gt=0)
    repository_full_name: str
    branch_name: str = Field(min_length=1, max_length=255)
    commit_sha: str
    analysis_mode: str
    registry_version: str = Field(min_length=1)

    @field_validator("analysis_id")
    @classmethod
    def _safe_analysis_id(cls, value: str) -> str:
        if not _ANALYSIS_ID.fullmatch(value):
            raise ValueError("analysis_id must be a single path-safe identifier")
        return value

    @field_validator("repository_full_name")
    @classmethod
    def _owner_and_repo(cls, value: str) -> str:
        if not _FULL_NAME.match(value):
            raise ValueError("repository_full_name must be owner/repo")
        return value

    @field_validator("commit_sha")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        # The analysis is pinned to this commit even after the branch moves, so
        # an abbreviated or uppercase SHA is a contract violation, not a hint.
        if not _COMMIT_SHA.match(value):
            raise ValueError("commit_sha must be 40 lowercase hex characters")
        return value

    @field_validator("branch_name")
    @classmethod
    def _usable_branch(cls, value: str) -> str:
        if value != value.strip() or value.startswith("/") or ".." in value:
            raise ValueError("branch_name is not a usable ref")
        return value

    @property
    def owner(self) -> str:
        return self.repository_full_name.split("/", 1)[0]

    @property
    def repository(self) -> str:
        return self.repository_full_name.split("/", 1)[1]


class RepositoryAnalysisRequest(BaseModel):
    """The envelope. `event_id` is the deduplication key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    schema_version: str
    event_type: str
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisRequestPayload

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        # A future version may add fields this worker would silently ignore.
        # Refusing here sends it to the DLQ where it is visible.
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {value!r}")
        return value

    @field_validator("event_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value != EVENT_TYPE:
            raise ValueError(f"unsupported event_type {value!r}")
        return value
