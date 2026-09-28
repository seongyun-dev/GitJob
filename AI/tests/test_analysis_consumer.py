"""The consumer's ordering rules, which are what make redelivery survivable.

No broker and no database: the transport and the claim store are fakes, the
way `common.kafka`'s docstring says its tests work.
"""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from analysis.claim import Claim, ClaimStatus
from analysis.clone import (
    CloneResult,
    CredentialRequiredCloneError,
    PermanentCloneError,
    TransientCloneError,
)
from analysis.consumer import AnalysisConsumer, ClaimLostError
from analysis.judge import Candidate, Judgement
from analysis.parse import ImportOccurrence, ParseReport
from analysis.publish import ResultPublisher
from analysis.results import SCHEMA_VERSION, SCHEMA_VERSION_V2
from analysis.rulepack import (
    RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)
from analysis.rules import RegistryStore, UnknownRegistryVersion
from common.kafka import ConsumedMessage

TOPIC = "gitjob.repository-analysis.requests.v1"
SHA = "0123456789abcdef0123456789abcdef01234567"


def work_target(
    analysis_id: str = "an_1", event_id: str = "ev_1", token: int = 1
) -> str:
    event_key = sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return f"{analysis_id}-{event_key}-{token}"


def event(event_id: str = "ev_1", analysis_id: str = "an_1", **overrides) -> bytes:
    body = {
        "event_id": event_id,
        "schema_version": "repository-analysis-request/v1",
        "event_type": "repository.analysis.requested",
        "occurred_at": "2026-09-08T01:02:03Z",
        "trace_id": "tr_1",
        "payload": {
            "analysis_id": analysis_id,
            "analysis_repository_id": "ar_1",
            "github_repository_id": 123456789,
            "repository_full_name": "octocat/gitjob",
            "branch_name": "feature/cdc",
            "commit_sha": SHA,
            "analysis_mode": "SNAPSHOT",
            "registry_version": "technology-registry/v1",
        },
    }
    body["payload"].update(overrides)
    return json.dumps(body).encode("utf-8")


def message(value: bytes, offset: int = 0) -> ConsumedMessage:
    return ConsumedMessage(
        topic=TOPIC, partition=0, offset=offset, key=b"ar_1", value=value
    )


class FakeClaims:
    def __init__(
        self,
        status: ClaimStatus = ClaimStatus.ACQUIRED,
        *,
        token: int = 1,
        finish_ok: bool = True,
    ) -> None:
        self.status = status
        self.token = token
        self.finish_ok = finish_ok
        self.claimed: list[str] = []
        self.released: list[tuple[str, int]] = []
        self.finished: list[tuple[str, int, str, str | None]] = []

    def claim(self, event_id: str, analysis_id: str) -> Claim:
        self.claimed.append(event_id)
        token = self.token if self.status is ClaimStatus.ACQUIRED else None
        return Claim(self.status, token)

    def release(self, event_id: str, token: int) -> bool:
        self.released.append((event_id, token))
        return True

    def finish(
        self, event_id: str, token: int, state: str, error_code: str | None = None
    ) -> bool:
        self.finished.append((event_id, token, state, error_code))
        return self.finish_ok


class FakeCloner:
    def __init__(self, work_root, result=None, error=None) -> None:
        self.work_root = work_root
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str, str, str | None]] = []
        self.cleaned: list[str] = []

    def fetch(
        self,
        full_name: str,
        commit_sha: str,
        into: str,
        *,
        access_token: str | None = None,
    ) -> CloneResult:
        self.calls.append((full_name, commit_sha, into, access_token))
        if self._error is not None:
            raise self._error
        return self._result or CloneResult(path=self.work_root / into, bytes_on_disk=10)

    def cleanup(self, into: str) -> None:
        self.cleaned.append(into)
        path = self.work_root / into
        if path.exists():
            import shutil

            shutil.rmtree(path)


class BatchTransport:
    def __init__(self, messages: list[ConsumedMessage]) -> None:
        self.messages = messages
        self.consumer: AnalysisConsumer | None = None
        self.polled = False
        self.commits = 0
        self.deferred: list[ConsumedMessage] = []
        self.closed = False

    def poll(self, _timeout_ms: int) -> list[ConsumedMessage]:
        if self.polled:
            return []
        self.polled = True
        assert self.consumer is not None
        self.consumer.stop()
        return self.messages

    def commit(self) -> None:
        self.commits += 1

    def defer(self, message: ConsumedMessage) -> None:
        self.deferred.append(message)

    def close(self) -> None:
        self.closed = True


