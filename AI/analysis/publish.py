"""Turn a judgement into the result event and send it.

The contract is `docs/data/contracts/repository-analysis-result-v1.schema.json`
and the model is `results.py`. This module is the part that fills it in.

### Where publishing sits in the order

Before `claims.finish`, and therefore before the offset is committed.

Publishing after `finish` looks tidier and loses results. A crash in that gap
leaves a terminal claim with nothing published: the redelivery sees `CLONED`,
skips, commits, and the analysis is gone with no trace. Publishing first makes
the bad case a duplicate instead, which the consumer already has to tolerate —
delivery is at-least-once, and `event_id` is the deduplication key.

### Why the result event id is derived, not random

A takeover re-runs the same request and publishes again. A fresh random id
would make that a second result for one analysis, and the backend would write
the evidence twice. Deriving the id from the request means a redelivery
produces the same id, which is exactly what a deduplication key is for.

### Snippets are captured here or never

`consumer.py` deletes the checkout in its `finally`. A permalink survives
without a snippet, but nothing else does: showing evidence for a repository
that has since been rewritten, or for a private one, needs the line we saw.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from analysis.contracts import RepositoryAnalysisRequest
from analysis.judge import Judgement
from analysis.manifests import DependencyReport
from analysis.parse import ParseReport
from analysis.results import (
    AnalysisStats,
    EvidenceItem,
    RepositoryAnalysisResult,
    RepositoryAnalysisResultPayload,
    TechnologyCandidate,
    TechnologyVerdict,
)

__all__ = ["ResultPublisher", "completed_result", "failed_result", "result_event_id"]

log = logging.getLogger("analysis.publish")

#: Long enough to show the declaration or the import, short enough that a
#: thousand of them stay inside one Kafka message.
_MAX_SNIPPET = 300


def result_event_id(request_event_id: str) -> str:
    """Stable for one request, so a redelivery deduplicates instead of doubling."""
    candidate = f"res_{request_event_id}"
    if len(candidate) <= 80:
        return candidate
    return "res_" + sha256(request_event_id.encode("utf-8")).hexdigest()[:40]


def completed_result(
    request: RepositoryAnalysisRequest,
    judgement: Judgement,
    report: ParseReport,
    dependencies: DependencyReport,
    *,
    checkout: Path | None = None,
    bytes_on_disk: int = 0,
    duration_ms: int = 0,
) -> RepositoryAnalysisResult:
    payload = request.payload
    snippets = _snippets(judgement, checkout)
    return RepositoryAnalysisResult(
        event_id=result_event_id(request.event_id),
        occurred_at=datetime.now(UTC),
        trace_id=request.trace_id,
        payload=RepositoryAnalysisResultPayload(
            analysis_id=payload.analysis_id,
            request_event_id=request.event_id,
            registry_version=payload.registry_version,
            commit_sha=payload.commit_sha,
            status="COMPLETED",
            technologies=tuple(
                TechnologyVerdict(
                    tech_id=verdict.tech_id,
                    level=verdict.level,
                    matched_rule_ids=verdict.matched_rule_ids,
                )
                for verdict in judgement.verdicts
            ),
            evidence=tuple(
                EvidenceItem(
                    rule_id=item.rule_id,
                    fact_type=item.fact.fact_type,
                    file_path=item.fact.file,
                    start_line=item.fact.line,
                    end_line=item.fact.line,
                    fact_payload=dict(item.fact.fields),
                    code_snippet=snippets.get((item.fact.file, item.fact.line)),
                )
                for item in judgement.evidence
            ),
            candidates=tuple(
                TechnologyCandidate(
                    ecosystem=candidate.ecosystem,
                    coordinate=candidate.coordinate,
                    scope=candidate.scope,
                    occurrence_count=candidate.occurrence_count,
                )
                for candidate in judgement.candidates
            ),
            stats=AnalysisStats(
                files_parsed=report.files_parsed,
                files_skipped=report.files_skipped,
                import_count=len(report.occurrences),
                dependency_count=len(dependencies.occurrences),
                bytes_on_disk=bytes_on_disk,
                duration_ms=duration_ms,
            ),
        ),
    )


def failed_result(
    request: RepositoryAnalysisRequest,
    error_code: str,
    error_detail: str | None = None,
) -> RepositoryAnalysisResult:
    """A failure the user has to see.

    The DLQ already holds the request, but the DLQ is for operators. Without
    this event `analysis_job` never leaves `QUEUED` and the person who asked
    for the analysis waits forever.
    """
    payload = request.payload
    return RepositoryAnalysisResult(
        event_id=result_event_id(request.event_id),
        occurred_at=datetime.now(UTC),
        trace_id=request.trace_id,
        payload=RepositoryAnalysisResultPayload(
            analysis_id=payload.analysis_id,
            request_event_id=request.event_id,
            registry_version=payload.registry_version,
            commit_sha=payload.commit_sha,
            status="FAILED",
            error_code=error_code,
            error_detail=(error_detail or None) and error_detail[:500],
        ),
    )


def _snippets(
    judgement: Judgement, checkout: Path | None
) -> dict[tuple[str, int], str]:
    """The source line behind each evidence item, read once per file."""
    if checkout is None:
        return {}
    wanted: dict[str, set[int]] = {}
    for item in judgement.evidence:
        wanted.setdefault(item.fact.file, set()).add(item.fact.line)

    found: dict[tuple[str, int], str] = {}
    for relative, numbers in wanted.items():
        try:
            lines = (checkout / relative).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError as unreadable:
            # The evidence still stands: a permalink needs only the path and
            # the line, and the snippet is declared optional for this reason.
            log.debug("no snippet for %s: %s", relative, unreadable)
            continue
        for number in numbers:
            if 1 <= number <= len(lines):
                found[(relative, number)] = lines[number - 1].strip()[:_MAX_SNIPPET]
    return found


class ResultPublisher:
    """Sends result events, and says plainly when it cannot.

    A failure here must not be swallowed the way a DLQ failure is. The DLQ is a
    place to look afterwards; this topic is the only path by which an analysis
    ever finishes, so losing a message here strands the job at `QUEUED`.
    """

    def __init__(self, transport, topic: str) -> None:
        self.transport = transport
        self.topic = topic

    def publish(self, result: RepositoryAnalysisResult) -> None:
        self.transport.send(
            self.topic,
            # Keyed by analysis so every event for one analysis keeps its order
            # on one partition, matching how the request topic is keyed.
            key=result.payload.analysis_id.encode("utf-8"),
            value=result.model_dump_json().encode("utf-8"),
        )
        log.info(
            "published result: analysisId=%s status=%s technologies=%s evidence=%s "
            "candidates=%s traceId=%s",
            result.payload.analysis_id,
            result.payload.status,
            len(result.payload.technologies),
            len(result.payload.evidence),
            len(result.payload.candidates),
            result.trace_id,
        )
