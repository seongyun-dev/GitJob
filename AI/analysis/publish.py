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

from analysis.attribution import AttributedEvidence
from analysis.configs import ConfigReport
from analysis.contracts import RepositoryAnalysisRequest
from analysis.judge import EvidenceFact, Judgement
from analysis.manifests import DependencyReport
from analysis.parse import ParseReport
from analysis.personal_level import PersonalTechnologyAssessment
from analysis.results import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    SCHEMA_VERSION_V3,
    SCHEMA_VERSION_V4,
    AnalysisStats,
    AnalysisStatsV2,
    AnalysisStatsV3,
    EvidenceItem,
    EvidenceItemV2,
    EvidenceItemV3,
    EvidenceItemV4,
    PersonalTechnologyAssessmentItem,
    RepositoryAnalysisResult,
    RepositoryAnalysisResultPayload,
    RepositoryAnalysisResultPayloadV2,
    RepositoryAnalysisResultPayloadV3,
    RepositoryAnalysisResultPayloadV4,
    RepositoryAnalysisResultV2,
    RepositoryAnalysisResultV3,
    RepositoryAnalysisResultV4,
    TechnologyCandidate,
    TechnologyCandidateV2,
    TechnologySupportItem,
    TechnologySupportItemV3,
    TechnologyVerdict,
    schema_for_rule_pack,
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
    configs: ConfigReport | None = None,
    schema_version: str | None = None,
    checkout: Path | None = None,
    bytes_on_disk: int = 0,
    duration_ms: int = 0,
    attributed_evidence: tuple[AttributedEvidence, ...] | None = None,
    personal_assessments: tuple[PersonalTechnologyAssessment, ...] | None = None,
) -> (
    RepositoryAnalysisResult
    | RepositoryAnalysisResultV2
    | RepositoryAnalysisResultV3
    | RepositoryAnalysisResultV4
):
    payload = request.payload
    common44 = bool(
        judgement.rule_pack_version
        and judgement.rule_pack_content_sha256
        and judgement.technology_support
    )
    inferred_schema = schema_for_rule_pack(judgement.rule_pack_version)
    depth = inferred_schema == SCHEMA_VERSION_V3
    personal = attributed_evidence is not None or personal_assessments is not None
    if (attributed_evidence is None) != (personal_assessments is None):
        raise ValueError(
            "attributed_evidence and personal_assessments must be supplied together"
        )
    if personal and not depth:
        raise ValueError("personal attribution requires structural Rule Pack evidence")
    if personal and schema_version not in {None, SCHEMA_VERSION_V4}:
        raise ValueError("personal attribution requires repository-analysis-result/v4")
    if depth and not personal and schema_version not in {None, SCHEMA_VERSION_V3}:
        raise ValueError(
            "depth Rule Pack results require repository-analysis-result/v3"
        )
    if schema_version not in {
        None,
        SCHEMA_VERSION,
        SCHEMA_VERSION_V2,
        SCHEMA_VERSION_V3,
        SCHEMA_VERSION_V4,
    }:
        raise ValueError(f"unsupported result schema_version {schema_version!r}")
    if schema_version == SCHEMA_VERSION and common44:
        raise ValueError(
            "common44 Rule Pack results require repository-analysis-result/v2"
        )
    if schema_version == SCHEMA_VERSION_V2 and not common44:
        raise ValueError(
            "repository-analysis-result/v2 requires common44 Rule Pack lineage"
        )
    if schema_version == SCHEMA_VERSION_V3 and not depth:
        raise ValueError(
            "repository-analysis-result/v3 requires depth Rule Pack lineage"
        )
    if schema_version == SCHEMA_VERSION_V4 and not personal:
        raise ValueError("repository-analysis-result/v4 requires personal attribution")
    result_class = RepositoryAnalysisResultV2 if common44 else RepositoryAnalysisResult
    payload_class = (
        RepositoryAnalysisResultPayloadV2
        if common44
        else RepositoryAnalysisResultPayload
    )
    evidence_class = EvidenceItemV2 if common44 else EvidenceItem
    if depth:
        result_class = RepositoryAnalysisResultV3
        payload_class = RepositoryAnalysisResultPayloadV3
        evidence_class = EvidenceItemV3
    if personal:
        result_class = RepositoryAnalysisResultV4
        payload_class = RepositoryAnalysisResultPayloadV4
        evidence_class = EvidenceItemV4
    support = (
        tuple(
            (TechnologySupportItemV3 if depth else TechnologySupportItem)(
                tech_id=tech_id,
                evaluation_scope=(
                    item.get("evaluation_scope")
                    if isinstance(item, dict)
                    else item.evaluation_scope
                ),
                required_fact_types=tuple(
                    item.get("required_fact_types")
                    if isinstance(item, dict)
                    else item.required_fact_types
                ),
                max_supported_level=(
                    item.get("max_supported_level")
                    if isinstance(item, dict)
                    else item.max_supported_level
                ),
                coverage=(
                    item.get("coverage") if isinstance(item, dict) else item.coverage
                ),
                limitations=tuple(
                    item.get("limitations", ())
                    if isinstance(item, dict)
                    else item.limitations
                ),
            )
            for tech_id, item in sorted(judgement.technology_support.items())
        )
        if common44
        else ()
    )
    extra = (
        {
            "rule_pack_version": judgement.rule_pack_version,
            "rule_pack_content_sha256": judgement.rule_pack_content_sha256,
            "technology_support": support,
        }
        if common44
        else {}
    )
    attributed_by_fact_id = {item.fact_id: item for item in (attributed_evidence or ())}
    published_evidence = _published_evidence(judgement, personal_assessments)
    if personal and not {item.fact_id for item in published_evidence}.issubset(
        attributed_by_fact_id
    ):
        raise ValueError("v4 attribution must cover every emitted evidence fact")
    snippets = _snippets(published_evidence, checkout)
    if personal:
        extra["personal_assessments"] = tuple(
            PersonalTechnologyAssessmentItem(
                tech_id=item.tech_id,
                personal_level=item.personal_level,
                assessment_ceiling=item.assessment_ceiling,
                attribution_status=item.attribution_status,
                missing_scope=item.missing_scope,
                decisive_fact_ids=tuple(proof.fact_id for proof in item.proofs),
            )
            for item in personal_assessments or ()
        )
    return result_class(
        event_id=result_event_id(request.event_id),
        occurred_at=datetime.now(UTC),
        trace_id=request.trace_id,
        payload=payload_class(
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
                evidence_class(
                    rule_id=item.rule_id,
                    fact_type=item.fact.fact_type,
                    file_path=item.fact.file,
                    start_line=item.fact.line,
                    end_line=item.fact.line,
                    fact_payload=dict(item.fact.fields),
                    code_snippet=snippets.get((item.fact.file, item.fact.line)),
                    **(
                        {
                            "fact_id": item.fact_id,
                            "repository_analysis_id": attributed_by_fact_id[
                                item.fact_id
                            ].repository_analysis_id,
                            "tech_id": item.tech_id,
                            "attribution": attributed_by_fact_id[
                                item.fact_id
                            ].attribution,
                            "attribution_commit_sha": attributed_by_fact_id[
                                item.fact_id
                            ].attribution_commit_sha,
                            "attribution_missing_scope": attributed_by_fact_id[
                                item.fact_id
                            ].missing_scope,
                        }
                        if personal
                        else {}
                    ),
                )
                for item in published_evidence
            ),
            candidates=tuple(
                (TechnologyCandidateV2 if common44 else TechnologyCandidate)(
                    ecosystem=candidate.ecosystem,
                    coordinate=candidate.coordinate,
                    scope=candidate.scope,
                    occurrence_count=candidate.occurrence_count,
                )
                for candidate in judgement.candidates
                if common44 or candidate.ecosystem in {"MAVEN", "NPM", "PYPI", "NUGET"}
            ),
            stats=(
                AnalysisStatsV3
                if depth
                else AnalysisStatsV2
                if common44
                else AnalysisStats
            )(
                files_parsed=report.files_parsed,
                files_skipped=report.files_skipped,
                import_count=len(report.occurrences),
                dependency_count=len(dependencies.occurrences),
                bytes_on_disk=bytes_on_disk,
                duration_ms=duration_ms,
                **(
                    {
                        "source_file_count": len(report.sources),
                        "annotation_count": len(report.annotations),
                        "config_count": len(configs.occurrences) if configs else 0,
                        "api_call_count": len(report.calls),
                        "skipped_reasons": _combined_skips(
                            report, dependencies, configs
                        ),
                    }
                    if common44
                    else {}
                ),
                **(
                    {"syntax_node_count": len(getattr(report, "syntax", ()))}
                    if depth
                    else {}
                ),
            ),
            **extra,
        ),
    )


