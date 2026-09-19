"""Fail-open Redis cache for parsed artifact evidence (S15P21E102-347).

`redis_artifact_index` caches *which* artifacts a Weekly repository has.  This
caches *what one artifact says*, which is the expensive half of C's public
intake: a 2026-08-31 measurement put 96.0% of the per-artifact cost in the
WebHDFS content GET and 3.8% in the parser, so a week that re-reads the same
fixed-cohort artifact pays 12.8 ms to learn something it already knew.  The
cohort is fixed across the 28-week backfill, so the same artifact is parsed
once per week instead of once.

Redis is not the source of truth here either.  A hit is usable only after the
durable object has been seen in the same run, and the caller decides what
"seen" means -- see `DirectoryArtifactValidator`, which is how Mode C keeps
that check without paying for it per artifact.

### Why the value is the parser output, not the mapped technologies

`public_analysis._read_candidates` returns `(candidates, unresolved, analysis)`
before `RegistryMapper.map` runs.  Caching at that boundary keeps the registry
out of the cached bytes, so a registry change takes effect on the next run
rather than waiting for entries to expire.  `registry_version` is still part of
the key: it costs nothing while the registry is stable and means a stale entry
cannot outlive a registry change even if this reasoning is later wrong.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

ANALYSIS_CACHE_SCHEMA_VERSION = "weekly-artifact-analysis/v1"
DEFAULT_TTL_SECONDS = 2_592_000
DEFAULT_NAMESPACE = "gitjob:weekly:artifact-analysis:v1"


@dataclass
class ArtifactAnalysisCacheMetrics:
    """Additive metrics; names match the Redis index so dashboards line up."""

    lookup_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    error_count: int = 0
    fail_open_count: int = 0
    durable_validation_count: int = 0
    durable_fallback_count: int = 0
    listing_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record_latency(self, elapsed_ms: float) -> None:
        self.latencies_ms.append(max(0.0, elapsed_ms))

    def percentile_ms(self, fraction: float) -> float | None:
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


class DirectoryArtifactValidator:
    """Confirm published artifacts exist, one LISTSTATUS per directory.

    A cache hit still has to answer "is the durable object there?".  Asking per
    artifact costs 2.3 ms (GETFILESTATUS); asking per directory costs 1.6 ms and
    answers for every artifact under it, which on the 2026-08-31 cohort is 3.3
    artifacts each.  That is the whole difference between a cache that pays back
    5x and one that pays back 26x.

    A listing is fetched at most once per directory per instance.  Failures are
    remembered as "unknown", not as "absent": the caller then falls back to the
    durable read, which is the same thing it would have done without a cache.
    """

    def __init__(self, reader: Any, *, max_entries: int = 4096) -> None:
        self.reader = reader
        self.max_entries = max_entries
        self._listings: dict[str, dict[str, int] | None] = {}
        self.listing_count = 0

    @staticmethod
    def _split(uri: str) -> tuple[str, str]:
        directory, _, name = uri.rpartition("/")
        return directory, name

    def _listing(self, directory: str) -> dict[str, int] | None:
        if directory in self._listings:
            return self._listings[directory]
        entries: dict[str, int] | None
        try:
            self.listing_count += 1
            entries = {
                str(entry["pathSuffix"]): int(entry.get("length", -1))
                for entry in self.reader.list_directory(
                    directory, max_entries=self.max_entries
                )
                if entry.get("type") == "FILE"
            }
        except Exception:  # noqa: BLE001 - an unreadable listing is not a verdict.
            entries = None
        self._listings[directory] = entries
        return entries

    def verify(self, uri: str, *, size_bytes: int) -> bool:
        """True only when the listing positively shows this name at this size."""

        directory, name = self._split(uri)
        if not directory or not name:
            return False
        entries = self._listing(directory)
        if entries is None:
            return False
        return entries.get(name) == size_bytes


class RedisArtifactAnalysisCache:
    """Read-through cache keyed by the artifact's own verified identity.

    The client is duck-typed so tests do not need a Redis server, and every
    Redis failure -- GET, SET, malformed value -- is a miss.  With Redis empty
    the pipeline computes exactly what it computed before.
    """

    def __init__(
        self,
        client: Any,
        *,
        registry_version: str,
        parser_version: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        namespace: str = DEFAULT_NAMESPACE,
        now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        monotonic: Callable[[], float] = time.perf_counter,
        metrics: ArtifactAnalysisCacheMetrics | None = None,
    ) -> None:
        if not str(registry_version).strip():
            raise ValueError("registry_version must not be blank")
        if not str(parser_version).strip():
            raise ValueError("parser_version must not be blank")
        if type(ttl_seconds) is not int or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer")
        if not namespace.strip():
            raise ValueError("namespace must not be blank")
        self.client = client
        self.registry_version = registry_version
        self.parser_version = parser_version
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace.rstrip(":")
        self.now = now
        self.monotonic = monotonic
        self.metrics = metrics or ArtifactAnalysisCacheMetrics()

    @staticmethod
    def companion_digest(companion_files: Mapping[str, bytes] | None) -> str:
        """Identity of the companion set a parse may consult.

        Only `libs.versions.toml` reaches the parser as a companion today, so
        this is the empty digest for almost every artifact.  It is still part of
        the key because a Gradle catalog changing under a build file changes
        what that build file resolves to.
        """

        digest = hashlib.sha256()
        for path in sorted((companion_files or {}).keys()):
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(
                hashlib.sha256((companion_files or {})[path])
                .hexdigest()
                .encode("ascii")
            )
            digest.update(b"\0")
        return digest.hexdigest()[:16]

    def lookup(
        self,
        *,
        content_hash: str,
        path: str,
        size_bytes: int,
        uri: str,
        companion_digest: str,
        validator: DirectoryArtifactValidator | None,
    ) -> dict[str, Any] | None:
        """Return the cached parse only after the durable object is confirmed."""

        self.metrics.lookup_count += 1
        started = self.monotonic()
        try:
            raw = self.client.get(
                self._key(
                    content_hash=content_hash,
                    path=path,
                    companion_digest=companion_digest,
                )
            )
            if raw is None:
                self.metrics.miss_count += 1
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping) or not self._matches(
                payload, content_hash=content_hash, path=path, size_bytes=size_bytes
            ):
                self._record_miss(error=True)
                return None
            # Durable validation is not optional; without a validator a hit is
            # unusable, because nothing in this process has seen the object.
            if validator is None:
                self.metrics.durable_fallback_count += 1
                self.metrics.miss_count += 1
                return None
            self.metrics.durable_validation_count += 1
            if not validator.verify(uri, size_bytes=size_bytes):
                self.metrics.durable_fallback_count += 1
                self.metrics.miss_count += 1
                return None
            self.metrics.hit_count += 1
            return dict(payload)
        except Exception:  # noqa: BLE001 - an unusable cache is a miss.
            self._record_miss(error=True)
            return None
        finally:
            self.metrics.record_latency((self.monotonic() - started) * 1000.0)

    def put(
        self,
        *,
        content_hash: str,
        path: str,
        size_bytes: int,
        companion_digest: str,
        candidates: Sequence[Mapping[str, Any]],
        unresolved: Sequence[Mapping[str, Any]],
        analysis: Mapping[str, Any],
    ) -> bool:
        """Best-effort write; a refusal never changes the caller's result."""

        payload = {
            "schema_version": ANALYSIS_CACHE_SCHEMA_VERSION,
            "registry_version": self.registry_version,
            "parser_version": self.parser_version,
            "content_hash": content_hash,
            "path": path,
            "size_bytes": size_bytes,
            "companion_digest": companion_digest,
            "candidates": list(candidates),
            "unresolved": list(unresolved),
            "analysis": dict(analysis),
            "created_at": self.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        try:
            self.client.set(
                self._key(
                    content_hash=content_hash,
                    path=path,
                    companion_digest=companion_digest,
                ),
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - Redis runs noeviction; a full instance
            # refuses writes, and that must not fail a publication.
            self.metrics.error_count += 1
            self.metrics.fail_open_count += 1
            return False
        return True

    def _record_miss(self, *, error: bool) -> None:
        self.metrics.miss_count += 1
        if error:
            self.metrics.error_count += 1
            self.metrics.fail_open_count += 1

    def _matches(
        self,
        payload: Mapping[str, Any],
        *,
        content_hash: str,
        path: str,
        size_bytes: int,
    ) -> bool:
        return (
            payload.get("schema_version") == ANALYSIS_CACHE_SCHEMA_VERSION
            and payload.get("registry_version") == self.registry_version
            and payload.get("parser_version") == self.parser_version
            and payload.get("content_hash") == content_hash
            and payload.get("path") == path
            and payload.get("size_bytes") == size_bytes
            and isinstance(payload.get("candidates"), list)
            and isinstance(payload.get("unresolved"), list)
            and isinstance(payload.get("analysis"), Mapping)
        )

    def _key(self, *, content_hash: str, path: str, companion_digest: str) -> str:
        path_key = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
        registry_key = hashlib.sha256(
            self.registry_version.encode("utf-8")
        ).hexdigest()[:16]
        parser_key = hashlib.sha256(self.parser_version.encode("utf-8")).hexdigest()[
            :16
        ]
        return (
            f"{self.namespace}:hash={content_hash}:path={path_key}:"
            f"registry={registry_key}:parser={parser_key}:"
            f"companion={companion_digest}"
        )


def preload_directories(
    validator: DirectoryArtifactValidator, uris: Iterable[str]
) -> int:
    """Warm one listing per distinct directory before the artifact loop.

    Returns the number of listings fetched, which is what the run summary
    reports as `LISTSTATUS_CALLS`.
    """

    before = validator.listing_count
    for directory in sorted({uri.rpartition("/")[0] for uri in uris if "/" in uri}):
        # Same module's own state; the leading underscore marks it internal
        # to callers, not to this helper.
        validator._listing(directory)
    return validator.listing_count - before


@dataclass(frozen=True)
class ArtifactAnalysisCacheContext:
    """One batch's cache plus the listing state that makes its hits usable.

    Held for the length of a batch and dropped with it. A directory listing is
    a claim about right now, so keeping it past the run it was taken for would
    slowly turn a fact into an assumption.
    """

    cache: RedisArtifactAnalysisCache
    validator: DirectoryArtifactValidator

    @classmethod
    def build(
        cls,
        client: Any,
        reader: Any,
        *,
        registry_version: str,
        parser_version: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> ArtifactAnalysisCacheContext:
        return cls(
            cache=RedisArtifactAnalysisCache(
                client,
                registry_version=registry_version,
                parser_version=parser_version,
                ttl_seconds=ttl_seconds,
                namespace=namespace,
            ),
            validator=DirectoryArtifactValidator(reader),
        )

    def preload(self, uris: Iterable[str]) -> int:
        fetched = preload_directories(self.validator, uris)
        self.cache.metrics.listing_count = self.validator.listing_count
        return fetched


def create_redis_client() -> Any:
    """Return a Redis client, or ``None`` when one cannot be made.

    Deliberately the same environment contract as
    `repo_fetch_orchestrator.create_redis_artifact_index`, including the short
    socket timeouts: a cache that blocks is worse than no cache. The DB is
    shared with the Weekly artifact index and kept apart by namespace, so this
    does not claim a new database number of its own.
    """

    try:
        import redis

        url = os.environ.get("WEEKLY_REDIS_URL")
        if url:
            return redis.Redis.from_url(
                url,
                decode_responses=False,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
        host = os.environ.get("REDIS_HOST")
        if not host:
            return None
        return redis.Redis(
            host=host,
            port=int(os.environ.get("REDIS_PORT", "6379")),
            db=int(os.environ.get("WEEKLY_REDIS_DB", "1")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            decode_responses=False,
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
        )
    except (ImportError, TypeError, ValueError):
        return None
