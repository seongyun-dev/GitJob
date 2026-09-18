"""Internal C compute API. Authentication/serving for end users remains in B."""

import hmac
import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.conninfo import make_conninfo
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from common.health import create_health_app
from github.contracts import GitHubRepoSnapshotBatch
from job.classifier import JOB_REQUIREMENT_PARSER_VERSION
from job.cohort import (
    JOB_QUALITY_VERSION,
    CohortCriteria,
    CohortPurpose,
    JobCohort,
    normalize_cohort_filters,
)
from job.contracts import JobAnalysisInputBatch
from job.demand import JOB_DEMAND_AGGREGATION_VERSION, DemandSnapshot
from recommendation.evidence import EvidenceAnalysis
from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import RegistryMapper
from trend.archive import PeriodGranularity
from worker.archive_input import ArchiveInputUnavailable, ArchiveTrendFields
from worker.lease import LeaseHeartbeat
from worker.store import (
    Artifact,
    ComputeStore,
    IdempotencyConflict,
    LeaseLost,
    StoredMatchingIntegrityError,
    digest,
)

LOGGER = logging.getLogger(__name__)
Identifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
SnapshotId = Annotated[str, StringConstraints(strict=True, pattern=r"^c-[0-9a-f]{64}$")]
REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registry/data"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["c-compute-event/v1"]
    event_id: Identifier
    trace_id: Identifier
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at requires timezone")
        return value.astimezone(UTC)


class JobCompleted(Event):
    batch: JobAnalysisInputBatch
    criteria: CohortCriteria


class AnalysisCompleted(Event):
    user_id: Identifier
    analysis_id: Identifier
    cohort_snapshot_id: SnapshotId
    evidence: EvidenceAnalysis


class PublicReposCompleted(Event):
    batch: GitHubRepoSnapshotBatch
    include_partial: StrictBool = False


class TrendCompleted(Event):
    tech_id: Annotated[
        str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ]
    source: Literal["JOB", "GITHUB"]
    periods: tuple[str, ...] = Field(min_length=1, max_length=48)
    demand_snapshot_ids: tuple[SnapshotId, ...] = ()
    csv_text: str | None = None
    source_version: str | None = None
    source_uri: str | None = None

    @model_validator(mode="after")
    def require_job_scope_reference(self) -> "TrendCompleted":
        # JOB stream identity comes from the referenced Demand criteria. Without
        # one there is no target role/filter identity under which the result can
        # later be resolved, so storing a PREPARING orphan is never useful.
        if self.source == "JOB" and not self.demand_snapshot_ids:
            raise ValueError("JOB Trend requires at least one demand snapshot")
        return self


class ArchiveTrendCompleted(Event, ArchiveTrendFields):
    """Trusted local activity references plus immutable C public snapshots."""