def failed_result(
    request: RepositoryAnalysisRequest,
    error_code: str,
    error_detail: str | None = None,
    *,
    schema_version: str = SCHEMA_VERSION,
) -> (
    RepositoryAnalysisResult
    | RepositoryAnalysisResultV2
    | RepositoryAnalysisResultV3
    | RepositoryAnalysisResultV4
):
    """A failure the user has to see.

    The DLQ already holds the request, but the DLQ is for operators. Without
    this event `analysis_job` never leaves `QUEUED` and the person who asked
    for the analysis waits forever.
    """
    payload = request.payload
    if schema_version == SCHEMA_VERSION:
        result_class = RepositoryAnalysisResult
        payload_class = RepositoryAnalysisResultPayload
    elif schema_version == SCHEMA_VERSION_V2:
        result_class = RepositoryAnalysisResultV2
        payload_class = RepositoryAnalysisResultPayloadV2
    elif schema_version == SCHEMA_VERSION_V3:
        result_class = RepositoryAnalysisResultV3
        payload_class = RepositoryAnalysisResultPayloadV3
    elif schema_version == SCHEMA_VERSION_V4:
        result_class = RepositoryAnalysisResultV4
        payload_class = RepositoryAnalysisResultPayloadV4
    else:
        raise ValueError(f"unsupported result schema_version {schema_version!r}")
    return result_class(
        event_id=result_event_id(request.event_id),
        occurred_at=datetime.now(UTC),
        trace_id=request.trace_id,
        payload=payload_class(
            analysis_id=payload.analysis_id,
            request_event_id=request.event_id,
            registry_version=payload.registry_version,
            commit_sha=payload.commit_sha,
            status="FAILED",
            error_code=error_code,
            error_detail=(error_detail or None) and error_detail[:500],
        ),
    )


