"""Deterministic, locally checkpointed execution of public snapshot observations."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, StrictInt

from github.contracts import (
    ContentHash,
    GitHubRepoSnapshotBatch,
    RepoCollectionPolicy,
    RepoCollectionStatus,
)
from github.public_analysis import (
    MAX_CONSUMER_BATCH_BYTES,
    PUBLIC_PARSER_VERSION,
    ArtifactReader,
    OutputModel,
    PublicBatchResult,
    PublicRepoResult,
    PublicTechnologyCount,
    analyze_public_batch,
)
from registry.mapper import RegistryMapper
from trend.contracts import TrendStatus

PIPELINE_VERSION = "c-public-partition-pipeline/v1"
MAX_CHECKPOINT_FILE_BYTES = 256_000_000
RETRYABLE_ARTIFACT_REASONS = frozenset(
    {"ARTIFACT_UNAVAILABLE", "HASH_MISMATCH", "SIZE_MISMATCH"}
)


class PipelineCheckpointError(ValueError):
    """Stored state cannot safely be reused; no automatic reset is performed."""


class PipelineBusyError(RuntimeError):
    """Another process owns this checkpoint directory."""


class PipelineExecutionError(RuntimeError):
    """Execution stopped without publishing a complete dataset."""


class PartitionPlan(OutputModel):
    index: StrictInt = Field(ge=0)
    github_repo_ids: tuple[StrictInt, ...]
    declared_bytes: StrictInt = Field(ge=0)
    readable_bytes: StrictInt = Field(ge=0)
    input_sha256: ContentHash


class PublicPipelinePlan(OutputModel):
    schema_version: Literal["c-public-partition-pipeline/v1"] = PIPELINE_VERSION
    input_sha256: ContentHash
    source_sha256: ContentHash | None
    manifest_sha256: ContentHash | None
    registry_sha256: ContentHash | None
    dataset_snapshot_id: str
    pipeline_run_id: str
    collector_version: str
    generated_at: str
    collection_policy: RepoCollectionPolicy
    collection_policy_sha256: ContentHash
    parser_version: str = PUBLIC_PARSER_VERSION
    registry_version: str
    include_partial: StrictBool
    max_records: StrictInt = Field(gt=0)
    max_declared_bytes: StrictInt = Field(gt=0, le=MAX_CONSUMER_BATCH_BYTES)
    total_repo_count: StrictInt = Field(ge=0)
    partitions: tuple[PartitionPlan, ...]

    @property
    def pipeline_id(self) -> str:
        return _digest(_canonical(self))


class PipelineFailure(OutputModel):
    partition_index: StrictInt = Field(ge=0)
    code: str


class PipelineCheckpoint(OutputModel):
    plan: PublicPipelinePlan
    completed: dict[str, ContentHash] = Field(default_factory=dict)
    failure: PipelineFailure | None = None
    final_sha256: ContentHash | None = None


class PipelineProgress(OutputModel):
    pipeline_id: str
    status: Literal["IN_PROGRESS", "COMPLETED"]
    total_partitions: int
    completed_partitions: int
    executed_partitions: int
    reused_partitions: int
    result: PublicBatchResult | None = None
    final_path: Path | None = None


def _canonical(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validated_batch(batch: GitHubRepoSnapshotBatch) -> GitHubRepoSnapshotBatch:
    # Input contracts are mutable and model_copy can bypass their validators.
    return GitHubRepoSnapshotBatch.model_validate(batch.model_dump(mode="json"))


def _allowed(include_partial: bool) -> set[RepoCollectionStatus]:
    if type(include_partial) is not bool:
        raise ValueError("include_partial must be an explicit boolean")
    statuses = {RepoCollectionStatus.COMPLETE, RepoCollectionStatus.REUSED}
    if include_partial:
        statuses.add(RepoCollectionStatus.PARTIAL)
    return statuses


def plan_public_pipeline(
    batch: GitHubRepoSnapshotBatch,
    mapper: RegistryMapper,
    *,
    include_partial: bool = False,
    max_records: int = 500,
    max_declared_bytes: int = 50_000_000,
    source_sha256: str | None = None,
    manifest_sha256: str | None = None,
    registry_sha256: str | None = None,
) -> PublicPipelinePlan:
    """Plan without reading artifacts; bind the complete validated source payload."""
    batch = _validated_batch(batch)
    allowed = _allowed(include_partial)
    if type(max_records) is not int or max_records < 1:
        raise ValueError("max_records must be a positive integer")
    if (
        type(max_declared_bytes) is not int
        or not 1 <= max_declared_bytes <= MAX_CONSUMER_BATCH_BYTES
    ):
        raise ValueError("invalid partition declared-byte limit")
    partitions = []
    pending = []
    readable_bytes = 0

    def append_partition():
        partitions.append(
            PartitionPlan(
                index=len(partitions),
                github_repo_ids=tuple(row.github_repo_id for row in pending),
                declared_bytes=sum(
                    a.size_bytes for row in pending for a in row.artifacts
                ),
                readable_bytes=readable_bytes,
                input_sha256=_digest(
                    _canonical([row.model_dump(mode="json") for row in pending])
                ),
            )
        )

    for row in sorted(batch.records, key=lambda item: item.activity_rank):
        weight = (
            sum(a.size_bytes for a in row.artifacts)
            if row.collection_status in allowed
            else 0
        )
        if weight > max_declared_bytes:
            raise ValueError("one repository exceeds the partition byte limit")
        if pending and (
            len(pending) >= max_records or readable_bytes + weight > max_declared_bytes
        ):
            append_partition()
            pending, readable_bytes = [], 0
        pending.append(row)
        readable_bytes += weight
    if pending:
        append_partition()
    return PublicPipelinePlan(
        input_sha256=_digest(_canonical(batch)),
        source_sha256=source_sha256,
        manifest_sha256=manifest_sha256,
        registry_sha256=registry_sha256,
        dataset_snapshot_id=batch.dataset_snapshot_id,
        pipeline_run_id=batch.pipeline_run_id,
        collector_version=batch.collector_version,
        generated_at=batch.generated_at.isoformat(),
        collection_policy=batch.collection_policy,
        collection_policy_sha256=_digest(_canonical(batch.collection_policy)),
        registry_version=mapper.registry_version,
        include_partial=include_partial,
        max_records=max_records,
        max_declared_bytes=max_declared_bytes,
        total_repo_count=len(batch.records),
        partitions=tuple(partitions),
    )


def _metadata(batch: GitHubRepoSnapshotBatch, registry_version: str) -> dict:
    return {
        "dataset_snapshot_id": batch.dataset_snapshot_id,
        "pipeline_run_id": batch.pipeline_run_id,
        "collector_version": batch.collector_version,
        "collection_policy_version": batch.collection_policy.policy_version,
        "generated_at": batch.generated_at.isoformat(),
        "registry_version": registry_version,
        "parser_version": PUBLIC_PARSER_VERSION,
    }


def _validate_result(
    result: PublicBatchResult,
    batch: GitHubRepoSnapshotBatch,
    mapper: RegistryMapper,
    include_partial: bool,
) -> PublicBatchResult:
    result = PublicBatchResult.model_validate_json(result.model_dump_json())
    if result.include_partial != include_partial or any(
        getattr(result, name) != value
        for name, value in _metadata(batch, mapper.registry_version).items()
    ):
        raise ValueError("partition result metadata does not match input")
    originals = {row.github_repo_id: row for row in batch.records}
    seen = set()
    for row in result.records:
        if row.github_repo_id in seen:
            raise ValueError("duplicate repository in partition result")
        seen.add(row.github_repo_id)
        original = originals.get(row.github_repo_id)
        if original is None:
            raise ValueError("partition repository is outside input coverage")
        expected = original.model_dump(mode="json")
        actual = row.model_dump(mode="json")
        if any(
            actual[key] != value
            for key, value in expected.items()
            if key != "artifacts"
        ):
            raise ValueError("partition repository provenance differs from input")
        if row.eligible != (original.collection_status in _allowed(include_partial)):
            raise ValueError("partition eligibility differs from input policy")
        identity_fields = ("path", "uri", "content_hash", "size_bytes")
        if [tuple(a[key] for key in identity_fields) for a in actual["artifacts"]] != [
            tuple(a[key] for key in identity_fields) for a in expected["artifacts"]
        ]:
            raise ValueError("partition artifact provenance differs from input")
        artifact_by_path = {a.path: a for a in row.artifacts}
        for observation in row.observations:
            artifact = artifact_by_path.get(observation.path)
            if (
                artifact is None
                or artifact.uri != observation.uri
                or artifact.content_hash != observation.content_hash
                or artifact.status
                not in {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
                or not mapper.has_active_technology(observation.tech_id)
            ):
                raise ValueError(
                    "observation lacks verified artifact/Registry provenance"
                )
        if any(item.path not in artifact_by_path for item in row.unresolved):
            raise ValueError("unresolved observation lacks artifact provenance")
    return result


def merge_public_partitions(
    batch: GitHubRepoSnapshotBatch,
    results: Iterable[PublicBatchResult],
    mapper: RegistryMapper,
    *,
    include_partial: bool = False,
) -> PublicBatchResult:
    """Rebuild whole-dataset distinct counts; never average partition ratios."""
    batch = _validated_batch(batch)
    _allowed(include_partial)
    by_id: dict[int, PublicRepoResult] = {}
    for result in results:
        result = _validate_result(result, batch, mapper, include_partial)
        for row in result.records:
            if row.github_repo_id in by_id:
                raise ValueError("duplicate repository across partitions")
            by_id[row.github_repo_id] = row
    if set(by_id) != {row.github_repo_id for row in batch.records}:
        raise ValueError("partition coverage does not match complete input")
    records = tuple(sorted(by_id.values(), key=lambda row: row.activity_rank))
    observed = defaultdict(set)
    denominator = sum(row.included_in_denominator for row in records)
    for row in records:
        if row.included_in_denominator:
            for observation in row.observations:
                observed[observation.tech_id].add(row.github_repo_id)
    statuses = {row.status for row in records}
    status = TrendStatus.INSUFFICIENT_DATA
    for uniform in (TrendStatus.READY, TrendStatus.FAILED, TrendStatus.NOT_SUPPORTED):
        if statuses == {uniform}:
            status = uniform
    return PublicBatchResult(
        **_metadata(batch, mapper.registry_version),
        status=status,
        include_partial=include_partial,
        total_repo_count=len(records),
        eligible_repo_count=sum(row.eligible for row in records),
        sample_repo_count=denominator,
        analyzed_repo_count=denominator,
        excluded_repo_count=len(records) - denominator,
        records=records,
        technologies=tuple(
            PublicTechnologyCount(
                tech_id=tech_id,
                observed_repo_count=len(ids),
                sample_repo_count=denominator,
                observation_ratio=len(ids) / denominator,
                github_repo_ids=tuple(sorted(ids)),
            )
            for tech_id, ids in sorted(observed.items())
        ),
    )


def _safe_file(root: Path, name: str) -> Path:
    target = root / name
    if target.is_symlink() or target.resolve().parent != root:
        raise PipelineCheckpointError(
            "checkpoint files must stay inside owned directory"
        )
    return target


def _replace_file(source: Path, destination: Path) -> None:
    for attempt in range(3):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if (
                os.name != "nt"
                or getattr(error, "winerror", None) not in {5, 32, 33}
                or attempt == 2
            ):
                raise
            time.sleep(0.05 * (attempt + 1))


def _atomic_write(root: Path, name: str, content: bytes) -> None:
    if len(content) > MAX_CHECKPOINT_FILE_BYTES:
        raise PipelineCheckpointError("checkpoint output exceeds local file limit")
    target = _safe_file(root, name)
    temporary = root / f".writing-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_file(temporary, target)
        if os.name != "nt":
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read_file(root: Path, name: str) -> bytes:
    try:
        with _safe_file(root, name).open("rb") as stream:
            content = stream.read(MAX_CHECKPOINT_FILE_BYTES + 1)
        if len(content) > MAX_CHECKPOINT_FILE_BYTES:
            raise PipelineCheckpointError("checkpoint file exceeds read limit")
        return content
    except OSError as error:
        raise PipelineCheckpointError(
            "checkpoint file missing or inaccessible"
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PipelineCheckpointError("duplicate key in checkpoint JSON")
        result[key] = value
    return result


def _json(content: bytes) -> object:
    try:
        return json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        raise PipelineCheckpointError("invalid checkpoint JSON") from error


@contextmanager
def _directory_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    path = _safe_file(root, ".public-pipeline.lock")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            acquire = lambda: fcntl.flock(
                handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            release = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as error:
            raise PipelineBusyError(
                "checkpoint directory is already running"
            ) from error
        try:
            yield
        finally:
            release()


def _save(root: Path, checkpoint: PipelineCheckpoint) -> None:
    _atomic_write(root, "checkpoint.json", _canonical(checkpoint))


def _load_checkpoint(root: Path, plan: PublicPipelinePlan) -> PipelineCheckpoint:
    path = _safe_file(root, "checkpoint.json")
    if not path.exists():
        if any(root.glob("partition-*.json")) or any(
            (root / name).exists() for name in ("final.json", "_SUCCESS.json")
        ):
            raise PipelineCheckpointError("managed output exists without checkpoint")
        checkpoint = PipelineCheckpoint(plan=plan)
        _save(root, checkpoint)
        return checkpoint
    try:
        checkpoint = PipelineCheckpoint.model_validate(
            _json(_read_file(root, path.name))
        )
    except ValueError as error:
        raise PipelineCheckpointError("invalid checkpoint structure") from error
    if checkpoint.plan != plan:
        raise PipelineCheckpointError(
            "checkpoint is bound to a different input or policy"
        )
    if not set(checkpoint.completed) <= {str(p.index) for p in plan.partitions}:
        raise PipelineCheckpointError("checkpoint contains unknown partition indices")
    if checkpoint.final_sha256 is not None and len(checkpoint.completed) != len(
        plan.partitions
    ):
        raise PipelineCheckpointError("final state lacks complete partition coverage")
    if len(checkpoint.completed) != len(plan.partitions) and any(
        (root / name).exists() for name in ("final.json", "_SUCCESS.json")
    ):
        raise PipelineCheckpointError("incomplete run has unexpected final output")
    return checkpoint


def run_public_pipeline(
    batch: GitHubRepoSnapshotBatch,
    reader: ArtifactReader,
    mapper: RegistryMapper,
    checkpoint_dir: Path,
    *,
    include_partial: bool = False,
    max_records: int = 500,
    max_declared_bytes: int = 50_000_000,
    source_sha256: str | None = None,
    manifest_sha256: str | None = None,
    registry_sha256: str | None = None,
    max_new_partitions: int | None = None,
) -> PipelineProgress:
    """Run/resume a single local writer; only return final output after full validation."""
    if max_new_partitions is not None and (
        type(max_new_partitions) is not int or max_new_partitions < 0
    ):
        raise ValueError("max_new_partitions must be a nonnegative integer or None")
    batch = _validated_batch(batch)
    plan = plan_public_pipeline(
        batch,
        mapper,
        include_partial=include_partial,
        max_records=max_records,
        max_declared_bytes=max_declared_bytes,
        source_sha256=source_sha256,
        manifest_sha256=manifest_sha256,
        registry_sha256=registry_sha256,
    )
    root = Path(checkpoint_dir).resolve()
    originals = {row.github_repo_id: row for row in batch.records}
    with _directory_lock(root):
        checkpoint = _load_checkpoint(root, plan)
        results = []
        reused = executed = 0
        # Verify every referenced completion before reading any new artifacts.
        for part in plan.partitions:
            key = str(part.index)
            if key not in checkpoint.completed:
                continue
            body = _read_file(root, f"partition-{part.index:06d}.json")
            if _digest(body) != checkpoint.completed[key]:
                raise PipelineCheckpointError("completed partition hash mismatch")
            subset = batch.model_copy(
                update={
                    "records": tuple(originals[item] for item in part.github_repo_ids)
                }
            )
            try:
                result = _validate_result(
                    PublicBatchResult.model_validate(_json(body)),
                    subset,
                    mapper,
                    include_partial,
                )
                if (
                    tuple(row.github_repo_id for row in result.records)
                    != part.github_repo_ids
                ):
                    raise ValueError("completed partition coverage mismatch")
                if any(
                    a.reason in RETRYABLE_ARTIFACT_REASONS
                    for r in result.records
                    for a in r.artifacts
                ):
                    raise ValueError(
                        "incomplete artifact read cannot be a completed partition"
                    )
            except ValueError as error:
                raise PipelineCheckpointError(
                    "completed partition validation failed"
                ) from error
            results.append(result)
            reused += 1
        for part in plan.partitions:
            if str(part.index) in checkpoint.completed:
                continue
            if max_new_partitions is not None and executed >= max_new_partitions:
                break
            subset = batch.model_copy(
                update={
                    "records": tuple(originals[item] for item in part.github_repo_ids)
                }
            )
            try:
                if mapper.registry_version != plan.registry_version:
                    raise ValueError("Registry version changed during execution")
                result = analyze_public_batch(
                    subset, reader, mapper, include_partial=include_partial
                )
                if mapper.registry_version != plan.registry_version:
                    raise ValueError("Registry version changed during execution")
                result = _validate_result(result, subset, mapper, include_partial)
                if (
                    tuple(row.github_repo_id for row in result.records)
                    != part.github_repo_ids
                ):
                    raise ValueError("partition execution coverage mismatch")
                if any(
                    a.reason in RETRYABLE_ARTIFACT_REASONS
                    for r in result.records
                    for a in r.artifacts
                ):
                    raise PipelineExecutionError(
                        "partition artifact verification incomplete"
                    )
            except Exception as error:
                checkpoint = checkpoint.model_copy(
                    update={
                        "failure": PipelineFailure(
                            partition_index=part.index,
                            code="PARTITION_EXECUTION_FAILED",
                        )
                    }
                )
                _save(root, checkpoint)
                raise PipelineExecutionError(
                    f"partition {part.index} incomplete; rerun the same checkpoint to retry"
                ) from error
            body = _canonical(result)
            _atomic_write(root, f"partition-{part.index:06d}.json", body)
            checkpoint = checkpoint.model_copy(
                update={
                    "completed": {
                        **checkpoint.completed,
                        str(part.index): _digest(body),
                    },
                    "failure": None,
                }
            )
            _save(root, checkpoint)
            results.append(result)
            executed += 1
        progress = {
            "pipeline_id": plan.pipeline_id,
            "total_partitions": len(plan.partitions),
            "completed_partitions": len(checkpoint.completed),
            "executed_partitions": executed,
            "reused_partitions": reused,
        }
        if len(checkpoint.completed) != len(plan.partitions):
            if any((root / name).exists() for name in ("final.json", "_SUCCESS.json")):
                raise PipelineCheckpointError(
                    "incomplete run has unexpected final output"
                )
            return PipelineProgress(**progress, status="IN_PROGRESS")
        final = merge_public_partitions(
            batch, results, mapper, include_partial=include_partial
        )
        body = _canonical(final)
        final_hash = _digest(body)
        marker = {
            "schema_version": PIPELINE_VERSION,
            "pipeline_id": plan.pipeline_id,
            "input_sha256": plan.input_sha256,
            "final_file": "final.json",
            "final_sha256": final_hash,
            "total_repo_count": len(batch.records),
            "partition_count": len(plan.partitions),
        }
        if checkpoint.final_sha256 is not None:
            if (
                checkpoint.final_sha256 != final_hash
                or _read_file(root, "final.json") != body
            ):
                raise PipelineCheckpointError(
                    "final result differs from verified partitions"
                )
        else:
            _atomic_write(root, "final.json", body)
            checkpoint = checkpoint.model_copy(update={"final_sha256": final_hash})
            _save(root, checkpoint)
        if _safe_file(root, "_SUCCESS.json").exists():
            if _json(_read_file(root, "_SUCCESS.json")) != marker:
                raise PipelineCheckpointError("completion marker mismatch")
        else:
            _atomic_write(root, "_SUCCESS.json", _canonical(marker))
        return PipelineProgress(
            **progress, status="COMPLETED", result=final, final_path=root / "final.json"
        )
