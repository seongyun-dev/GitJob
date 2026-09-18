"""Stage transitions: the shape on the wire, and when they are sent.

The screen is the only consumer of these messages, so a bug here is invisible
in every other test -- the analysis still produces the same evidence and the
same result event. What it looks like in production is "the progress feature
was never deployed", which is why the cases below are mostly about *not*
sending and about surviving a broken broker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.consumer import AnalysisConsumer
from analysis.progress import (
    EVENT_TYPE,
    SCHEMA_VERSION,
    STAGE_ANALYZING_REPOSITORY,
    STAGE_ATTRIBUTING_CONTRIBUTION,
    ProgressPublisher,
    RepositoryAnalysisProgress,
    progress_event,
    progress_event_id,
)
from tests.test_analysis_consumer import (
    EmptyRegistry,
    FakeCloner,
    FakeResults,
    build,
    event,
    message,
)

FIXTURES = Path(__file__).parent / "fixtures"

TOPIC = "gitjob.repository-analysis.progress.v1"


class FakeProgressTransport:
    """Records what went out, or refuses to send at all."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail = fail

    def send(self, topic: str, *, key: bytes, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("progress broker is down")
        self.sent.append((topic, key, value))

    def stages(self) -> list[str]:
        return [json.loads(value)["payload"]["stage"] for _, _, value in self.sent]


def publisher(fail: bool = False) -> tuple[ProgressPublisher, FakeProgressTransport]:
    transport = FakeProgressTransport(fail=fail)
    return ProgressPublisher(transport, TOPIC), transport


# --- the contract both sides read -------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    [
        "repository-analysis-progress-v1-analyzing.json",
        "repository-analysis-progress-v1-attributing.json",
    ],
)
def test_the_shared_fixture_is_what_this_module_produces(fixture):
    # B's RepositoryAnalysisProgressContractTest reads these same files. If this
    # assertion and that one both pass, the two sides agree without either
    # keeping a copy of the other's shape.
    parsed = RepositoryAnalysisProgress.model_validate_json(
        (FIXTURES / fixture).read_text(encoding="utf-8")
    )

    assert parsed.schema_version == SCHEMA_VERSION
    assert parsed.event_type == EVENT_TYPE


def test_a_takeover_repeats_an_event_id_instead_of_inventing_one():
    # The same request runs again after a lease expires. Two ids for one
    # transition would look like the analysis passed that stage twice.
    first = progress_event_id("ev_1", STAGE_ANALYZING_REPOSITORY)

    assert first == progress_event_id("ev_1", STAGE_ANALYZING_REPOSITORY)
    assert first != progress_event_id("ev_1", STAGE_ATTRIBUTING_CONTRIBUTION)
    assert first != progress_event_id("ev_2", STAGE_ANALYZING_REPOSITORY)


def test_an_event_id_stays_inside_the_identifier_contract():
    # Identifier is max 80 characters on both sides. A long request id used to
    # be fine here and would start failing validation only in production.
    long_request = "ev_" + "a" * 70

    assert len(progress_event_id(long_request, STAGE_ATTRIBUTING_CONTRIBUTION)) <= 80


def test_a_stage_name_that_would_not_fit_the_column_is_refused():
    # current_stage is VARCHAR(40). Postgres would truncate silently and the
    # screen would then look for a stage name that never arrives.
    with pytest.raises(ValueError, match="current_stage"):
        progress_event(
            analysis_id="an_1",
            request_event_id="ev_1",
            trace_id="tr_1",
            stage="S" * 41,
        )


# --- publishing --------------------------------------------------------------


def test_progress_is_keyed_by_analysis_so_stages_keep_their_order():
    sender, transport = publisher()

    sender.report(
        analysis_id="an_1",
        request_event_id="ev_1",
        trace_id="tr_1",
        stage=STAGE_ANALYZING_REPOSITORY,
    )

    topic, key, value = transport.sent[0]
    assert topic == TOPIC
    assert key == b"an_1"
    assert json.loads(value)["payload"] == {
        "analysis_id": "an_1",
        "stage": STAGE_ANALYZING_REPOSITORY,
    }


def test_a_broken_progress_broker_is_swallowed():
    # ResultPublisher raises here on purpose. This one must not: the caller is
    # holding a claim on a checkout it would have to clone all over again.
    sender, _ = publisher(fail=True)

    assert (
        sender.report(
            analysis_id="an_1",
            request_event_id="ev_1",
            trace_id="tr_1",
            stage=STAGE_ANALYZING_REPOSITORY,
        )
        is False
    )


# --- when the worker reports -------------------------------------------------


def test_the_first_stage_is_reported_once_the_checkout_exists(tmp_path):
    sender, transport = publisher()

    outcome = build(tmp_path, cloner=FakeCloner(tmp_path), progress=sender).handle(
        message(event())
    )

    assert outcome.action == "parsed"
    assert transport.stages() == [STAGE_ANALYZING_REPOSITORY]


def test_attribution_is_not_announced_when_it_does_not_run(tmp_path):
    # attribute_authors is off by default, and then _authorship returns {}
    # without touching git. Announcing it would leave the screen waiting on a
    # step that nobody is performing.
    sender, transport = publisher()

    build(
        tmp_path,
        cloner=FakeCloner(tmp_path),
        progress=sender,
        registry=EmptyRegistry(),
        results=FakeResults().publisher(),
    ).handle(message(event()))

    assert STAGE_ATTRIBUTING_CONTRIBUTION not in transport.stages()


def test_attribution_is_announced_when_it_does_run(tmp_path):
    sender, transport = publisher()

    build(
        tmp_path,
        cloner=FakeCloner(tmp_path),
        progress=sender,
        attribute_authors=True,
        registry=EmptyRegistry(),
        results=FakeResults().publisher(),
    ).handle(message(event()))

    assert transport.stages() == [
        STAGE_ANALYZING_REPOSITORY,
        STAGE_ATTRIBUTING_CONTRIBUTION,
    ]


def test_an_analysis_runs_to_completion_with_a_broken_progress_topic(tmp_path):
    sender, _ = publisher(fail=True)

    outcome = build(tmp_path, cloner=FakeCloner(tmp_path), progress=sender).handle(
        message(event())
    )

    assert outcome.action == "parsed"


def test_a_worker_without_a_progress_topic_behaves_exactly_as_before(tmp_path):
    # The default. This is what every deployment runs until Infra sets the
    # topic, so it has to be the boring path rather than a special case.
    consumer: AnalysisConsumer = build(tmp_path, cloner=FakeCloner(tmp_path))

    assert consumer.progress is None
    assert consumer.handle(message(event())).action == "parsed"
