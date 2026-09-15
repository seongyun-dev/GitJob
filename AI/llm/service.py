"""Generate one technology summary: ask, check, retry once, else fall back."""

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import ValidationError

from llm.cache import summary_cache_key
from llm.client import ChatClient, OllamaError
from llm.contracts import Confidence, FactPack, TechnologySummary
from llm.prompt import PROMPT_VERSION, build_messages
from llm.validation import (
    ValidationFailure,
    derive_confidence,
    fallback_summary,
    validate_summary,
)

#: Restatement is not creation, so the first pass runs cool. The retry runs at
#: zero: if 0.2 produced something ungrounded, sampling again at 0.2 mostly
#: produces a different ungrounded sentence.
FIRST_TEMPERATURE = 0.2
RETRY_TEMPERATURE = 0.0

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


class SummaryStatus(StrEnum):
    """Where the stored sentence came from."""

    OK = "OK"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True)
class SummaryAttempt:
    """One generation try and why it was not accepted."""

    temperature: float
    failures: tuple[ValidationFailure, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class GeneratedSummary:
    """The summary to store, plus what it took to get there."""

    summary: TechnologySummary
    status: SummaryStatus
    cache_key: str
    model: str
    prompt_version: str = PROMPT_VERSION
    attempts: tuple[SummaryAttempt, ...] = field(default=())
    #: What the model put in `confidence` before it was replaced by the derived
    #: value, when the two disagreed. Kept for the backend's logs: a band that
    #: drifts often is a prompt problem, and the drift is invisible otherwise.
    model_confidence: Confidence | None = None


def _with_derived_confidence(
    summary: TechnologySummary,
    fact_pack: FactPack,
) -> tuple[TechnologySummary, Confidence | None]:
    """Replace the model's confidence band with the one the input implies.

    `confidence` is a function of the Fact Pack -- whether the person's own
    evidence held an implementation fact -- so this AI service computes it
    exactly instead of trusting the model. Observed on qwen3.5:4b: a
    dependency-only input comes back HIGH. Letting that stand would put a band
    on the card that the evidence below it contradicts.
    """

    derived = derive_confidence(fact_pack)
    if summary.confidence is derived:
        return summary, None
    return summary.model_copy(update={"confidence": derived}), summary.confidence


def parse_summary(content: str) -> TechnologySummary:
    """Read the model's message content as a summary object.

    ``format`` should make the fences and prose impossible, but a model that
    emits them anyway is a formatting slip, not a wrong summary -- salvaging
    the object costs one regex and saves a GPU round trip.
    """

    try:
        return TechnologySummary.model_validate_json(content)
    except ValidationError:
        pass

    match = _JSON_OBJECT_PATTERN.search(content)
    if match is None:
        raise ValueError("model output contained no JSON object")
    return TechnologySummary.model_validate(json.loads(match.group()))


def _try_once(
    client: ChatClient,
    messages: list[dict[str, str]],
    fact_pack: FactPack,
    temperature: float,
) -> tuple[TechnologySummary | None, SummaryAttempt]:
    """Ask once and report either an accepted summary or why it was rejected."""

    try:
        content = client.chat(messages, temperature=temperature)
    except OllamaError as exc:
        return None, SummaryAttempt(temperature=temperature, error=str(exc))

    try:
        summary = parse_summary(content)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        return None, SummaryAttempt(temperature=temperature, error=str(exc)[:500])

    failures = validate_summary(summary, fact_pack)
    if failures:
        return None, SummaryAttempt(temperature=temperature, failures=failures)
    return summary, SummaryAttempt(temperature=temperature)


def generate_summary(
    fact_pack: FactPack,
    *,
    user_id: str,
    client: ChatClient,
) -> GeneratedSummary:
    """Produce the summary for one (user, technology) pair.

    A failure here never empties the card. The level, the evidence rows and the
    permalinks are already on screen without the model; a rejected generation
    only means the sentence above them is assembled from the data instead.
    """

    messages = build_messages(fact_pack)
    cache_key = summary_cache_key(
        user_id,
        fact_pack,
        prompt_version=PROMPT_VERSION,
        model=client.model,
    )

    attempts: list[SummaryAttempt] = []
    for temperature in (FIRST_TEMPERATURE, RETRY_TEMPERATURE):
        summary, attempt = _try_once(client, messages, fact_pack, temperature)
        attempts.append(attempt)
        if summary is not None:
            corrected, model_confidence = _with_derived_confidence(summary, fact_pack)
            return GeneratedSummary(
                summary=corrected,
                status=SummaryStatus.OK,
                cache_key=cache_key,
                model=client.model,
                attempts=tuple(attempts),
                model_confidence=model_confidence,
            )

    return GeneratedSummary(
        summary=fallback_summary(fact_pack),
        status=SummaryStatus.FALLBACK,
        cache_key=cache_key,
        model=client.model,
        attempts=tuple(attempts),
    )