class DeferredRetryTransport:
    """Redeliver the exact record after the consumer rewinds its offset."""

    def __init__(self, message: ConsumedMessage) -> None:
        self.message = message
        self.commits = 0
        self.closed = False
        self.deferred: list[ConsumedMessage] = []
        self.consumer: AnalysisConsumer | None = None

    def poll(self, _timeout_ms: int) -> list[ConsumedMessage]:
        return [self.message]

    def commit(self) -> None:
        self.commits += 1
        assert self.consumer is not None
        self.consumer.stop()

    def defer(self, message: ConsumedMessage) -> None:
        self.deferred.append(message)

    def close(self) -> None:
        self.closed = True


class BusyThenAcquiredClaims(FakeClaims):
    def __init__(self) -> None:
        super().__init__(ClaimStatus.BUSY)
        self.calls = 0

    def claim(self, event_id: str, analysis_id: str) -> Claim:
        self.calls += 1
        if self.calls == 1:
            return super().claim(event_id, analysis_id)
        self.status = ClaimStatus.ACQUIRED
        return super().claim(event_id, analysis_id)


class FakeResults:
    def __init__(self, fail: bool = False) -> None:
        self.published: list = []
        self.fail = fail

    def send(self, topic, *, key, value):
        if self.fail:
            raise RuntimeError("results broker is down")
        self.published.append((topic, key, value))

    def publisher(
        self,
        topic: str = "gitjob.repository-analysis.results.v1",
        schema_version: str | None = None,
    ) -> ResultPublisher:
        return ResultPublisher(self, topic, schema_version=schema_version)


class EmptyRegistry:
    """Loads a registry that matches nothing. Enough to exercise publishing."""

    def load(self, registry_version):
        from analysis.rules import Mapping, RuleSet

        return RuleSet(
            registry_version=registry_version,
            mappings=(Mapping("x", "IMPORT_PATH", "JAVA", "com.example.x", "PREFIX"),),
            rules=(),
        )


class FakeDlq:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, bytes]] = []
        self.fail = fail

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("dlq is down")
        self.sent.append((topic, value))

    def close(self) -> None:  # pragma: no cover - interface completeness
        pass


def build(
    tmp_path, *, claims=None, cloner=None, dlq=None, **overrides
) -> AnalysisConsumer:
    return AnalysisConsumer(
        transport=None,  # handle() never touches the transport
        claims=claims or FakeClaims(),
        cloner=cloner or FakeCloner(tmp_path),
        dlq_topic="gitjob.analysis.dlq" if dlq else None,
        dlq_transport=dlq,
        **overrides,
    )


def test_clone_is_pinned_to_the_commit_not_the_branch(tmp_path):
    cloner = FakeCloner(tmp_path)
    outcome = build(tmp_path, cloner=cloner).handle(message(event()))

    assert outcome.action == "parsed"
    assert cloner.calls == [("octocat/gitjob", SHA, work_target(), None)]


def test_busy_redelivery_is_retried_without_terminating_the_consumer(tmp_path):
    claims = BusyThenAcquiredClaims()
    busy = message(event())
    transport = DeferredRetryTransport(busy)
    consumer = AnalysisConsumer(
        transport=transport, claims=claims, cloner=FakeCloner(tmp_path)
    )
    transport.consumer = consumer

    consumer.run()

    assert claims.calls == 2
    assert transport.commits == 1
    assert transport.deferred == [busy]
    assert transport.closed is True


def test_result_contract_validation_is_terminal_and_does_not_leave_a_lease(tmp_path):
    claims, dlq, results = FakeClaims(), FakeDlq(), FakeResults()
    consumer = build(
        tmp_path,
        claims=claims,
        dlq=dlq,
        results=results.publisher(),
    )
    invalid = Judgement(
        verdicts=(),
        evidence=(),
        candidates=(Candidate("PYPI", "broken", "x" * 1025, 1),),
    )
    consumer._judge = lambda *_args: invalid

    outcome = consumer.handle(message(event()))

    assert outcome.action == "failed"
    assert outcome.error_code == "RESULT_CONTRACT_INVALID"
    assert claims.finished == [("ev_1", 1, "FAILED", "RESULT_CONTRACT_INVALID")]
    assert len(results.published) == 1
    assert len(dlq.sent) == 1


