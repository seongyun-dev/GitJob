"""Tell the backend which stage an analysis is in, so a screen can show it.

The consuming half is B's `RepositoryAnalysisProgressConsumer`, and the shape is
pinned by the fixtures under `AI/tests/fixtures/repository-analysis-progress-*`.

### Why this is not part of the result event

The result event says an analysis finished. It arrives once, at the end, and if
it is lost the job stays at `QUEUED` forever -- `publish.py` calls that topic the
only path by which an analysis ever finishes, and treats a send failure as fatal.

These messages are the opposite. They arrive while the work is still running,
they only feed a progress display, and losing one costs nothing but a screen
that updates a step late. Putting them on the result topic would mean one
malformed progress message could send that analysis's *result* to the DLQ.

### Why publishing never raises

`ResultPublisher` raises so a lost result stops the world. Here, raising would
abandon a claim and force a redelivery -- a full re-clone and re-parse -- to
recover a message nobody is waiting on. So the failure is logged and the
analysis continues. A worker with a broken progress topic still produces
correct results; it just looks like the version before this feature existed.

### Why the event id is derived

A claim takeover re-runs the same request and reports the same stages again.
Deriving the id from the request and the stage makes that a duplicate rather
than a second event, which is what B's ordering rule already expects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict

from analysis.results import Identifier

__all__ = [
    "EVENT_TYPE",
    "SCHEMA_VERSION",
    "ProgressPublisher",
    "RepositoryAnalysisProgress",
    "RepositoryAnalysisProgressPayload",
    "Stage",
    "progress_event",
    "progress_event_id",
]

log = logging.getLogger(__name__)

SCHEMA_VERSION = "repository-analysis-progress/v1"
EVENT_TYPE = "repository.analysis.progressed"

#: 워커가 알릴 수 있는 단계. 대기는 접수가, 종료는 결과 이벤트가 만든다.
Stage = Literal["ANALYZING_REPOSITORY", "ATTRIBUTING_CONTRIBUTION"]

STAGE_ANALYZING_REPOSITORY = "ANALYZING_REPOSITORY"
STAGE_ATTRIBUTING_CONTRIBUTION = "ATTRIBUTING_CONTRIBUTION"

#: `analysis_job.current_stage` is VARCHAR(40) on B's side.
_MAX_STAGE_LENGTH = 40
#: The identifier charset both contracts share.
_MAX_IDENTIFIER_LENGTH = 80


class RepositoryAnalysisProgressPayload(BaseModel):
    """Which analysis, and where it got to. Nothing else is needed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: Identifier
    stage: Stage


class RepositoryAnalysisProgress(BaseModel):
    """The envelope, deliberately identical in shape to the result event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    schema_version: Literal["repository-analysis-progress/v1"] = SCHEMA_VERSION
    event_type: Literal["repository.analysis.progressed"] = EVENT_TYPE
    occurred_at: datetime
    trace_id: Identifier
    payload: RepositoryAnalysisProgressPayload


def progress_event_id(request_event_id: str, stage: str) -> str:
    """Stable for one request and stage, so a takeover repeats rather than doubles."""
    candidate = f"prg_{stage}_{request_event_id}"
    if len(candidate) <= _MAX_IDENTIFIER_LENGTH:
        return candidate
    digest = sha256(f"{stage}:{request_event_id}".encode()).hexdigest()
    return "prg_" + digest[:40]


def progress_event(
    *,
    analysis_id: str,
    request_event_id: str,
    trace_id: str,
    stage: Stage,
    now: datetime | None = None,
) -> RepositoryAnalysisProgress:
    """Build one stage transition. Raises on anything the contract refuses."""
    if len(stage) > _MAX_STAGE_LENGTH:
        # B stores this in a fixed-width column; a longer name is silently
        # truncated there and then never matches the name the screen looks for.
        raise ValueError(f"stage name {stage!r} does not fit current_stage")
    return RepositoryAnalysisProgress(
        event_id=progress_event_id(request_event_id, stage),
        occurred_at=now or datetime.now(UTC),
        trace_id=trace_id,
        payload=RepositoryAnalysisProgressPayload(
            analysis_id=analysis_id, stage=stage
        ),
    )


class ProgressPublisher:
    """Sends stage transitions and swallows every failure.

    The swallowing is the point, not an oversight. See the module docstring:
    an analysis that cannot report its progress is still a correct analysis.
    """

    def __init__(self, transport, topic: str) -> None:
        self.transport = transport
        self.topic = topic

    def report(
        self,
        *,
        analysis_id: str,
        request_event_id: str,
        trace_id: str,
        stage: Stage,
    ) -> bool:
        """Return whether it went out. Callers are free to ignore the answer."""
        try:
            event = progress_event(
                analysis_id=analysis_id,
                request_event_id=request_event_id,
                trace_id=trace_id,
                stage=stage,
            )
            self.transport.send(
                self.topic,
                # Keyed by analysis, like the request and result topics, so one
                # analysis's stages stay ordered on one partition.
                key=analysis_id.encode("utf-8"),
                value=event.model_dump_json().encode("utf-8"),
            )
        except Exception:  # noqa: BLE001 - see the class docstring
            log.warning(
                "progress not published: analysisId=%s stage=%s traceId=%s",
                analysis_id,
                stage,
                trace_id,
                exc_info=True,
            )
            return False
        log.info(
            "published progress: analysisId=%s stage=%s traceId=%s",
            analysis_id,
            stage,
            trace_id,
        )
        return True
