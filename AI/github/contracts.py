"""A-team to C-team GitHub repository snapshot input contract."""

import re
from datetime import date, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from pydantic.types import StringConstraints

GITHUB_REPO_SNAPSHOT_SCHEMA_VERSION = "github-repo-snapshot/v1"
_ISO_8601_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

GitObjectSha = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{40}$"),
]
ContentHash = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
RepoFullName = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$",
    ),
]


class RepoCollectionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    REUSED = "REUSED"


class RepoCollectionIssue(StrEnum):
    TREE_TRUNCATED = "TREE_TRUNCATED"
    TREE_LIMIT_REACHED = "TREE_LIMIT_REACHED"
    FILE_LIMIT_REACHED = "FILE_LIMIT_REACHED"
    BYTE_LIMIT_REACHED = "BYTE_LIMIT_REACHED"
    RATE_LIMITED = "RATE_LIMITED"
    ARTIFACT_FETCH_FAILED = "ARTIFACT_FETCH_FAILED"
    REPOSITORY_UNAVAILABLE = "REPOSITORY_UNAVAILABLE"


class RepoArtifactType(StrEnum):
    MANIFEST = "MANIFEST"
    SOURCE = "SOURCE"


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepoCollectionPolicy(StrictContractModel):
    policy_version: StrictStr
    top_n_limit: Annotated[StrictInt, Field(gt=0)]
    max_api_calls: Annotated[StrictInt, Field(gt=0)]
    max_runtime_seconds: Annotated[StrictInt, Field(gt=0)]
    max_tree_entries: Annotated[StrictInt, Field(gt=0)]
    max_artifact_files: Annotated[StrictInt, Field(gt=0)]
    max_artifact_bytes: Annotated[StrictInt, Field(gt=0)]

    @field_validator("policy_version")
    @classmethod
    def require_non_blank_policy_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_version must not be blank")
        return value