def test_private_repository_retries_the_same_pinned_commit_with_broker_token(tmp_path):
    secret = "github-token"

    class PrivateCloner(FakeCloner):
        def fetch(self, full_name, commit_sha, into, *, access_token=None):
            self.calls.append((full_name, commit_sha, into, access_token))
            if access_token is None:
                raise CredentialRequiredCloneError(
                    "REPOSITORY_CREDENTIAL_REQUIRED", "credential required"
                )
            return CloneResult(path=tmp_path / into, bytes_on_disk=10)

    class Broker:
        def __init__(self):
            self.calls = []

        def access_token_for(self, **request):
            self.calls.append(request)
            return secret

    cloner = PrivateCloner(tmp_path)
    broker = Broker()
    outcome = build(tmp_path, cloner=cloner, credential_broker=broker).handle(
        message(event())
    )

    assert outcome.action == "parsed"
    assert cloner.calls == [
        ("octocat/gitjob", SHA, work_target(), None),
        ("octocat/gitjob", SHA, work_target(), secret),
    ]
    assert broker.calls == [
        {
            "analysis_id": "an_1",
            "analysis_repository_id": "ar_1",
            "github_repository_id": 123456789,
            "repository_full_name": "octocat/gitjob",
            "commit_sha": SHA,
        }
    ]


def test_public_repository_never_calls_the_credential_broker(tmp_path):
    class Broker:
        def access_token_for(self, **_request):
            raise AssertionError("public clone must not request a credential")

    assert build(tmp_path, credential_broker=Broker()).handle(message(event())).action == "parsed"


def test_private_repository_without_broker_keeps_the_existing_failure_contract(tmp_path):
    cloner = FakeCloner(
        tmp_path,
        error=CredentialRequiredCloneError(
            "REPOSITORY_CREDENTIAL_REQUIRED", "credential required"
        ),
    )

    outcome = build(tmp_path, cloner=cloner).handle(message(event()))

    assert outcome.action == "failed"
    assert outcome.error_code == "REPOSITORY_NOT_ACCESSIBLE"


def test_transient_credential_broker_failure_releases_the_claim_for_redelivery(tmp_path):
    claims = FakeClaims()
    cloner = FakeCloner(
        tmp_path,
        error=CredentialRequiredCloneError(
            "REPOSITORY_CREDENTIAL_REQUIRED", "credential required"
        ),
    )

    class Broker:
        def access_token_for(self, **_request):
            raise TransientCloneError(
                "CREDENTIAL_BROKER_UNAVAILABLE", "temporarily unavailable"
            )

    with pytest.raises(TransientCloneError):
        build(
            tmp_path, claims=claims, cloner=cloner, credential_broker=Broker()
        ).handle(message(event()))

    assert claims.released == [("ev_1", 1)]
    assert claims.finished == []


def test_a_cloned_repository_is_parsed_before_the_checkout_is_removed(tmp_path):
    # The checkout only exists until handle()'s finally, so parsing cannot be
    # deferred to a later delivery.
    class RecordingParser:
        def __init__(self) -> None:
            self.seen: list[bool] = []

        def parse_repository(self, root):
            self.seen.append(root.exists())
            return ParseReport(
                occurrences=(), files_parsed=0, files_skipped=0, bytes_parsed=0
            )

    checkout = tmp_path / work_target()
    checkout.mkdir()
    parser = RecordingParser()
    consumer = build(tmp_path, cloner=FakeCloner(tmp_path))
    consumer.parser = parser

    outcome = consumer.handle(message(event()))

    assert outcome.action == "parsed"
    assert parser.seen == [True]
    assert not checkout.exists()


def test_the_parse_report_is_returned_with_the_outcome(tmp_path):
    report = ParseReport(
        occurrences=(ImportOccurrence("react", "javascript", "JAVASCRIPT", "a.js", 1),),
        files_parsed=1,
        files_skipped=0,
        bytes_parsed=20,
    )

    class FixedParser:
        def parse_repository(self, root):
            return report

    consumer = build(tmp_path, cloner=FakeCloner(tmp_path))
    consumer.parser = FixedParser()

    assert consumer.handle(message(event())).report is report


def test_malformed_message_goes_to_the_dlq_and_never_claims(tmp_path):
    # Redelivering an unparseable message changes nothing, so it must be
    # committed. Committing is the caller's job; not raising is how we say so.
    claims, dlq = FakeClaims(), FakeDlq()
    outcome = build(tmp_path, claims=claims, dlq=dlq).handle(message(b"{not json"))

    assert outcome.action == "rejected"
    assert claims.claimed == []
    assert len(dlq.sent) == 1


def test_a_future_schema_version_is_rejected_rather_than_guessed(tmp_path):
    body = json.loads(event())
    body["schema_version"] = "repository-analysis-request/v2"
    outcome = build(tmp_path).handle(message(json.dumps(body).encode()))

    assert outcome.action == "rejected"