class JobCohortResolveSelector(BaseModel):
    """Stable B selector for one currently verified receipt.

    The selector names a scope, never a time: C binds `as_of` to the newest
    verified observation. `purpose` picks which question that scope answers --
    a role's active matching cohort, or the whole current market. The role rules
    are not restated here; `criteria_at` builds the real `CohortCriteria` and
    lets the contract judge, so a market can never quietly carry a role.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["job-cohort-resolve-selector/v1"]
    # Absent for CURRENT_MARKET only. Kept ahead of `purpose` so the stored
    # request shape of every existing ACTIVE_MATCHING selector is unchanged.
    target_role: StrictStr | None = None
    purpose: CohortPurpose = CohortPurpose.ACTIVE_MATCHING
    sources: tuple[StrictStr, ...] | None = None
    regions: tuple[StrictStr, ...] = ()
    career_levels: tuple[StrictStr, ...] = ()
    min_jobs: StrictInt | None = Field(default=None, ge=1)

    @field_validator("target_role")
    @classmethod
    def normalize_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return CohortCriteria.model_validate(
            {"target_role": value, "as_of": "2020-01-01T00:00:00Z"}
        ).target_role

    @model_validator(mode="after")
    def validate_scope(self) -> "JobCohortResolveSelector":
        # Reject an impossible scope now rather than at the first poll, so the
        # caller sees 422 instead of a cohort that never resolves.
        self.criteria_at(datetime(2020, 1, 1, tzinfo=UTC))
        return self

    @field_validator("sources", "regions", "career_levels")
    @classmethod
    def normalize_filters(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        return normalize_cohort_filters(values)

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        return normalize_cohort_filters(values, uppercase=True)

    def criteria_at(self, as_of: datetime) -> CohortCriteria:
        return CohortCriteria(
            target_role=self.target_role,
            purpose=self.purpose,
            as_of=as_of,
            sources=self.sources or (),
            regions=self.regions,
            career_levels=self.career_levels,
            min_jobs=1 if self.min_jobs is None else self.min_jobs,
        )


class TrendResolveSelector(BaseModel):
    """Natural keys for public Trend heads; source families never share a key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal[
        "JOB", "WEEKLY_REPO_ACTIVITY", "GH_ARCHIVE", "GH_ARCHIVE_HISTORICAL"
    ]
    tech_id: Annotated[
        str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ]
    periods: tuple[str, ...] = Field(default=(), max_length=48)
    granularity: PeriodGranularity | None = None
    include_partial: StrictBool = False
    target_role: StrictStr | None = None
    sources: tuple[StrictStr, ...] | None = None
    regions: tuple[StrictStr, ...] = ()
    career_levels: tuple[StrictStr, ...] = ()
    min_jobs: StrictInt | None = Field(default=None, ge=1)

    @field_validator("target_role")
    @classmethod
    def normalize_optional_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return CohortCriteria.model_validate(
            {"target_role": value, "as_of": "2020-01-01T00:00:00Z"}
        ).target_role

    @field_validator("sources", "regions", "career_levels")
    @classmethod
    def normalize_job_filters(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        return normalize_cohort_filters(values)

    @field_validator("sources")
    @classmethod
    def normalize_job_sources(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        return normalize_cohort_filters(values, uppercase=True)

    @model_validator(mode="after")
    def source_specific_scope(self) -> "TrendResolveSelector":
        job_scope = bool(
            self.target_role is not None
            or self.sources is not None
            or self.regions
            or self.career_levels
            or self.min_jobs is not None
        )
        if self.source == "WEEKLY_REPO_ACTIVITY":
            if self.periods or self.granularity is not None or job_scope:
                raise ValueError("weekly resolve does not accept a fixed period scope")
            return self
        if self.source == "JOB":
            if (
                not self.periods
                or self.granularity is not PeriodGranularity.MONTH
                or self.target_role is None
                or self.include_partial
            ):
                raise ValueError("JOB resolve requires a target role and MONTH periods")
        elif job_scope:
            raise ValueError("archive resolve does not accept JOB cohort filters")
        if not self.periods or self.granularity is None:
            raise ValueError("archive resolve requires periods and granularity")
        if (
            self.source == "GH_ARCHIVE_HISTORICAL"
            and self.granularity is not PeriodGranularity.MONTH
        ):
            raise ValueError("historical archive resolve supports MONTH only")
        from trend.archive import _period_index

        indices = tuple(
            _period_index(period, self.granularity) for period in self.periods
        )
        if indices != tuple(sorted(set(indices))):
            raise ValueError("periods must be unique and ascending")
        return self

    def public_identity(self) -> dict[str, Any]:
        common = {
            "source": self.source,
            "tech_id": self.tech_id,
            "include_partial": self.include_partial,
        }
        if self.source != "WEEKLY_REPO_ACTIVITY":
            common.update(
                periods=list(self.periods),
                granularity=self.granularity.value,
            )
        if self.source == "JOB":
            common.update(
                target_role=self.target_role,
                sources=list(self.sources or ()),
                regions=list(self.regions),
                career_levels=list(self.career_levels),
                min_jobs=1 if self.min_jobs is None else self.min_jobs,
            )
        return common


class TrendResolveBatchRequest(BaseModel):
    """A bounded comparison request; every selector shares one source scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selectors: tuple[TrendResolveSelector, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def one_source_scope(self) -> "TrendResolveBatchRequest":
        tech_ids = tuple(selector.tech_id for selector in self.selectors)
        if len(tech_ids) != len(set(tech_ids)):
            raise ValueError("batch tech_ids must be unique")
        # Lists inside the dumped values are not hashable, so compare their stable
        # JSON representation instead of accepting subtly different periods/filters.
        serialized_scopes = {
            digest(selector.model_dump(mode="json", exclude={"tech_id"}))
            for selector in self.selectors
        }
        if len(serialized_scopes) != 1:
            raise ValueError("batch selectors must share one source scope")
        return self


class BodyLimit:
    """Enforce a limit even for chunked requests before Pydantic parses JSON."""

    def __init__(self, app, *, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "code": "INPUT_TOO_LARGE",
                        "message": "Request body exceeds the C input limit",
                    },
                )
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        position = 0

        async def replay():
            nonlocal position
            if position < len(chunks):
                message = chunks[position]
                position += 1
                return message
            return await receive()

        await self.app(scope, replay, send)


def configured_database_url() -> str | None:
    if os.environ.get("C_COMPUTE_DATABASE_URL"):
        return os.environ["C_COMPUTE_DATABASE_URL"]
    required = ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    if not all(os.environ.get(key) for key in required):
        return None
    return make_conninfo(
        host=os.environ["POSTGRES_HOST"],
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def default_registry(*, dsn: str | None = None) -> TechnologyRegistry:
    from registry.db import PostgresRegistryStore, RegistryStoreError

    backend = os.getenv("C_REGISTRY_BACKEND", "postgres")
    if backend == "postgres":
        dsn = dsn or configured_database_url()
        if not dsn:
            raise RegistryStoreError("C Registry database is not configured")
        source = PostgresRegistryStore(dsn)
        selected = source.resolve_version(
            os.getenv("C_REGISTRY_VERSION", "technology-registry/v1")
        )
        return source.load_registry(selected.registry_version)
    if backend != "file":
        raise RegistryStoreError("C_REGISTRY_BACKEND must be postgres or file")
    configured = os.getenv("C_REGISTRY_PATH")
    path = (
        Path(configured)
        if configured
        else REGISTRY_ROOT / "technology_registry_20260911_4.json"
    )
    source_root = Path(
        os.getenv(
            "C_REGISTRY_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[2])
        )
    )
    return load_registry(path, repository_root=source_root)


def compute_versions(kind: str, registry: TechnologyRegistry) -> dict[str, str]:
    """A retry must not silently run different rules after a deployment."""
    versions = {
        "runtime": "c-compute-runtime/v3",
        "registry": registry.registry_version,
        "registry_sha256": digest(registry.model_dump(mode="json")),
    }
    if kind == "JOB_BATCH":
        from job.input_union import INPUT_UNION_VERSION
        from job.requirements import (
            JOB_REQUIRED_LEVEL_POLICY_VERSION,
            JOB_REQUIREMENTS_SCHEMA_VERSION,
        )
        from registry.review import REVIEW_QUEUE_VERSION

        versions.update(
            parser=JOB_REQUIREMENT_PARSER_VERSION,
            quality=JOB_QUALITY_VERSION,
            aggregation=JOB_DEMAND_AGGREGATION_VERSION,
            input_union=INPUT_UNION_VERSION,
            requirements=JOB_REQUIREMENTS_SCHEMA_VERSION,
            required_level_policy=JOB_REQUIRED_LEVEL_POLICY_VERSION,
            review_queue=REVIEW_QUEUE_VERSION,
        )
    elif kind == "ANALYSIS":
        from job.matching import JOB_MATCHING_VERSION
        from recommendation.engine import (
            PREREQUISITE_POLICY_VERSION,
            RECOMMENDATION_ALGORITHM_VERSION,
        )
        from recommendation.evidence import HELD_POLICY_VERSION, LEVEL_POLICY_VERSION
        from recommendation.explanation import EXPLANATION_VERSION

        versions.update(
            algorithm=RECOMMENDATION_ALGORITHM_VERSION,
            prerequisites=PREREQUISITE_POLICY_VERSION,
            held=HELD_POLICY_VERSION,
            level=LEVEL_POLICY_VERSION,
            aggregation=JOB_DEMAND_AGGREGATION_VERSION,
            explanation=EXPLANATION_VERSION,
            matching=JOB_MATCHING_VERSION,
        )
    elif kind == "PUBLIC_REPO":
        from github.public_analysis import PUBLIC_PARSER_VERSION

        versions["parser"] = PUBLIC_PARSER_VERSION
    else:
        from trend.contracts import TREND_VERSION
        from trend.job import JOB_TREND_POLICY_VERSION

        versions["trend"] = TREND_VERSION
        versions["job_population"] = JOB_TREND_POLICY_VERSION
    return versions


def archive_compute_versions(
    archive_version: Literal["v1", "v2"], registry: TechnologyRegistry
) -> dict[str, str]:
    """Pin the current or historical Archive algorithm in event identity."""

    versions = compute_versions("TREND", registry)
    if archive_version == "v2":
        from trend.archive_v2 import HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION

        versions["archive_trend"] = HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION
    else:
        from trend.archive import ARCHIVE_TREND_ALGORITHM_VERSION

        versions["archive_trend"] = ARCHIVE_TREND_ALGORITHM_VERSION
    return versions


def startup_registry(*, dsn: str | None = None) -> TechnologyRegistry | None:
    """Retry only startup DB interruptions; a loaded snapshot stays process-pinned."""
    from registry.db import RegistryStoreError

    for attempt in range(1, 4):
        try:
            return default_registry(dsn=dsn)
        except psycopg.OperationalError as exc:
            # Exception messages can contain connection details. Log only safe tags.
            LOGGER.warning(
                "C Registry startup DB failure attempt=%s/3 error_type=%s sqlstate=%s",
                attempt,
                type(exc).__name__,
                exc.sqlstate,
            )
            if attempt == 3:
                # The process supervisor can restart after DB recovery. Keeping a
                # live process with registry=None would never retry until rollout.
                raise RuntimeError("Registry startup retries exhausted") from None
            time.sleep(attempt)
        except (RegistryStoreError, psycopg.Error) as exc:
            LOGGER.error(
                "C Registry requires setup or repair error_type=%s; "
                "check migrations and approved import, then restart Worker",
                type(exc).__name__,
            )
            # Missing approval/config/schema is not fixed by repeated DB reads.
            # Keep liveness and authenticated /ready=503 available for diagnosis.
            return None
    return None  # All three attempts above either return or raise.


def create_compute_app(
    *,
    store: ComputeStore | None = None,
    token: str | None = None,
    registry: TechnologyRegistry | None = None,
    artifact_reader: Any = None,
    max_body_bytes: int = 8 * 1024 * 1024,
    intake_config: Path | None = None,
) -> FastAPI:
    app = create_health_app("worker")
    app.add_middleware(BodyLimit, limit=max_body_bytes)
    if registry is None:
        registry = startup_registry(dsn=getattr(store, "_dsn", None))
    mapper = RegistryMapper(registry) if registry is not None else None
    token = token if token is not None else os.getenv("C_COMPUTE_TOKEN", "")
    if store is None:
        dsn = configured_database_url()
        if dsn:
            store = ComputeStore(
                dsn, lease_seconds=int(os.getenv("C_COMPUTE_LEASE_SECONDS", "120"))
            )
    if (
        artifact_reader is None
        and os.getenv("C_ARTIFACT_ROOT")
        and os.getenv("C_ARTIFACT_URI_PREFIX")
    ):
        from github.public_analysis import LocalMirrorArtifactReader

        artifact_reader = LocalMirrorArtifactReader(
            Path(os.environ["C_ARTIFACT_ROOT"]), os.environ["C_ARTIFACT_URI_PREFIX"]
        )

    configured_intake = intake_config or os.getenv("C_INTAKE_CONFIG")
    intake_runner = None
    if configured_intake and registry is not None:
        from worker.intake import configured_runner

        if store is None or len(token) < 32:
            raise ValueError("automatic intake requires configured database and token")
        intake_runner = configured_runner(
            Path(configured_intake), store, mapper, registry
        )

    @asynccontextmanager
    async def lifespan(application):
        if intake_runner:
            intake_runner.start()
        try:
            yield
        finally:
            if intake_runner:
                intake_runner.stop()

    app.router.lifespan_context = lifespan
    app.state.intake_runner = intake_runner

    def authorized(authorization: Annotated[str | None, Header()] = None):
        if len(token) < 32:
            raise HTTPException(503, "C_COMPUTE_NOT_CONFIGURED")
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or not hmac.compare_digest(supplied.encode(), token.encode())
        ):
            raise HTTPException(401, "INTERNAL_AUTH_REQUIRED")
        if registry is None:
            raise HTTPException(503, "C_REGISTRY_UNAVAILABLE")

    def database() -> ComputeStore:
        if store is None:
            raise HTTPException(503, "C_DATABASE_NOT_CONFIGURED")
        return store

    def snapshot(snapshot_id: str, owner: str | None, kind: str | None = None):
        value = database().get_snapshot(snapshot_id, owner=owner)
        if not value or (kind and value["kind"] != kind):
            raise HTTPException(404, "SNAPSHOT_NOT_FOUND")
        return value

    def execute(
        event: Event,
        kind: str,
        owner: str | None,
        compute: Callable[[], list[Artifact]],
    ):
        db = database()
        request_payload = event.model_dump(mode="json")
        # trace_id is delivery diagnostics, not computation input or idempotency identity.
        request_payload.pop("trace_id")
        if isinstance(event, ArchiveTrendCompleted):
            if event.archive_version == "v1":
                # Preserve the pre-v2 request hash for legacy retries.
                request_payload.pop("archive_version", None)
            request_payload["compute_versions"] = archive_compute_versions(
                event.archive_version, registry
            )
        else:
            request_payload["compute_versions"] = compute_versions(kind, registry)
        ticket = db.claim(
            event_id=event.event_id,
            kind=kind,
            owner=owner,
            occurred_at=event.occurred_at,
            request=request_payload,
        )
        if ticket.status == "COMPLETED":
            return {
                "message": "C computation complete",
                "data": {
                    "event_id": event.event_id,
                    "status": "COMPLETED",
                    "results": ticket.results,
                },
            }
        if ticket.token is None:
            return JSONResponse(
                status_code=202,
                headers={"Retry-After": "2"},
                content={
                    "message": "C computation in progress",
                    "data": {
                        "event_id": event.event_id,
                        "status": "PREPARING",
                        "results": [],
                    },
                },
            )
        try:
            with LeaseHeartbeat(db, ticket):
                results = db.complete(ticket, compute())
        except Exception:
            try:
                db.fail(ticket, "COMPUTE_FAILED")
            except psycopg.Error:
                pass  # The persisted lease allows recovery after database reconnect.
            LOGGER.warning(
                "C computation failed kind=%s event_id=%s trace_id=%s",
                kind,
                event.event_id,
                event.trace_id,
            )
            raise
        LOGGER.info(
            "C computation completed kind=%s event_id=%s trace_id=%s",
            kind,
            event.event_id,
            event.trace_id,
        )
        return {
            "message": "C computation complete",
            "data": {
                "event_id": event.event_id,
                "status": "COMPLETED",
                "results": results,
            },
        }

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": str(exc.detail), "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_INPUT",
                "message": "Request does not satisfy the C compute contract",
            },
        )

    @app.exception_handler(ValueError)
    async def invalid_domain_input(request: Request, exc: ValueError):
        from job.matching import MatchingResultTooLarge

        if isinstance(exc, IdempotencyConflict):
            code, status = "IDEMPOTENCY_CONFLICT", 409
        elif isinstance(exc, MatchingResultTooLarge):
            code, status = "RESULT_TOO_LARGE", 413
        else:
            code, status = "INVALID_INPUT", 422
        return JSONResponse(status_code=status, content={"code": code, "message": code})

    @app.exception_handler(StoredMatchingIntegrityError)
    async def stored_matching_integrity_error(
        request: Request, exc: StoredMatchingIntegrityError
    ):
        LOGGER.error("Stored matching integrity check failed", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "STORED_MATCHING_INTEGRITY_FAILED",
                "message": "Stored matching result failed an integrity check",
            },
        )

    @app.exception_handler(PermissionError)
    async def wrong_scope(request: Request, exc: PermissionError):
        return JSONResponse(
            status_code=403,
            content={
                "code": "EVIDENCE_SCOPE_MISMATCH",
                "message": "Evidence does not belong to the requested analysis",
            },
        )

    @app.exception_handler(LeaseLost)
    async def lease_lost(request: Request, exc: LeaseLost):
        return JSONResponse(
            status_code=409,
            content={
                "code": "LEASE_LOST",
                "message": "Retry the same event after the current attempt finishes",
            },
        )

    @app.exception_handler(psycopg.Error)
    async def db_error(request: Request, exc: psycopg.Error):
        return JSONResponse(
            status_code=503,
            content={
                "code": "C_DATABASE_UNAVAILABLE",
                "message": "C database or migration is unavailable",
            },
        )

    @app.exception_handler(ArchiveInputUnavailable)
    async def archive_input_unavailable(request: Request, exc: ArchiveInputUnavailable):
        LOGGER.error(
            "Archive input unavailable error_type=%s errno=%s activity_path=%r endpoint=%s",
            exc.error_type,
            exc.errno,
            exc.activity_path,
            request.url.path,
        )
        return JSONResponse(
            status_code=503,
            content={
                "code": "ARCHIVE_INPUT_UNAVAILABLE",
                "message": "Archive input cannot be read; check the input mount and permissions",
            },
        )

    @app.exception_handler(Exception)
    async def compute_error(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "code": "COMPUTE_FAILED",
                "message": "C computation failed; retry the same event",
            },
        )

    @app.get("/ready", dependencies=[Depends(authorized)])
    def ready():
        if not database().ready():
            raise HTTPException(503, "C_MIGRATION_REQUIRED")
        return {
            "message": "C compute ready",
            "data": {"status": "READY", "registry_version": registry.registry_version},
        }

    prefix = "/internal/v1/c"
    auth = [Depends(authorized)]

    from worker.review_api import install_review_routes

    install_review_routes(
        app, prefix=prefix, auth=auth, database=database, mapper=mapper
    )

    @app.get(prefix + "/intake/status", dependencies=auth)
    def intake_status():
        return {
            "message": "C completed-output intake status",
            "data": {
                "configured": intake_runner is not None,
                "running": bool(intake_runner and intake_runner.running),
                "last_poll": intake_runner.last_report if intake_runner else None,
                "public_sources": intake_runner.public_reports if intake_runner else [],
            },
        }

    @app.post(prefix + "/job-cohorts/resolve", dependencies=auth)
    def resolve_job_cohort(
        request: CohortCriteria | JobCohortResolveSelector,
    ):
        from worker.jobs import job_stream

        selector = request if isinstance(request, JobCohortResolveSelector) else None
        criteria = request if isinstance(request, CohortCriteria) else None
        versions = compute_versions("JOB_BATCH", registry)
        if intake_runner and intake_runner.job_set_sink:
            if selector is not None:
                selected = intake_runner.resolve_job_selector(selector)
                criteria, result = selected if selected is not None else (None, None)
            else:
                result = intake_runner.resolve_job_criteria(criteria)
            if not result:
                raise HTTPException(404, "COHORT_NOT_PREPARED")
            if result.get("status") == "PREPARING":
                return JSONResponse(
                    status_code=202,
                    headers={"Retry-After": "2"},
                    content={
                        "message": "C cohort computation in progress",
                        "data": {
                            "status": "PREPARING",
                            "criteria": criteria.model_dump(mode="json"),
                            "compute_versions": versions,
                        },
                    },
                )
            references = result["results"]
            message = "C latest verified input-union cohort and demand reference"
        else:
            if criteria is None:
                raise HTTPException(404, "COHORT_NOT_PREPARED")
            stream = job_stream(criteria, versions)
            pair = database().get_job_head_pair(stream)
            references = (
                []
                if pair is None
                else [
                    {"kind": "COHORT", "snapshot_id": pair["cohort_snapshot_id"]},
                    {"kind": "DEMAND", "snapshot_id": pair["demand_snapshot_id"]},
                ]
            )
            message = "C latest completed cohort and demand reference"
        by_kind = {
            row.get("kind"): row.get("snapshot_id")
            for row in references
            if isinstance(row, dict)
        }
        if (
            len(references) != 2
            or set(by_kind) != {"COHORT", "DEMAND"}
            or not all(isinstance(value, str) for value in by_kind.values())
        ):
            raise HTTPException(404, "COHORT_NOT_PREPARED")
        return {
            "message": message,
            "data": {
                "cohort_snapshot_id": by_kind["COHORT"],
                "demand_snapshot_id": by_kind["DEMAND"],
                "criteria": criteria.model_dump(mode="json"),
                "compute_versions": versions,
            },
        }

    @app.get(prefix + "/registry", dependencies=auth)
    def get_registry():
        return {
            "message": "C Registry snapshot",
            "data": registry.model_dump(mode="json"),
            "meta": {
                "schema_version": registry.schema_version,
                "registry_version": registry.registry_version,
                "registry_sha256": digest(registry.model_dump(mode="json")),
            },
        }

    @app.get(prefix + "/contracts", dependencies=auth)
    def get_contracts():
        return {
            "message": "C input schemas",
            "data": {
                model.__name__: model.model_json_schema()
                for model in (
                    CohortCriteria,
                    JobCohortResolveSelector,
                    JobCompleted,
                    AnalysisCompleted,
                    PublicReposCompleted,
                    TrendCompleted,
                    ArchiveTrendCompleted,
                    TrendResolveSelector,
                    TrendResolveBatchRequest,
                )
            },
        }

    @app.post(prefix + "/job-batches/completed", dependencies=auth)
    def job_completed(event: JobCompleted):
        from worker.jobs import job_artifacts

        def compute():
            return job_artifacts(
                event.batch,
                event.criteria,
                mapper,
                compute_versions("JOB_BATCH", registry),
            )

        return execute(event, "JOB_BATCH", None, compute)

    @app.post(prefix + "/analyses/completed", dependencies=auth)
    def analysis_completed(event: AnalysisCompleted):
        from recommendation.engine import build_recommendations

        if (
            event.user_id != event.evidence.user_id
            or event.analysis_id != event.evidence.analysis_id
            or any(r.user_id != event.user_id for r in event.evidence.repositories)
        ):
            raise PermissionError("Evidence scope mismatch")

        def compute():
            cohort = JobCohort.model_validate(
                snapshot(event.cohort_snapshot_id, None, "COHORT")["payload"]
            )
            if cohort.registry_version != registry.registry_version:
                raise ValueError("cohort and runtime Registry versions differ")
            result = build_recommendations(
                cohort,
                event.evidence,
                user_id=event.user_id,
                analysis_id=event.analysis_id,
            )
            payload = result.model_dump(mode="json")
            payload["cohort_snapshot_id"] = event.cohort_snapshot_id
            from recommendation.explanation import explain_recommendations

            payload["explanation"] = explain_recommendations(result).model_dump(
                mode="json"
            )
            if cohort.matching_jobs is not None:
                from job.matching import (
                    build_job_matching,
                    matching_reference,
                    matching_storage_rows,
                )

                matching_result = build_job_matching(
                    cohort,
                    event.evidence,
                    user_id=event.user_id,
                    analysis_id=event.analysis_id,
                )
                payload["job_matching_ref"] = matching_reference(
                    matching_result, cohort_snapshot_id=event.cohort_snapshot_id
                )
                matching = matching_storage_rows(matching_result)
            else:
                matching = None
            stream = digest(
                {
                    "cohort": event.cohort_snapshot_id,
                    "criteria": cohort.criteria.model_dump(mode="json"),
                }
            )
            return [
                Artifact(
                    "RECOMMENDATION",
                    event.user_id,
                    payload,
                    stream,
                    matching=matching,
                )
            ]

        return execute(event, "ANALYSIS", event.user_id, compute)

    @app.get(prefix + "/snapshots/{snapshot_id}", dependencies=auth)
    def get_snapshot(snapshot_id: SnapshotId, user_id: Identifier | None = None):
        return {"message": "C snapshot", "data": snapshot(snapshot_id, user_id)}

    @app.get(prefix + "/recommendations/{snapshot_id}/job-postings", dependencies=auth)
    def get_postings(
        snapshot_id: SnapshotId,
        user_id: Identifier,
        mode: Literal["CURRENT", "WHAT_IF"] = "CURRENT",
        recommended_tech_id: str | None = None,
        page: Annotated[int, Query(ge=0)] = 0,
        size: Annotated[int, Query(ge=1, le=50)] = 20,
    ):
        from recommendation.engine import RecommendationSnapshot, list_related_jobs

        payload = dict(snapshot(snapshot_id, user_id, "RECOMMENDATION")["payload"])
        payload.pop("cohort_snapshot_id", None)
        payload.pop("explanation", None)
        payload.pop("job_matching", None)
        payload.pop("job_matching_ref", None)
        result = RecommendationSnapshot.model_validate(payload)
        listing = list_related_jobs(
            result,
            user_id=user_id,
            view=mode,
            tech_id=recommended_tech_id,
            offset=page * size,
            limit=size,
        )
        return {
            "message": "C matching job postings",
            "data": {
                **listing.model_dump(mode="json"),
                "calculation_snapshot_id": listing.snapshot_id,
                "snapshot_id": snapshot_id,
            },
        }

    def legacy_matching_result(snapshot_id: str, user_id: str):
        from job.matching import MatchingResultTooLarge, validate_job_matching

        payload = snapshot(snapshot_id, user_id, "RECOMMENDATION")["payload"]
        if "job_matching" not in payload:
            raise HTTPException(409, "JOB_MATCHING_NOT_PREPARED")
        try:
            result = validate_job_matching(payload["job_matching"])
            if (
                result.user_id != user_id
                or result.analysis_id != payload["analysis_id"]
                or result.cohort_id != payload["cohort_id"]
            ):
                raise ValueError("stored matching scope mismatch")
            return result
        except MatchingResultTooLarge as exc:
            raise HTTPException(413, "LEGACY_MATCHING_RESULT_TOO_LARGE") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise StoredMatchingIntegrityError(
                "legacy embedded matching result is inconsistent"
            ) from exc

    def matching_page(
        snapshot_id: str,
        user_id: str,
        *,
        page: int,
        size: int,
        include_conditional: bool,
    ):
        stored = database().get_matching_page(
            snapshot_id,
            owner=user_id,
            offset=page * size,
            limit=size,
            include_conditional=include_conditional,
        )
        if stored is None:
            raise HTTPException(404, "SNAPSHOT_NOT_FOUND")
        if stored["status"] == "NOT_PREPARED":
            raise HTTPException(409, "JOB_MATCHING_NOT_PREPARED")
        if stored["status"] == "LEGACY_EMBEDDED":
            result = legacy_matching_result(snapshot_id, user_id)
            rows = tuple(
                row
                for row in result.jobs
                if include_conditional or row.job.eligibility == "ELIGIBLE"
            )
            offset = page * size
            items = (
                []
                if offset >= len(rows)
                else [
                    row.model_dump(mode="json") for row in rows[offset : offset + size]
                ]
            )
            return {
                "calculation_snapshot_id": result.calculation_snapshot_id,
                "metadata": result.model_dump(
                    mode="json", exclude={"jobs", "calculation_snapshot_id"}
                ),
                "total_count": len(result.jobs),
                "eligible_count": sum(
                    row.job.eligibility == "ELIGIBLE" for row in result.jobs
                ),
                "conditional_count": sum(
                    row.job.eligibility == "CONDITIONAL" for row in result.jobs
                ),
                "items": items,
                "has_next": offset + size < len(rows),
            }
        return stored

    @app.get(
        prefix + "/recommendations/{snapshot_id}/matching-job-postings",
        dependencies=auth,
    )
    def get_matching_postings(
        snapshot_id: SnapshotId,
        user_id: Identifier,
        page: Annotated[int, Query(ge=0)] = 0,
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        include_conditional: bool = False,
    ):
        stored = matching_page(
            snapshot_id,
            user_id,
            page=page,
            size=size,
            include_conditional=include_conditional,
        )
        metadata = stored["metadata"]
        total_count = (
            stored["total_count"] if include_conditional else stored["eligible_count"]
        )
        return {
            "message": "C partial matching job postings",
            "data": {
                "snapshot_id": snapshot_id,
                "calculation_snapshot_id": stored["calculation_snapshot_id"],
                "schema_version": metadata["schema_version"],
                "cohort_id": metadata["cohort_id"],
                "analysis_id": metadata["analysis_id"],
                "criteria": metadata["criteria"],
                "registry_version": metadata["registry_version"],
                "held_policy_version": metadata["held_policy_version"],
                "level_policy_version": metadata["level_policy_version"],
                "evidence_rule_version": metadata["evidence_rule_version"],
                "total_count": total_count,
                "conditional_count": stored["conditional_count"],
                "excluded_conditional_count": (
                    0 if include_conditional else stored["conditional_count"]
                ),
                "page": page,
                "size": size,
                "has_next": stored["has_next"],
                "items": stored["items"],
                "data_gaps": metadata["data_gaps"],
            },
        }

    @app.get(
        prefix + "/recommendations/{snapshot_id}/matching-job-posting",
        dependencies=auth,
    )
    def get_matching_posting(
        snapshot_id: SnapshotId,
        user_id: Identifier,
        job_id: Annotated[str, Query(min_length=1, max_length=256)],
    ):
        stored = database().get_matching_detail(
            snapshot_id, owner=user_id, job_id=job_id
        )
        if stored is None:
            raise HTTPException(404, "SNAPSHOT_NOT_FOUND")
        if stored["status"] == "NOT_PREPARED":
            raise HTTPException(409, "JOB_MATCHING_NOT_PREPARED")
        if stored["status"] == "LEGACY_EMBEDDED":
            result = legacy_matching_result(snapshot_id, user_id)
            row = next((row for row in result.jobs if row.job.job_id == job_id), None)
            stored = {
                "calculation_snapshot_id": result.calculation_snapshot_id,
                "metadata": result.model_dump(
                    mode="json", exclude={"jobs", "calculation_snapshot_id"}
                ),
                "item": row.model_dump(mode="json") if row else None,
            }
        if stored["item"] is None:
            raise HTTPException(404, "JOB_NOT_FOUND")
        metadata = stored["metadata"]
        return {
            "message": "C partial matching job detail",
            "data": {
                "snapshot_id": snapshot_id,
                "calculation_snapshot_id": stored["calculation_snapshot_id"],
                "cohort_id": metadata["cohort_id"],
                "analysis_id": metadata["analysis_id"],
                "item": stored["item"],
            },
        }

    @app.post(prefix + "/public-repositories/completed", dependencies=auth)
    def public_completed(event: PublicReposCompleted):
        from github.public_analysis import analyze_public_batch

        if artifact_reader is None:
            raise HTTPException(503, "C_ARTIFACT_READER_NOT_CONFIGURED")

        def compute():
            result = analyze_public_batch(
                event.batch,
                artifact_reader,
                mapper,
                include_partial=event.include_partial,
            )
            payload = result.model_dump(mode="json")
            return [
                Artifact(
                    "PUBLIC_GITHUB",
                    None,
                    payload,
                    digest(
                        {
                            "batch": event.batch.dataset_snapshot_id,
                            "versions": compute_versions("PUBLIC_REPO", registry),
                            "collection_policy": event.batch.collection_policy.policy_version,
                            "include_partial": event.include_partial,
                        }
                    ),
                )
            ]

        return execute(event, "PUBLIC_REPO", None, compute)

    @app.post(prefix + "/archive-trends/completed", dependencies=auth)
    def archive_completed(event: ArchiveTrendCompleted):
        from worker.archive_input import build_archive_artifact

        return execute(
            event,
            "TREND",
            None,
            lambda: [
                build_archive_artifact(event, registry=registry, snapshot=snapshot)
            ],
        )

    def trend_resolve_context(selector: TrendResolveSelector):
        from trend.archive import ARCHIVE_TREND_ALGORITHM_VERSION
        from trend.archive_v2 import (
            HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
        )
        from trend.job import JOB_TREND_POLICY_VERSION
        from worker.trend_streams import (
            archive_trend_stream,
            job_trend_filters,
            job_trend_stream,
            weekly_activity_trend_stream,
        )

        active = any(
            technology.tech_id == selector.tech_id
            and technology.status.value == "ACTIVE"
            for technology in registry.technologies
        )
        if not active:
            raise ValueError("tech_id must reference an active Registry technology")
        expected_job_filters = None
        if selector.source == "JOB":
            algorithm = JOB_TREND_POLICY_VERSION
            minimum = 1 if selector.min_jobs is None else selector.min_jobs
            expected_job_filters = job_trend_filters(
                target_role=selector.target_role,
                sources=selector.sources or (),
                regions=selector.regions,
                career_levels=selector.career_levels,
                min_jobs=minimum,
                registry_version=registry.registry_version,
            )
            stream = job_trend_stream(
                tech_id=selector.tech_id,
                periods=selector.periods,
                target_role=selector.target_role,
                sources=selector.sources or (),
                regions=selector.regions,
                career_levels=selector.career_levels,
                min_jobs=minimum,
                registry_version=registry.registry_version,
                versions=compute_versions("TREND", registry),
            )
        elif selector.source == "WEEKLY_REPO_ACTIVITY":
            algorithm = ARCHIVE_TREND_ALGORITHM_VERSION
            stream = weekly_activity_trend_stream(
                tech_id=selector.tech_id,
                registry_version=registry.registry_version,
                include_partial=selector.include_partial,
            )
        else:
            historical = selector.source == "GH_ARCHIVE_HISTORICAL"
            archive_version = "v2" if historical else "v1"
            algorithm = (
                HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION
                if historical
                else ARCHIVE_TREND_ALGORITHM_VERSION
            )
            stream = archive_trend_stream(
                archive_version=archive_version,
                tech_id=selector.tech_id,
                periods=selector.periods,
                granularity=selector.granularity.value,
                include_partial=selector.include_partial,
                registry_version=registry.registry_version,
                algorithm=algorithm,
            )
        return stream, algorithm, expected_job_filters

    def resolved_trend_data(
        selector: TrendResolveSelector,
        resolved: dict[str, Any],
        algorithm: str,
        expected_job_filters,
    ):
        from trend.archive import ArchiveTrendResult
        from trend.archive_v2 import HistoricalArchiveTrendResult
        from trend.contracts import TrendResult

        payload = resolved.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("resolved Trend payload is invalid")
        try:
            result = (
                TrendResult.model_validate(payload)
                if selector.source == "JOB"
                else (
                    HistoricalArchiveTrendResult.model_validate(payload)
                    if selector.source == "GH_ARCHIVE_HISTORICAL"
                    else ArchiveTrendResult.model_validate(payload)
                )
            )
        except ValueError as exc:
            raise RuntimeError("resolved Trend payload is invalid") from exc
        periods = [point.period for point in result.points]
        if selector.source == "JOB":
            consistent = (
                result.source == "JOB"
                and result.tech_id == selector.tech_id
                and result.registry_version == registry.registry_version
                and result.algorithm_version == algorithm
                and result.granularity == PeriodGranularity.MONTH.value
                and periods == list(selector.periods)
                and result.filters == expected_job_filters
            )
            include_partial = False
        else:
            expected_granularity = (
                PeriodGranularity.WEEK
                if selector.source == "WEEKLY_REPO_ACTIVITY"
                else selector.granularity
            )
            consistent = (
                result.tech_id == selector.tech_id
                and result.registry_version == registry.registry_version
                and result.algorithm_version == algorithm
                and result.granularity is expected_granularity
                and result.include_partial is selector.include_partial
                and (
                    selector.source == "WEEKLY_REPO_ACTIVITY"
                    or periods == list(selector.periods)
                )
            )
            include_partial = result.include_partial
        if not consistent:
            raise RuntimeError("resolved Trend scope is inconsistent")
        return {
            "snapshot_id": resolved["snapshot_id"],
            "selector": selector.public_identity(),
            "schema_version": result.schema_version,
            "status": result.status.value,
            "registry_version": result.registry_version,
            "algorithm_version": result.algorithm_version,
            "granularity": (
                result.granularity
                if selector.source == "JOB"
                else result.granularity.value
            ),
            "periods": periods,
            "include_partial": include_partial,
            "lineage": {
                "event_id": resolved["event_id"],
                "occurred_at": resolved["occurred_at"],
            },
        }

    @app.post(prefix + "/trends/resolve", dependencies=auth)
    def resolve_trend(selector: TrendResolveSelector):
        stream, algorithm, expected_job_filters = trend_resolve_context(selector)
        resolved = database().get_head_snapshot("TREND", None, stream)
        if resolved is None:
            raise HTTPException(404, "TREND_NOT_PREPARED")
        return {
            "message": "C current public Trend reference",
            "data": resolved_trend_data(
                selector, resolved, algorithm, expected_job_filters
            ),
        }

    @app.post(prefix + "/trends/resolve-batch", dependencies=auth)
    def resolve_trend_batch(request: TrendResolveBatchRequest):
        """Resolve up to ten technologies with one B-to-C HTTP round trip."""

        contexts = [
            (selector, *trend_resolve_context(selector))
            for selector in request.selectors
        ]
        streams = tuple(context[1] for context in contexts)
        resolved_by_stream = database().get_head_snapshots(
            kind="TREND", owner=None, streams=streams
        )
        items = []
        for selector, stream, algorithm, expected_job_filters in contexts:
            resolved = resolved_by_stream.get(stream)
            if resolved is None:
                items.append(
                    {
                        "tech_id": selector.tech_id,
                        "status": "NOT_PREPARED",
                        "code": "TREND_NOT_PREPARED",
                        "snapshot": None,
                    }
                )
                continue
            resolved_trend_data(selector, resolved, algorithm, expected_job_filters)
            items.append(
                {
                    "tech_id": selector.tech_id,
                    "status": "READY",
                    "code": None,
                    "snapshot": {
                        "snapshot_id": resolved["snapshot_id"],
                        "kind": "TREND",
                        "payload": resolved["payload"],
                    },
                }
            )
        return {"message": "C public Trend batch", "data": {"items": items}}

    @app.post(prefix + "/trends/completed", dependencies=auth)
    def trend_completed(event: TrendCompleted):
        from trend.github import github_trend, parse_innovation_graph_csv
        from trend.job import job_trend
        from worker.trend_streams import source_trend_stream

        def compute():
            if event.source == "JOB":
                if (
                    event.csv_text is not None
                    or event.source_uri
                    or event.source_version
                ):
                    raise ValueError("JOB input must reference demand snapshots only")
                demands = tuple(
                    DemandSnapshot.model_validate(
                        snapshot(sid, None, "DEMAND")["payload"]
                    )
                    for sid in event.demand_snapshot_ids
                )
                result = job_trend(
                    event.tech_id, demands or None, registry, periods=event.periods
                )
            else:
                if event.demand_snapshot_ids:
                    raise ValueError("GITHUB does not accept demand snapshots")
                if event.csv_text is not None:
                    if not event.source_uri or not event.source_version:
                        raise ValueError("GITHUB source provenance is required")
                    dataset = parse_innovation_graph_csv(
                        event.csv_text,
                        source_version=event.source_version,
                        source_uri=event.source_uri,
                    )
                else:
                    if event.source_uri or event.source_version:
                        raise ValueError("GITHUB source metadata requires a dataset")
                    dataset = None
                result = github_trend(
                    event.tech_id, dataset, registry, periods=event.periods
                )
            return [
                Artifact(
                    "TREND",
                    None,
                    result.model_dump(mode="json"),
                    source_trend_stream(
                        tech_id=event.tech_id,
                        source=event.source,
                        periods=event.periods,
                        versions=compute_versions("TREND", registry),
                        # Validated non-period filters include JOB cohort rule
                        # versions, never values, run IDs or source snapshots.
                        filters=result.filters,
                    ),
                )
            ]

        return execute(event, "TREND", None, compute)

    return app