class RepoArtifact(StrictContractModel):
    artifact_type: RepoArtifactType
    path: StrictStr
    uri: StrictStr
    content_hash: ContentHash
    size_bytes: Annotated[StrictInt, Field(ge=0)]

    @field_validator("path")
    @classmethod
    def require_safe_repo_relative_posix_path(cls, value: str) -> str:
        if (
            not value.strip()
            or value != value.strip()
            or "\\" in value
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("path must be a safe repository-relative POSIX path")
        return value

    @field_validator("uri")
    @classmethod
    def require_non_blank_artifact_uri(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("uri must not be blank")
        return value


class GitHubRepoSnapshot(StrictContractModel):
    repo_snapshot_id: StrictStr
    github_repo_id: Annotated[StrictInt, Field(gt=0)]
    repo_full_name: RepoFullName
    activity_metric: StrictStr
    activity_period_start: date
    activity_period_end: date
    activity_count: Annotated[StrictInt, Field(ge=0)]
    activity_rank: Annotated[StrictInt, Field(gt=0)]
    pinned_commit_sha: GitObjectSha
    tree_sha: GitObjectSha | None = None
    collection_status: RepoCollectionStatus
    collection_issues: tuple[RepoCollectionIssue, ...] = ()
    checkpoint_uri: StrictStr | None = None
    reused_from_snapshot_id: StrictStr | None = None
    tree_truncated: StrictBool
    observed_tree_entries: Annotated[StrictInt, Field(ge=0)]
    artifacts: tuple[RepoArtifact, ...] = ()

    @field_validator("repo_snapshot_id", "activity_metric")
    @classmethod
    def require_non_blank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("checkpoint_uri", "reused_from_snapshot_id")
    @classmethod
    def reject_blank_optional_identifier(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional identifier must not be blank")
        return value

    @field_validator("activity_period_start", "activity_period_end", mode="before")
    @classmethod
    def require_iso_date_input(cls, value: object) -> object:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
            raise ValueError("activity period must be an ISO 8601 date string")
        return value

    @model_validator(mode="after")
    def validate_collection_state(self) -> "GitHubRepoSnapshot":
        issues = set(self.collection_issues)
        if len(issues) != len(self.collection_issues):
            raise ValueError("collection_issues must not contain duplicates")
        if self.activity_period_start > self.activity_period_end:
            raise ValueError(
                "activity_period_start must not be after activity_period_end"
            )

        if self.collection_status is RepoCollectionStatus.COMPLETE:
            if issues:
                raise ValueError("COMPLETE snapshot must not have collection issues")
            if self.checkpoint_uri is not None:
                raise ValueError("COMPLETE snapshot must not have checkpoint_uri")
            if self.reused_from_snapshot_id is not None:
                raise ValueError(
                    "COMPLETE snapshot must not have reused_from_snapshot_id"
                )
        elif self.collection_status in {
            RepoCollectionStatus.PARTIAL,
            RepoCollectionStatus.FAILED,
        }:
            if not issues:
                raise ValueError("incomplete snapshot requires a collection issue")
            if self.reused_from_snapshot_id is not None:
                raise ValueError("incomplete snapshot must not be marked as reused")
        else:
            if self.reused_from_snapshot_id is None:
                raise ValueError("REUSED snapshot requires reused_from_snapshot_id")
            if issues or self.checkpoint_uri is not None or self.tree_truncated:
                raise ValueError(
                    "REUSED snapshot cannot carry collection failure state"
                )

        if RepoCollectionIssue.RATE_LIMITED in issues and self.checkpoint_uri is None:
            raise ValueError("RATE_LIMITED snapshot requires checkpoint_uri")
        if self.tree_truncated != (RepoCollectionIssue.TREE_TRUNCATED in issues):
            raise ValueError("tree_truncated must agree with TREE_TRUNCATED issue")

        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError(
                "artifact paths must be unique within a repository snapshot"
            )
        return self


class GitHubRepoSnapshotBatch(StrictContractModel):
    schema_version: Literal["github-repo-snapshot/v1"]
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    generated_at: datetime
    collection_policy: RepoCollectionPolicy
    records: tuple[GitHubRepoSnapshot, ...]

    @field_validator(
        "dataset_snapshot_id",
        "pipeline_run_id",
        "collector_version",
    )
    @classmethod
    def require_non_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("generated_at", mode="before")
    @classmethod
    def require_iso_datetime_input(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _ISO_8601_DATETIME_PATTERN.match(value):
            raise ValueError("generated_at must be an ISO 8601 date-time string")
        return value

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_batch_identity_and_policy(self) -> "GitHubRepoSnapshotBatch":
        if len(self.records) > self.collection_policy.top_n_limit:
            raise ValueError("records exceed collection_policy.top_n_limit")

        seen_repo_ids: set[int] = set()
        seen_full_names: set[str] = set()
        seen_snapshot_ids: set[str] = set()
        seen_ranks: set[int] = set()
        for record in self.records:
            if record.github_repo_id in seen_repo_ids:
                raise ValueError("duplicate github_repo_id in snapshot batch")
            if record.repo_full_name.casefold() in seen_full_names:
                raise ValueError("duplicate repo_full_name in snapshot batch")
            if record.repo_snapshot_id in seen_snapshot_ids:
                raise ValueError("duplicate repo_snapshot_id in snapshot batch")
            if record.activity_rank in seen_ranks:
                raise ValueError("duplicate activity_rank in snapshot batch")
            if record.activity_rank > self.collection_policy.top_n_limit:
                raise ValueError("activity_rank exceeds collection_policy.top_n_limit")
            if record.observed_tree_entries > self.collection_policy.max_tree_entries:
                raise ValueError("observed_tree_entries exceed max_tree_entries")
            if len(record.artifacts) > self.collection_policy.max_artifact_files:
                raise ValueError("artifacts exceed max_artifact_files")
            if (
                sum(artifact.size_bytes for artifact in record.artifacts)
                > self.collection_policy.max_artifact_bytes
            ):
                raise ValueError("artifact bytes exceed max_artifact_bytes")

            seen_repo_ids.add(record.github_repo_id)
            seen_full_names.add(record.repo_full_name.casefold())
            seen_snapshot_ids.add(record.repo_snapshot_id)
            seen_ranks.add(record.activity_rank)
        return self