def test_terminal_redelivery_of_the_same_event_does_not_clone_again(tmp_path):
    claims = FakeClaims(ClaimStatus.TERMINAL)
    cloner = FakeCloner(tmp_path)

    outcome = build(tmp_path, claims=claims, cloner=cloner).handle(message(event()))

    assert outcome.action == "skipped"
    assert cloner.calls == []


def test_busy_redelivery_is_deferred_without_stopping_the_worker(tmp_path):
    claims = FakeClaims(ClaimStatus.BUSY)
    cloner = FakeCloner(tmp_path)
    busy = message(event(), 7)
    transport = BatchTransport([busy, message(event("ev_2", "an_2"), 8)])
    consumer = AnalysisConsumer(
        transport=transport,
        claims=claims,
        cloner=cloner,
        poll_timeout_ms=0,
    )
    transport.consumer = consumer

    consumer.run()

    assert transport.commits == 0
    assert transport.deferred == [busy]
    assert transport.closed is True
    assert claims.claimed == ["ev_1"]
    assert cloner.calls == []


def test_lost_lease_cannot_finish_or_commit_after_a_takeover(tmp_path):
    claims = FakeClaims(token=4, finish_ok=False)
    cloner = FakeCloner(tmp_path)
    transport = BatchTransport([message(event(), 7)])
    consumer = AnalysisConsumer(transport=transport, claims=claims, cloner=cloner)
    transport.consumer = consumer

    with pytest.raises(ClaimLostError):
        consumer.run()

    assert transport.commits == 0
    assert claims.finished == [("ev_1", 4, "CLONED", None)]


def test_transient_failure_releases_the_claim_and_refuses_to_commit(tmp_path):
    # Raising is the signal: the loop only commits after handle() returns.
    claims = FakeClaims()
    cloner = FakeCloner(
        tmp_path, error=TransientCloneError("GITHUB_UNAVAILABLE", "boom")
    )

    with pytest.raises(TransientCloneError):
        build(tmp_path, claims=claims, cloner=cloner).handle(message(event()))

    assert claims.released == [("ev_1", 1)]
    assert claims.finished == []


def test_a_transient_failure_inside_the_budget_still_retries(tmp_path):
    # The token is the attempt count, so attempt 4 of 5 has one left to spend.
    claims = FakeClaims(token=4)
    cloner = FakeCloner(tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "slow"))

    with pytest.raises(TransientCloneError):
        build(tmp_path, claims=claims, cloner=cloner, max_attempts=5).handle(
            message(event())
        )

    assert claims.released == [("ev_1", 4)]
    assert claims.finished == []


def test_the_last_transient_failure_becomes_permanent(tmp_path):
    # A repository that always times out is transient on every single delivery.
    # Retried without a limit it holds its partition forever, so the budget
    # running out has to end the message rather than replay it again.
    claims, dlq = FakeClaims(token=5), FakeDlq()
    cloner = FakeCloner(tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "slow"))

    outcome = build(
        tmp_path, claims=claims, cloner=cloner, dlq=dlq, max_attempts=5
    ).handle(message(event()))

    assert outcome.action == "failed"
    assert outcome.error_code == "CLONE_TIMEOUT"
    assert claims.finished == [("ev_1", 5, "FAILED", "CLONE_TIMEOUT")]
    assert claims.released == []  # not handed back: there is nothing left to retry
    assert len(dlq.sent) == 1


def test_giving_up_on_a_lost_lease_does_not_record_someone_elses_outcome(tmp_path):
    # The budget ran out, but a takeover already happened. Writing FAILED here
    # would overwrite the new owner's work with a stale verdict.
    claims = FakeClaims(token=5, finish_ok=False)
    cloner = FakeCloner(tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "slow"))

    with pytest.raises(ClaimLostError):
        build(
            tmp_path, claims=claims, cloner=cloner, dlq=FakeDlq(), max_attempts=5
        ).handle(message(event()))


def test_a_budget_below_one_is_refused(tmp_path):
    # Zero attempts would send every request to the DLQ without ever trying.
    with pytest.raises(ValueError):
        build(tmp_path, max_attempts=0)


