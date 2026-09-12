"""The loop that turns an analysis request into a checked-out repository.

Three ordering rules carry the correctness of this file, and each of them is a
way to lose or duplicate work if broken.

**The offset is committed last.** Anything committed before the work is done is
a message that disappears when the process dies mid-job.

**A failure that a retry cannot fix is still committed.** Leaving it uncommitted
is how a single bad message stops a partition forever. It goes to the DLQ, where
it can be found, instead of round-tripping invisibly.

**The working directory is removed in `finally`.** A failed job that leaves its
clone behind fills the disk, and the next failure is unrelated and confusing.

Retrying a transient failure is bounded by `max_attempts` for the same reason
the second rule exists: a repository that always times out is transient on every
delivery, and retried without a limit it holds its partition forever.
"""

from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic
from types import FrameType

from pydantic import ValidationError

from analysis.claim import ClaimStatus, ClaimStore
from analysis.clone import CloneError, RepositoryCloner, TransientCloneError
from analysis.configs import ConfigReport, ConfigScanner, facts_from_configs
from analysis.contracts import RepositoryAnalysisRequest
from analysis.judge import (
    Judge,
    Judgement,
    facts_from_annotations,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
    facts_from_sources,
)
from analysis.manifests import DependencyReport, ManifestScanner
from analysis.parse import ParseReport, RepositoryParser
from analysis.publish import ResultPublisher, completed_result, failed_result
from analysis.results import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    SCHEMA_VERSION_V3,
    schema_for_rule_pack,
)
from analysis.rules import RegistryStore, UnknownRegistryVersion
from common.kafka import ConsumedMessage, ConsumerTransport, KafkaTransport

__all__ = ["AnalysisConsumer", "ClaimBusyError", "ClaimLostError", "Outcome"]

log = logging.getLogger("analysis.consumer")


class ClaimBusyError(RuntimeError):
    """The event must remain uncommitted until the active lease expires."""


class ClaimLostError(RuntimeError):
    """This worker's fencing token no longer owns the event."""


@dataclass(frozen=True)
class Outcome:
    """What happened to one message. Returned so tests can assert on it."""

    action: str  # "parsed" | "skipped" | "rejected" | "failed"
    event_id: str | None = None
    error_code: str | None = None
    report: ParseReport | None = None
    dependencies: DependencyReport | None = None
    configs: ConfigReport | None = None
    judgement: Judgement | None = None


