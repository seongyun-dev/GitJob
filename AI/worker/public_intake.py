"""Publish one provenance-wrapped public result only after every partition completes."""

import logging
from pathlib import Path

from github.public_analysis import ArtifactReader
from github.public_pipeline import plan_public_pipeline, run_public_pipeline
from github.snapshot_input import PublishedSnapshot
from registry.contracts import TechnologyRegistry
from registry.mapper import RegistryMapper
from worker.lease import LeaseHeartbeat
from worker.store import Artifact, ComputeStore, digest

LOGGER = logging.getLogger(__name__)
PUBLICATION_SCHEMA = "c-public-published-result/v1"


class PublicPipelineConsumer:
    """Consume an injected verified publication; network discovery belongs to the factory."""

    def __init__(
        self,
        published: PublishedSnapshot,
        reader: ArtifactReader,
        registry: TechnologyRegistry,
        checkpoint_dir: Path,
        registry_sha256: str,
        store: ComputeStore,
        *,
        include_partial: bool = False,
        max_records: int = 500,
        max_declared_bytes: int = 50_000_000,
    ):
        # Snapshot contracts contain mutable nested values: own a validated copy.
        self._published = PublishedSnapshot.model_validate_json(
            published.model_dump_json()
        )
        self._mapper = RegistryMapper(
            TechnologyRegistry.model_validate_json(registry.model_dump_json())
        )
        self._reader = reader
        self._checkpoint_dir = Path(checkpoint_dir)
        self._store = store
        self._options = {
            "include_partial": include_partial,
            "max_records": max_records,
            "max_declared_bytes": max_declared_bytes,
            "source_sha256": self._published.source_sha256,
            "manifest_sha256": self._published.manifest_sha256,
            "registry_sha256": registry_sha256,
        }
        self._plan = plan_public_pipeline(
            self._published.batch, self._mapper, **self._options
        )
        self.pipeline_id = self._plan.pipeline_id
        self._publication = {
            "source_root": self._published.source_root,
            "source_sha256": self._published.source_sha256,
            "manifest_sha256": self._published.manifest_sha256,
            "summary_sha256": self._published.summary_sha256,
            "failures_sha256": self._published.failures_sha256,
            "quality": self._published.quality.model_dump(mode="json"),
            "pipeline_id": self.pipeline_id,
        }
        self._identity = {
            "schema_version": PUBLICATION_SCHEMA,
            "publication": self._publication,
        }
        self.event_id = "public-intake-" + digest(self._identity)
        self.stream = (
            PUBLICATION_SCHEMA
            + ":"
            + digest(
                {
                    "source_root": self._published.source_root,
                    "pipeline_id": self.pipeline_id,
                }
            )
        )

    def poll_once(self, max_new_partitions: int | None = 1) -> dict:
        progress = run_public_pipeline(
            self._published.batch,
            self._reader,
            self._mapper,
            self._checkpoint_dir,
            max_new_partitions=max_new_partitions,
            **self._options,
        )
        if progress.pipeline_id != self.pipeline_id:
            raise ValueError("public pipeline identity changed during consumption")
        report = {
            "pipeline_id": self.pipeline_id,
            "total_partitions": progress.total_partitions,
            "completed_partitions": progress.completed_partitions,
            "executed_partitions": progress.executed_partitions,
            "reused_partitions": progress.reused_partitions,
        }
        if progress.status != "COMPLETED":
            return {**report, "status": "IN_PROGRESS", "results": []}
        if progress.result is None:
            raise ValueError("completed pipeline lacks final result")
        result = progress.result.model_dump(mode="json")
        artifact = Artifact(
            kind="PUBLIC_GITHUB",
            owner=None,
            stream=self.stream,
            payload={**self._identity, "result": result},
        )
        ticket = self._store.claim(
            event_id=self.event_id,
            kind="PUBLIC_REPO",
            owner=None,
            occurred_at=self._published.batch.generated_at,
            request={**self._identity, "result_sha256": digest(result)},
        )
        report.update(
            event_id=self.event_id,
            result_quality_status=progress.result.status.value,
        )
        if ticket.status == "COMPLETED":
            return {**report, "status": "COMPLETED", "results": ticket.results}
        if ticket.token is None:
            return {**report, "status": "PREPARING", "results": []}
        try:
            with LeaseHeartbeat(self._store, ticket):
                results = self._store.complete(ticket, [artifact])
        except Exception:
            try:
                # This is token/state fenced: a committed-but-unacknowledged event
                # remains COMPLETED, and an obsolete lease cannot fail its successor.
                self._store.fail(ticket, "PUBLIC_PUBLICATION_FAILED")
            except Exception:  # noqa: BLE001 - preserve original failure without sensitive logs.
                LOGGER.warning(
                    "Public publication failure recording unavailable; retry required"
                )
            raise
        return {**report, "status": "COMPLETED", "results": results}