def test_the_result_is_published_before_the_claim_is_finished(tmp_path):
    # Publishing after finish loses results: a crash in that gap leaves a
    # terminal claim with nothing sent, and the redelivery skips it.
    order: list[str] = []

    class RecordingResults(FakeResults):
        def send(self, topic, *, key, value):
            order.append("publish")
            super().send(topic, key=key, value=value)

    class RecordingClaims(FakeClaims):
        def finish(self, event_id, token, state, error_code=None):
            order.append("finish")
            return super().finish(event_id, token, state, error_code)

    results = RecordingResults()
    outcome = build(
        tmp_path,
        claims=RecordingClaims(),
        registry=EmptyRegistry(),
        results=results.publisher(),
    ).handle(message(event()))

    assert outcome.action == "parsed"
    assert order == ["publish", "finish"]


def test_a_failed_publish_leaves_the_claim_unfinished(tmp_path):
    # The offset stays where it is and the lease expires, so a redelivery
    # retries. Committing here would strand the job at QUEUED.
    claims = FakeClaims()

    with pytest.raises(RuntimeError, match="results broker is down"):
        build(
            tmp_path,
            claims=claims,
            registry=EmptyRegistry(),
            results=FakeResults(fail=True).publisher(),
        ).handle(message(event()))

    assert claims.finished == []


def test_invalid_result_contract_becomes_a_terminal_failure(tmp_path, monkeypatch):
    claims, results, dlq = FakeClaims(), FakeResults(), FakeDlq()

    def invalid_result(*_args, **_kwargs):
        from analysis.results import TechnologyCandidate

        TechnologyCandidate(
            ecosystem="PYPI",
            coordinate="pytest",
            scope="x" * 1025,
            occurrence_count=1,
        )

    monkeypatch.setattr("analysis.consumer.completed_result", invalid_result)

    outcome = build(
        tmp_path,
        claims=claims,
        dlq=dlq,
        registry=EmptyRegistry(),
        results=results.publisher(),
    ).handle(message(event()))

    assert outcome.action == "failed"
    assert outcome.error_code == "RESULT_CONTRACT_INVALID"
    assert claims.finished == [
        ("ev_1", 1, "FAILED", "RESULT_CONTRACT_INVALID")
    ]
    assert len(dlq.sent) == 1
    body = json.loads(results.published[0][2])
    assert body["payload"]["error_code"] == "RESULT_CONTRACT_INVALID"


def test_a_permanent_clone_failure_is_reported_to_the_backend_too(tmp_path):
    # The DLQ is for operators. Without this event the user never learns their
    # deleted repository could not be analyzed.
    results = FakeResults()
    cloner = FakeCloner(
        tmp_path, error=PermanentCloneError("REPOSITORY_NOT_FOUND", "gone")
    )

    outcome = build(
        tmp_path, cloner=cloner, dlq=FakeDlq(), results=results.publisher()
    ).handle(message(event()))

    assert outcome.action == "failed"
    body = json.loads(results.published[0][2])
    assert body["payload"]["status"] == "FAILED"
    assert body["payload"]["error_code"] == "REPOSITORY_NOT_FOUND"


def test_an_unknown_registry_version_is_reported_to_the_backend_too(tmp_path):
    class MissingRegistry:
        def load(self, registry_version):
            raise UnknownRegistryVersion(registry_version)

    results = FakeResults()
    outcome = build(
        tmp_path, dlq=FakeDlq(), registry=MissingRegistry(), results=results.publisher()
    ).handle(message(event()))

    assert outcome.action == "failed"
    body = json.loads(results.published[0][2])
    assert body["payload"]["error_code"] == "REGISTRY_VERSION_UNKNOWN"


def test_an_exhausted_retry_budget_is_reported_to_the_backend_too(tmp_path):
    results = FakeResults()
    cloner = FakeCloner(tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "slow"))

    outcome = build(
        tmp_path,
        claims=FakeClaims(token=5),
        cloner=cloner,
        dlq=FakeDlq(),
        results=results.publisher(),
        max_attempts=5,
    ).handle(message(event()))

    assert outcome.action == "failed"
    body = json.loads(results.published[0][2])
    assert body["payload"]["error_code"] == "CLONE_TIMEOUT"


def test_a_transient_failure_inside_the_budget_publishes_nothing(tmp_path):
    # It will be retried. Announcing a failure the user would then see reversed
    # is worse than saying nothing yet.
    results = FakeResults()
    cloner = FakeCloner(tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "slow"))

    with pytest.raises(TransientCloneError):
        build(
            tmp_path, cloner=cloner, results=results.publisher(), max_attempts=5
        ).handle(message(event()))

    assert results.published == []