@dataclass
class AnalysisConsumer:
    """Owns the poll/handle/commit cycle for one topic."""

    transport: ConsumerTransport
    claims: ClaimStore
    cloner: RepositoryCloner
    parser: RepositoryParser | None = None
    scanner: ManifestScanner | None = None
    config_scanner: ConfigScanner | None = None
    registry: RegistryStore | None = None
    results: ResultPublisher | None = None
    results_v2: ResultPublisher | None = None
    results_v3: ResultPublisher | None = None
    dlq_topic: str | None = None
    dlq_transport: KafkaTransport | None = None
    poll_timeout_ms: int = 1_000
    # Attempts, not retries: the first delivery spends one. The claim's fencing
    # token is that count, so the budget survives redelivery without a second
    # counter. Five is longer than any outage a retry is still the answer to.
    max_attempts: int = 5
    _stopped: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def stop(self, *_: object) -> None:
        """Finish the message in flight, then leave the loop."""
        self._stopped = True

    def install_signal_handlers(self) -> None:
        for received in (signal.SIGTERM, signal.SIGINT):
            signal.signal(received, self._on_signal)

    def _on_signal(self, number: int, _frame: FrameType | None) -> None:
        log.info("shutdown signal %s received; finishing current message", number)
        self.stop()

    def run(self) -> None:
        log.info("analysis consumer started")
        try:
            while not self._stopped:
                for message in self.transport.poll(self.poll_timeout_ms):
                    self.handle(message)
                    # Committing per message is affordable because the consumer
                    # is configured for one record per poll, and it keeps the
                    # redelivery window to a single job.
                    self.transport.commit()
                    if self._stopped:
                        break
        finally:
            self.transport.close()
            log.info("analysis consumer stopped")

    def handle(self, message: ConsumedMessage) -> Outcome:
        """Process one message. Raising means "do not commit"."""
        try:
            request = RepositoryAnalysisRequest.model_validate_json(message.value)
        except ValidationError as invalid:
            # Redelivering this changes nothing: it will fail identically.
            log.warning(
                "rejected malformed request at %s-%s: %s",
                message.partition,
                message.offset,
                invalid.error_count(),
            )
            self._to_dlq(message, "INVALID_EVENT")
            return Outcome("rejected", error_code="INVALID_EVENT")

        payload = request.payload
        claim = self.claims.claim(request.event_id, payload.analysis_id)
        if claim.status is ClaimStatus.TERMINAL:
            log.info(
                "skipped terminal event: eventId=%s analysisId=%s",
                request.event_id,
                payload.analysis_id,
            )
            return Outcome("skipped", event_id=request.event_id)
        if claim.status is ClaimStatus.BUSY:
            # Continuing to poll would let a later commit advance this
            # partition past the unfinished event. Leaving the loop preserves
            # the broker offset for redelivery after the lease expires.
            raise ClaimBusyError(f"event {request.event_id} has an active lease")

        assert claim.token is not None
        token = claim.token
        event_key = sha256(request.event_id.encode("utf-8")).hexdigest()[:16]
        target = f"{payload.analysis_id}-{event_key}-{token}"
        started = monotonic()
        try:
            result = self.cloner.fetch(
                payload.repository_full_name, payload.commit_sha, target
            )
            log.info(
                "cloned: analysisId=%s repo=%s sha=%s bytes=%s traceId=%s",
                payload.analysis_id,
                payload.repository_full_name,
                payload.commit_sha[:12],
                result.bytes_on_disk,
                request.trace_id,
            )

            # Parsing runs inside the same claim: the checkout only exists until
            # the `finally` below, so there is nowhere to resume from later.
            report = (self.parser or RepositoryParser()).parse_repository(result.path)
            log.info(
                "parsed: analysisId=%s files=%s imports=%s distinct=%s "
                "byLanguage=%s skipped=%s traceId=%s",
                payload.analysis_id,
                report.files_parsed,
                len(report.occurrences),
                len(report.modules),
                report.by_language(),
                report.skipped_reasons,
                request.trace_id,
            )
            # Manifests, not just source. A JDBC driver or a cache
            # implementation is declared and then reached only through
            # configuration, so no import ever names it, and an unmatched
            # coordinate is the only fact shaped like something an
            # administrator could promote into the registry.
            dependencies = (self.scanner or ManifestScanner()).scan(result.path)
            log.info(
                "dependencies: analysisId=%s manifests=%s declared=%s distinct=%s "
                "byEcosystem=%s skipped=%s traceId=%s",
                payload.analysis_id,
                dependencies.manifests_read,
                len(dependencies.occurrences),
                len(dependencies.coordinates),
                dependencies.by_ecosystem(),
                dependencies.skipped_reasons,
                request.trace_id,
            )

            configs = (self.config_scanner or ConfigScanner()).scan(result.path)
            judgement = self._judge(request, payload, dependencies, configs, report)

            common44 = bool(judgement and judgement.rule_pack_version)
            result_schema = schema_for_rule_pack(
                judgement.rule_pack_version if judgement else None
            )
            result_publisher = {
                SCHEMA_VERSION: self.results,
                SCHEMA_VERSION_V2: self.results_v2,
                SCHEMA_VERSION_V3: self.results_v3,
            }[result_schema]
            if common44 and result_publisher is None:
                error_code = "UNSUPPORTED_RESULT_SCHEMA"
                self._report_failure(
                    request,
                    error_code,
                    f"{result_schema} publisher is not configured",
                    force_v1=True,
                )
                self._to_dlq(message, error_code)
                if not self.claims.finish(
                    request.event_id, token, "FAILED", error_code
                ):
                    raise ClaimLostError(
                        f"event {request.event_id} lease was taken over before "
                        "result schema failure recording"
                    )
                return Outcome(
                    "failed", event_id=request.event_id, error_code=error_code
                )

            if result_publisher is not None and judgement is not None:
                # Before finish, and therefore before the offset is committed.
                # Publishing afterwards loses results: a crash in that gap
                # leaves a terminal claim with nothing sent, and the redelivery
                # skips it. This way the bad case is a duplicate, which the
                # consumer already tolerates.
                result_publisher.publish(
                    completed_result(
                        request,
                        judgement,
                        report,
                        dependencies,
                        configs=configs,
                        checkout=result.path,
                        bytes_on_disk=result.bytes_on_disk,
                        duration_ms=int((monotonic() - started) * 1000),
                    )
                )

            if not self.claims.finish(request.event_id, token, "CLONED"):
                raise ClaimLostError(
                    f"event {request.event_id} lease was taken over before completion"
                )
            return Outcome(
                "parsed",
                event_id=request.event_id,
                report=report,
                dependencies=dependencies,
                configs=configs,
                judgement=judgement,
            )
        except TransientCloneError as transient:
            if token >= self.max_attempts:
                # Out of budget, so this stops being a retry decision. A repository
                # that fails this way on every delivery is permanently unfetchable
                # from here, and leaving it uncommitted only means nothing behind it
                # in the partition is ever analyzed.
                self._report_failure(request, transient.code, str(transient))
                if not self.claims.finish(
                    request.event_id, token, "FAILED", transient.code
                ):
                    raise ClaimLostError(
                        f"event {request.event_id} lease was taken over "
                        "before the retry budget could be closed out"
                    ) from transient
                log.error(
                    "giving up after %s attempts: analysisId=%s repo=%s code=%s",
                    token,
                    payload.analysis_id,
                    payload.repository_full_name,
                    transient.code,
                )
                self._to_dlq(message, transient.code)
                return Outcome(
                    "failed", event_id=request.event_id, error_code=transient.code
                )
            # Hand the claim back so the redelivery can take it, and do not
            # commit: raising is what keeps the offset where it is. The claim row
            # survives the release, so the next delivery's token resumes the count.
            self.claims.release(request.event_id, token)
            log.warning(
                "transient clone failure on attempt %s of %s, will retry: "
                "analysisId=%s code=%s",
                token,
                self.max_attempts,
                payload.analysis_id,
                transient.code,
            )
            raise
        except UnknownRegistryVersion as unknown:
            # Evaluating against a version that does not exist yields no
            # matches, and no matches is a normal result for a repository that
            # uses nothing. Retrying cannot make the version appear, so this
            # ends the message loudly instead of producing a plausible lie.
            log.error(
                "registry %s is not in the database: analysisId=%s: %s",
                payload.registry_version,
                payload.analysis_id,
                unknown,
            )
            self._report_failure(request, "REGISTRY_VERSION_UNKNOWN", str(unknown))
            if not self.claims.finish(
                request.event_id, token, "FAILED", "REGISTRY_VERSION_UNKNOWN"
            ):
                raise ClaimLostError(
                    f"event {request.event_id} lease was taken over before failure recording"
                ) from unknown
            self._to_dlq(message, "REGISTRY_VERSION_UNKNOWN")
            return Outcome(
                "failed",
                event_id=request.event_id,
                error_code="REGISTRY_VERSION_UNKNOWN",
            )
        except CloneError as permanent:
            self._report_failure(request, permanent.code, str(permanent))
            if not self.claims.finish(
                request.event_id, token, "FAILED", permanent.code
            ):
                raise ClaimLostError(
                    f"event {request.event_id} lease was taken over before failure recording"
                )
            log.error(
                "permanent clone failure: analysisId=%s repo=%s code=%s",
                payload.analysis_id,
                payload.repository_full_name,
                permanent.code,
            )
            self._to_dlq(message, permanent.code)
            return Outcome(
                "failed", event_id=request.event_id, error_code=permanent.code
            )
        finally:
            self.cloner.cleanup(target)

    def _report_failure(
        self,
        request,
        error_code: str,
        detail: str | None = None,
        *,
        force_v1: bool = False,
    ) -> None:
        """Tell the backend the analysis failed, so the job can leave QUEUED.

        The DLQ already holds the request, but that is for operators. Without
        this the person who asked sees "대기 중" forever.
        """
        schema = SCHEMA_VERSION
        publisher = self.results
        if not force_v1:
            if (
                request.payload.registry_version == "registry-20260911.2"
                and self.results_v2 is not None
            ):
                schema, publisher = SCHEMA_VERSION_V2, self.results_v2
            elif (
                request.payload.registry_version
                in {"registry-20260911.3", "registry-20260911.4"}
                and self.results_v3 is not None
            ):
                schema, publisher = SCHEMA_VERSION_V3, self.results_v3
        if publisher is None:
            return
        publisher.publish(
            failed_result(
                request,
                error_code,
                detail,
                schema_version=schema,
            )
        )

    def _judge(
        self, request, payload, dependencies, configs, report
    ) -> Judgement | None:
        """Resolve facts against the registry and evaluate the rules.

        Returns `None` only when no registry is configured, which is how the
        clone-and-parse deployment ran before this stage existed. A configured
        registry that cannot answer is a failure, not an empty judgement.
        """
        if self.registry is None:
            return None

        rule_set = self.registry.load(payload.registry_version)
        judge = Judge(rule_set)
        structural_facts = ()
        if rule_set.rule_pack_version in {
            "rule-pack-20260911.3",
            "rule-pack-20260911.4",
        }:
            from analysis.judge import facts_from_syntax

            structural_facts = facts_from_syntax(report.syntax)
        judgement = judge.judge(
            facts_from_imports(report.occurrences)
            + facts_from_calls(report.calls)
            + facts_from_sources(report.sources)
            + facts_from_annotations(report.annotations)
            + facts_from_dependencies(dependencies.occurrences)
            + facts_from_configs(configs.occurrences)
            + structural_facts
        )
        log.info(
            "judged: analysisId=%s registry=%s technologies=%s evidence=%s "
            "candidates=%s skippedRules=%s traceId=%s",
            payload.analysis_id,
            payload.registry_version,
            {verdict.tech_id: verdict.level for verdict in judgement.verdicts},
            len(judgement.evidence),
            len(judgement.candidates),
            len(judgement.skipped_rule_ids),
            request.trace_id,
        )
        return judgement

    def _to_dlq(self, message: ConsumedMessage, error_code: str) -> None:
        """Best effort. A DLQ that is down must not block the main topic."""
        if not self.dlq_topic or self.dlq_transport is None:
            return
        try:
            self.dlq_transport.send(
                self.dlq_topic, key=message.key, value=message.value
            )
        except Exception as error:  # noqa: BLE001 - never mask the original failure
            log.error("could not publish to the DLQ (%s): %s", error_code, error)


def work_root_from_env(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    return Path(values.get("ANALYSIS_WORK_ROOT", "/tmp/gitjob-analysis"))
