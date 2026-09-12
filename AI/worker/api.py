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
    StringConstraints,
    field_validator,
)

from common.health import create_health_app
from github.contracts import GitHubRepoSnapshotBatch
from job.classifier import JOB_REQUIREMENT_PARSER_VERSION
from job.cohort import JOB_QUALITY_VERSION, CohortCriteria, JobCohort
from job.contracts import JobAnalysisInputBatch
from job.demand import JOB_DEMAND_AGGREGATION_VERSION, DemandSnapshot
from recommendation.evidence import EvidenceAnalysis
from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import RegistryMapper
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


class ArchiveTrendCompleted(Event, ArchiveTrendFields):
    """Trusted local activity references plus immutable C public snapshots."""


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
        else REGISTRY_ROOT / "technology_registry_20260911_1.json"
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
        request_payload["compute_versions"] = compute_versions(kind, registry)
        if isinstance(event, ArchiveTrendCompleted):
            from trend.archive import ARCHIVE_TREND_ALGORITHM_VERSION

            request_payload["compute_versions"]["archive_trend"] = (
                ARCHIVE_TREND_ALGORITHM_VERSION
            )
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
    def resolve_job_cohort(criteria: CohortCriteria):
        from worker.jobs import job_stream

        if intake_runner and intake_runner.job_set_sink:
            result = intake_runner.current_job_result(criteria)
            if not result:
                raise HTTPException(404, "COHORT_NOT_PREPARED")
            return {
                "message": "C current observed input-union cohort reference",
                "data": {
                    "cohort_snapshot_id": next(
                        row["snapshot_id"]
                        for row in result["results"]
                        if row["kind"] == "COHORT"
                    )
                },
            }
        stream = job_stream(criteria, compute_versions("JOB_BATCH", registry))
        snapshot_id = database().get_head("COHORT", None, stream)
        if snapshot_id is None:
            raise HTTPException(404, "COHORT_NOT_PREPARED")
        return {
            "message": "C current cohort reference",
            "data": {"cohort_snapshot_id": snapshot_id},
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
                    JobCompleted,
                    AnalysisCompleted,
                    PublicReposCompleted,
                    TrendCompleted,
                    ArchiveTrendCompleted,
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

    @app.post(prefix + "/trends/completed", dependencies=auth)
    def trend_completed(event: TrendCompleted):
        from trend.github import github_trend, parse_innovation_graph_csv
        from trend.job import job_trend

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
                    digest(
                        {
                            "tech_id": event.tech_id,
                            "source": event.source,
                            "periods": event.periods,
                            "versions": compute_versions("TREND", registry),
                            # Validated non-period filters include JOB cohort rule
                            # versions, never values, run IDs or source snapshots.
                            "filters": result.filters,
                        }
                    ),
                )
            ]

        return execute(event, "TREND", None, compute)

    return app