def test_a_registry_version_that_is_not_in_the_database_fails_loudly(tmp_path):
    # Evaluating against a missing version returns no matches, and no matches is
    # what a repository using nothing looks like. Silence here would ship a
    # plausible lie, so it ends the message instead.
    class MissingRegistry:
        def load(self, registry_version):
            raise UnknownRegistryVersion(registry_version)

    claims, dlq = FakeClaims(), FakeDlq()
    outcome = build(
        tmp_path, claims=claims, dlq=dlq, registry=MissingRegistry()
    ).handle(message(event()))

    assert outcome.action == "failed"
    assert outcome.error_code == "REGISTRY_VERSION_UNKNOWN"
    assert claims.finished == [("ev_1", 1, "FAILED", "REGISTRY_VERSION_UNKNOWN")]
    assert len(dlq.sent) == 1


def test_no_registry_configured_still_clones_and_parses(tmp_path):
    # The deployment before this stage existed. A judgement of None is the
    # absence of the stage, not an empty result.
    outcome = build(tmp_path).handle(message(event()))

    assert outcome.action == "parsed"
    assert outcome.judgement is None


def test_manifests_are_scanned_inside_the_same_claim(tmp_path):
    # The checkout is deleted in the finally below, so dependencies have to be
    # read now or not at all. They are also the only facts shaped like something
    # an administrator could promote into the registry.
    checkout = tmp_path / "an_1"
    checkout.mkdir()
    (checkout / "build.gradle").write_text(
        "dependencies {\n  implementation 'org.postgresql:postgresql'\n}\n",
        encoding="utf-8",
    )
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=10))

    outcome = build(tmp_path, cloner=cloner).handle(message(event()))

    assert outcome.action == "parsed"
    assert outcome.dependencies is not None
    assert outcome.dependencies.coordinates == ("MAVEN:org.postgresql:postgresql",)


def test_default_v1_consumer_handles_new_manifest_ecosystems_without_contract_drift(
    tmp_path,
):
    checkout = tmp_path / "go-repository"
    checkout.mkdir()
    (checkout / "go.mod").write_text(
        "module example.com/app\nrequire github.com/redis/go-redis/v9 v9.0.0\n",
        encoding="utf-8",
    )
    (checkout / "main.go").write_text(
        "package main\nfunc main() {}\n", encoding="utf-8"
    )
    results = FakeResults()
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=40))

    outcome = build(
        tmp_path,
        cloner=cloner,
        registry=EmptyRegistry(),
        results=results.publisher(),
    ).handle(message(event()))

    assert outcome.action == "parsed"
    body = json.loads(results.published[0][2])
    assert body["schema_version"] == "repository-analysis-result/v1"
    assert body["payload"]["candidates"] == []
    assert all(
        item["fact_type"] != "SOURCE_FILE" for item in body["payload"]["evidence"]
    )