def _combined_skips(
    report: ParseReport,
    dependencies: DependencyReport,
    configs: ConfigReport | None,
) -> dict[str, int]:
    combined: dict[str, int] = {}
    for prefix, reasons in (
        ("source", report.skipped_reasons),
        ("manifest", dependencies.skipped_reasons),
        ("config", configs.skipped_reasons if configs else {}),
    ):
        for reason, count in reasons.items():
            combined[f"{prefix}:{reason}"] = count
    return combined


def _published_evidence(
    judgement: Judgement,
    personal_assessments: tuple[PersonalTechnologyAssessment, ...] | None,
) -> tuple[EvidenceFact, ...]:
    published = {item.fact_id: item for item in judgement.evidence}
    for assessment in personal_assessments or ():
        for proof in assessment.proofs:
            published.setdefault(proof.fact_id, proof.evidence)
    return tuple(published.values())


def _snippets(
    evidence: tuple[EvidenceFact, ...], checkout: Path | None
) -> dict[tuple[str, int], str]:
    """The source line behind each evidence item, read once per file."""
    if checkout is None:
        return {}
    wanted: dict[str, set[int]] = {}
    for item in evidence:
        wanted.setdefault(item.fact.file, set()).add(item.fact.line)

    found: dict[tuple[str, int], str] = {}
    for relative, numbers in wanted.items():
        try:
            lines = (
                (checkout / relative)
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
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

    def __init__(
        self,
        transport,
        topic: str,
        schema_version: str | None = None,
    ) -> None:
        if schema_version not in {
            None,
            SCHEMA_VERSION,
            SCHEMA_VERSION_V2,
            SCHEMA_VERSION_V3,
            SCHEMA_VERSION_V4,
        }:
            raise ValueError(f"unsupported result schema_version {schema_version!r}")
        self.transport = transport
        self.topic = topic
        self.schema_version = schema_version

    def publish(
        self,
        result: RepositoryAnalysisResult
        | RepositoryAnalysisResultV2
        | RepositoryAnalysisResultV3
        | RepositoryAnalysisResultV4,
    ) -> None:
        if (
            self.schema_version is not None
            and result.schema_version != self.schema_version
        ):
            raise ValueError(
                f"result schema {result.schema_version!r} cannot be published to "
                f"{self.schema_version!r} topic {self.topic!r}"
            )
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
