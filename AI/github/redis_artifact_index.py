"""Fail-open Redis index for Weekly durable repository artifacts.

Redis is only an accelerator.  Every hit is checked against the configured
durable :class:`ArtifactStore` before it can be used by the orchestrator.
Historical callers do not construct this component.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from github.contracts import RepoArtifact

INDEX_SCHEMA_VERSION = "weekly-artifact-index/v1"
DEFAULT_TTL_SECONDS = 2_592_000
DEFAULT_NAMESPACE = "gitjob:weekly:artifact-index:v1"


@dataclass(frozen=True)
class RedisArtifactIndexHit:
    """Validated artifact references returned by a Redis lookup."""

    cache_policy_version: str
    repo_id: int
    pinned_commit_sha: str
    selected_commit_sha: str
    sha_source: str
    artifacts: tuple[RepoArtifact, ...]


@dataclass
class RedisArtifactMetrics:
    """Additive metrics for the optional Redis accelerator."""

    lookup_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    error_count: int = 0
    fail_open_count: int = 0
    durable_validation_count: int = 0
    durable_fallback_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record_latency(self, elapsed_ms: float) -> None:
        self.latencies_ms.append(max(0.0, elapsed_ms))

    def percentile_ms(self, fraction: float) -> float | None:
        """Return a nearest-rank percentile, or ``None`` with no samples."""

        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        index = max(0, math.ceil(fraction * len(ordered)) - 1)
        return round(ordered[index], 3)

    @property
    def hit_rate(self) -> float | None:
        if not self.lookup_count:
            return None
        return round(self.hit_count / self.lookup_count, 6)


class RedisArtifactIndex:
    """Index durable artifact references without becoming their source of truth.

    The client is deliberately duck-typed so offline tests do not require a
    running Redis server.  All Redis failures are treated as a miss.
    """

    def __init__(
        self,
        client: Any,
        *,
        materialization_context: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        namespace: str = DEFAULT_NAMESPACE,
        now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        monotonic: Callable[[], float] = time.perf_counter,
        metrics: RedisArtifactMetrics | None = None,
    ) -> None:
        if not materialization_context.strip():
            raise ValueError("materialization_context must not be blank")
        if type(ttl_seconds) is not int or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer")
        if not namespace.strip():
            raise ValueError("namespace must not be blank")
        self.client = client
        self.materialization_context = materialization_context
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace.rstrip(":")
        self.now = now
        self.monotonic = monotonic
        self.metrics = metrics or RedisArtifactMetrics()

    def put(
        self,
        *,
        cache_policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        sha_source: str,
        artifacts: Sequence[RepoArtifact],
    ) -> bool:
        """Publish a positive, Weekly artifact reference entry.

        Empty and partial results are intentionally not indexed.  A Redis
        write failure returns ``False`` and never affects the caller's durable
        publication result.
        """

        if not artifacts or sha_source != "CURRENT_DEFAULT_HEAD":
            return False
        payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "cache_policy_version": cache_policy_version,
            "repo_id": repo_id,
            "pinned_commit_sha": pinned_commit_sha,
            "selected_commit_sha": pinned_commit_sha,
            "sha_source": sha_source,
            "materialization_context": self.materialization_context,
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in artifacts
            ],
            "created_at": self.now().astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
        }
        try:
            self.client.set(
                self._key(
                    cache_policy_version=cache_policy_version,
                    repo_id=repo_id,
                    pinned_commit_sha=pinned_commit_sha,
                ),
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - Redis is an optional accelerator.
            self.metrics.error_count += 1
            self.metrics.fail_open_count += 1
            return False
        return True

    def lookup(
        self,
        *,
        cache_policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        sha_source: str,
        artifact_store: Any,
    ) -> RedisArtifactIndexHit | None:
        """Return a hit only after every artifact passes durable validation."""

        if sha_source != "CURRENT_DEFAULT_HEAD":
            return None
        if getattr(artifact_store, "materialization_context", None) != (
            self.materialization_context
        ):
            return None
        self.metrics.lookup_count += 1
        lookup_started = self.monotonic()
        try:
            raw = self.client.get(
                self._key(
                    cache_policy_version=cache_policy_version,
                    repo_id=repo_id,
                    pinned_commit_sha=pinned_commit_sha,
                )
            )
            if raw is None:
                self.metrics.miss_count += 1
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                self._record_miss(error=True)
                return None
            if not self._matches(
                payload,
                cache_policy_version=cache_policy_version,
                repo_id=repo_id,
                pinned_commit_sha=pinned_commit_sha,
                sha_source=sha_source,
            ):
                self.metrics.miss_count += 1
                return None
            raw_artifacts = payload.get("artifacts")
            if not isinstance(raw_artifacts, list) or not raw_artifacts:
                self._record_miss(error=True)
                return None
            artifacts = tuple(
                RepoArtifact.model_validate(value) for value in raw_artifacts
            )
            self.metrics.hit_count += 1
            self.metrics.durable_validation_count += 1
            try:
                valid = all(
                    artifact_store.validate_artifact(artifact)
                    for artifact in artifacts
                )
            except Exception:  # noqa: BLE001 - durable failure is fail-open.
                self.metrics.error_count += 1
                self.metrics.fail_open_count += 1
                self.metrics.durable_fallback_count += 1
                return None
            if not valid:
                self.metrics.durable_fallback_count += 1
                return None
            return RedisArtifactIndexHit(
                cache_policy_version=cache_policy_version,
                repo_id=repo_id,
                pinned_commit_sha=pinned_commit_sha,
                selected_commit_sha=str(payload["selected_commit_sha"]),
                sha_source=sha_source,
                artifacts=artifacts,
            )
        except Exception:  # noqa: BLE001 - invalid/unavailable index is a miss.
            self._record_miss(error=True)
            return None
        finally:
            self.metrics.record_latency(
                (self.monotonic() - lookup_started) * 1000.0
            )

    def _record_miss(self, *, error: bool) -> None:
        self.metrics.miss_count += 1
        if error:
            self.metrics.error_count += 1
            self.metrics.fail_open_count += 1

    def _matches(
        self,
        payload: Mapping[str, Any],
        *,
        cache_policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        sha_source: str,
    ) -> bool:
        return (
            payload.get("schema_version") == INDEX_SCHEMA_VERSION
            and payload.get("cache_policy_version") == cache_policy_version
            and payload.get("repo_id") == repo_id
            and payload.get("pinned_commit_sha") == pinned_commit_sha
            and payload.get("selected_commit_sha") == pinned_commit_sha
            and payload.get("sha_source") == sha_source
            and payload.get("materialization_context")
            == self.materialization_context
        )

    def _key(
        self,
        *,
        cache_policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
    ) -> str:
        policy_key = hashlib.sha256(
            cache_policy_version.encode("utf-8")
        ).hexdigest()[:16]
        context_key = hashlib.sha256(
            self.materialization_context.encode("utf-8")
        ).hexdigest()[:16]
        return (
            f"{self.namespace}:repo={repo_id}:sha={pinned_commit_sha}:"
            f"policy={policy_key}:context={context_key}"
        )