def test_dual_publishers_route_legacy_v1_and_common44_v2_by_rule_lineage(tmp_path):
    checkout = tmp_path / "react-repository"
    (checkout / "src").mkdir(parents=True)
    (checkout / "package.json").write_text(
        '{"dependencies":{"react":"18.3.1"}}\n', encoding="utf-8"
    )
    (checkout / "src/App.tsx").write_text(
        "import React from 'react';\nReact.useState(0);\n", encoding="utf-8"
    )
    registry_path = (
        RULE_PACK_PATH.parents[2]
        / "registry"
        / "data"
        / "technology_registry_20260911_2.json"
    )
    rule_set = load_rule_pack(RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(registry_path)
    )
    registry = RegistryStore(connect=lambda: None)
    registry._cache["registry-20260911.2"] = rule_set
    legacy_results, common_results = FakeResults(), FakeResults()
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=80))

    outcome = build(
        tmp_path,
        cloner=cloner,
        registry=registry,
        results=legacy_results.publisher(schema_version=SCHEMA_VERSION),
        results_v2=common_results.publisher(
            "gitjob.repository-analysis.results.v2",
            schema_version=SCHEMA_VERSION_V2,
        ),
    ).handle(message(event(registry_version="registry-20260911.2")))

    assert outcome.action == "parsed"
    assert legacy_results.published == []
    body = json.loads(common_results.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION_V2
    assert {item["tech_id"]: item["level"] for item in body["payload"]["technologies"]}[
        "react"
    ] == "L2"
    assert len(body["payload"]["technology_support"]) == 44
    assert body["payload"]["stats"]["source_file_count"] == 1


def test_common44_without_v2_destination_finishes_as_explicit_capability_failure(
    tmp_path,
):
    checkout = tmp_path / "common-repository"
    checkout.mkdir()
    (checkout / "main.py").write_text("print('ok')\n", encoding="utf-8")
    registry_path = (
        RULE_PACK_PATH.parents[2]
        / "registry"
        / "data"
        / "technology_registry_20260911_2.json"
    )
    registry = RegistryStore(connect=lambda: None)
    registry._cache["registry-20260911.2"] = load_rule_pack(RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(registry_path)
    )
    claims, results = FakeClaims(), FakeResults()

    outcome = build(
        tmp_path,
        claims=claims,
        cloner=FakeCloner(
            tmp_path, result=CloneResult(path=checkout, bytes_on_disk=20)
        ),
        registry=registry,
        results=results.publisher(schema_version=SCHEMA_VERSION),
    ).handle(message(event(registry_version="registry-20260911.2")))

    assert outcome.error_code == "UNSUPPORTED_RESULT_SCHEMA"
    assert claims.finished == [("ev_1", 1, "FAILED", "UNSUPPORTED_RESULT_SCHEMA")]
    body = json.loads(results.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["payload"]["error_code"] == "UNSUPPORTED_RESULT_SCHEMA"


def test_schema_capability_failure_is_published_before_terminal_claim(tmp_path):
    registry_path = (
        RULE_PACK_PATH.parents[2]
        / "registry"
        / "data"
        / "technology_registry_20260911_2.json"
    )
    registry = RegistryStore(connect=lambda: None)
    registry._cache["registry-20260911.2"] = load_rule_pack(RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(registry_path)
    )
    claims = FakeClaims()
    failing_results = FakeResults(fail=True)
    request_message = message(event(registry_version="registry-20260911.2"))

    with pytest.raises(RuntimeError, match="results broker is down"):
        build(
            tmp_path,
            claims=claims,
            registry=registry,
            results=failing_results.publisher(schema_version=SCHEMA_VERSION),
        ).handle(request_message)
    assert claims.finished == []

    recovered_results = FakeResults()
    outcome = build(
        tmp_path,
        claims=claims,
        registry=registry,
        results=recovered_results.publisher(schema_version=SCHEMA_VERSION),
    ).handle(request_message)

    assert outcome.error_code == "UNSUPPORTED_RESULT_SCHEMA"
    assert claims.finished == [("ev_1", 1, "FAILED", "UNSUPPORTED_RESULT_SCHEMA")]
    assert len(recovered_results.published) == 1
    assert json.loads(recovered_results.published[0][2])["event_id"] == "res_ev_1"


def test_permanent_failure_is_recorded_and_committed(tmp_path):
    # The opposite rule: leaving this uncommitted stops the partition forever.
    claims, dlq = FakeClaims(), FakeDlq()
    cloner = FakeCloner(
        tmp_path, error=PermanentCloneError("REPOSITORY_NOT_FOUND", "gone")
    )

    outcome = build(tmp_path, claims=claims, cloner=cloner, dlq=dlq).handle(
        message(event())
    )

    assert outcome.action == "failed"
    assert outcome.error_code == "REPOSITORY_NOT_FOUND"
    assert claims.finished == [("ev_1", 1, "FAILED", "REPOSITORY_NOT_FOUND")]
    assert claims.released == []
    assert len(dlq.sent) == 1


def test_a_dead_dlq_does_not_mask_the_original_failure(tmp_path):
    cloner = FakeCloner(tmp_path, error=PermanentCloneError("CLONE_FAILED", "boom"))
    outcome = build(tmp_path, cloner=cloner, dlq=FakeDlq(fail=True)).handle(
        message(event())
    )

    assert outcome.action == "failed"


def test_the_working_directory_is_removed_even_when_the_clone_fails(tmp_path):
    leftover = tmp_path / work_target()
    leftover.mkdir()
    (leftover / "big.bin").write_bytes(b"x" * 16)
    cloner = FakeCloner(tmp_path, error=PermanentCloneError("CLONE_FAILED", "boom"))

    build(tmp_path, cloner=cloner).handle(message(event()))

    assert not leftover.exists()


def test_success_records_a_terminal_state_so_redelivery_is_skipped(tmp_path):
    claims = FakeClaims()
    build(tmp_path, claims=claims).handle(message(event()))

    assert claims.finished == [("ev_1", 1, "CLONED", None)]


@pytest.mark.parametrize(
    "analysis_id",
    ["../outside", "/outside", "C:/outside", ".", "nested/child"],
)
def test_unsafe_analysis_id_is_rejected_before_claim_or_cleanup(tmp_path, analysis_id):
    claims = FakeClaims()
    cloner = FakeCloner(tmp_path)

    outcome = build(tmp_path, claims=claims, cloner=cloner).handle(
        message(event(analysis_id=analysis_id))
    )

    assert outcome.action == "rejected"
    assert claims.claimed == []
    assert cloner.calls == []
    assert cloner.cleaned == []


# -- line authorship --------------------------------------------------------


def _git(repository, *args, **env):
    import subprocess

    subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_AUTHOR_NAME": "A",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_COMMITTER_NAME": "A",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            **env,
        },
    )


def _repository_with_history(root, *, shallow: bool):
    """근거가 가리키는 파일이 실제로 blame 되는 체크아웃."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    origin = root / "origin"
    (origin / "src/main/java").mkdir(parents=True)
    _git(origin.parent, "init", "--quiet", "--initial-branch", "main", str(origin))
    (origin / "src/main/java/App.java").write_text(
        "package a;\nimport b.C;\nimport org.springframework.boot.SpringApplication;\n",
        encoding="utf-8",
    )
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "first")

    if not shallow:
        return origin

    checkout = root / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", f"file://{origin}", str(checkout)],
        check=True,
        capture_output=True,
    )
    return checkout


class MatchingRegistry:
    """App.java 의 import 를 실제로 맞춰 근거를 만드는 레지스트리."""

    def load(self, registry_version):
        from analysis.rules import Clause, Mapping, Predicate, Rule, RuleSet

        return RuleSet(
            registry_version=registry_version,
            mappings=(
                Mapping(
                    "spring-boot", "IMPORT_PATH", "JAVA",
                    "org.springframework.boot", "PREFIX",
                ),
            ),
            rules=(
                Rule(
                    rule_id="spring-boot.l1.import",
                    tech_id="spring-boot",
                    rule_type="L1",
                    language=None,
                    evaluation_scope="REPOSITORY",
                    priority=50,
                    clauses=(
                        Clause(
                            clause_id=1, group_no=1, clause_key="resolved-tech",
                            role="REQUIRED", fact_type="IMPORT", min_match_count=1,
                            predicates=(
                                Predicate("TECH_ID", "EXACT", None, ("spring-boot",)),
                            ),
                        ),
                    ),
                ),
            ),
        )


def _evidence_of(results) -> list[dict]:
    assert results.published, "발행된 결과가 없으면 이 테스트는 아무것도 지키지 않는다"
    return json.loads(results.published[0][2])["payload"]["evidence"]


def test_authorship_is_attached_when_the_checkout_has_history(tmp_path):
    checkout = _repository_with_history(tmp_path, shallow=False)
    results = FakeResults()
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=10))

    build(
        tmp_path, cloner=cloner, registry=MatchingRegistry(),
        results=results.publisher(), attribute_authors=True,
    ).handle(message(event()))

    evidence = _evidence_of(results)
    assert evidence, "근거가 없으면 기여 판정을 확인할 수 없다"
    assert any(item["commit_sha"] is not None for item in evidence)


def test_a_shallow_checkout_publishes_no_authorship_instead_of_a_wrong_one(tmp_path):
    """이 기능에서 가장 중요한 테스트다.

    얕은 클론에서 blame 은 실패하지 않고 모든 줄을 tip 커밋에 돌린다. 그것을
    그대로 실으면 팀원의 코드가 전부 마지막에 푸시한 사람의 기여가 된다.
    분석 자체는 계속돼야 하므로 실패가 아니라 "없음"으로 나가야 한다.
    """
    checkout = _repository_with_history(tmp_path, shallow=True)
    results = FakeResults()
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=10))

    outcome = build(
        tmp_path, cloner=cloner, registry=MatchingRegistry(),
        results=results.publisher(), attribute_authors=True,
    ).handle(message(event()))

    assert outcome.action == "parsed", "기여 판정 실패가 분석을 깨뜨리면 안 된다"
    evidence = _evidence_of(results)
    assert evidence
    assert all(item["commit_sha"] is None for item in evidence)


def test_authorship_is_off_by_default(tmp_path):
    # 히스토리 클론을 쓰지 않는 배포가 blame 비용을 내면 안 된다.
    checkout = _repository_with_history(tmp_path, shallow=False)
    results = FakeResults()
    cloner = FakeCloner(tmp_path, result=CloneResult(path=checkout, bytes_on_disk=10))

    build(
        tmp_path, cloner=cloner, registry=MatchingRegistry(),
        results=results.publisher(),
    ).handle(message(event()))

    assert all(item["commit_sha"] is None for item in _evidence_of(results))
