"""Content checks that decide whether a generated summary may be shown.

A 4B model returns well-formed JSON and still writes the wrong thing in it.
``format`` guarantees the shape; these checks guarantee the content. Any single
failure discards the response -- there is no partial acceptance, because a
summary is one paragraph and half of it cannot be shown.
"""

import re
from dataclasses import dataclass

from llm.contracts import (
    MAX_HEADLINE_LENGTH,
    MAX_SUMMARY_LENGTH,
    Authorship,
    Confidence,
    FactPack,
    FactType,
    TechnologySummary,
)

#: Every proper noun a summary may contain came from the Fact Pack, so pulling
#: the identifiers out of the text and checking them against the input is what
#: actually catches hallucination. The other checks catch style.
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.@]{2,}")
_TOKEN_SPLIT_PATTERN = re.compile(r"[^A-Za-z0-9]+")
_LEVEL_PATTERN = re.compile(r"\bL[0-3]\b")
_RATIO_PATTERN = re.compile(r"\d\s*%|퍼센트|비율")
_GRADE_PATTERN = re.compile(r"초급|중급|고급|전문가|숙련")
#: Phrases that assert the person wrote the code. Forbidden when contribution
#: was never judged -- NOT_VERIFIED means "we could not tell", not "they did
#: not".
_CLAIMS_AUTHORSHIP_PATTERN = re.compile(r"직접 작성|본인이")


#: The fact types the shipped rule pack uses in L2 and L3 rules. The contract
#: writes the HIGH band as "an API_CALL the person wrote", from a three-type
#: world; these are the types that carry the same weight in the seven-type one.
IMPLEMENTATION_FACT_TYPES = frozenset(
    {
        FactType.API_CALL,
        FactType.ANNOTATION,
        FactType.SYNTAX_NODE,
        FactType.CONFIG_KEY,
    }
)


@dataclass(frozen=True)
class ValidationFailure:
    """One reason a response cannot be shown."""

    code: str
    detail: str


def _allowed_tokens(fact_pack: FactPack) -> frozenset[str]:
    """Collect every name the summary is allowed to use.

    File paths are in here alongside ``highlights.value``: they are part of the
    Fact Pack the model was given, and the contract's own worked example names
    ``SecurityConfig`` and ``build.gradle``, which exist only as file paths.
    """

    sources = [fact_pack.technology.display_name, fact_pack.technology.tech_id]
    for highlight in fact_pack.highlights:
        sources.append(highlight.value)
        sources.append(highlight.file)
    for level in fact_pack.levels:
        sources.extend(level.rules)
    if fact_pack.next_level is not None:
        sources.append(fact_pack.next_level.rule)
        sources.extend(fact_pack.next_level.missing)
    for repository in fact_pack.repositories:
        sources.append(repository.full_name)

    tokens: set[str] = set()
    for source in sources:
        tokens.add(source.casefold())
        tokens.update(
            part.casefold().rstrip(".@") for part in re.split(r"[\\/]", source) if part
        )
        tokens.update(
            part.casefold() for part in _TOKEN_SPLIT_PATTERN.split(source) if part
        )
    return frozenset(tokens)


def _body_text(summary: TechnologySummary) -> str:
    """Join the fields that reach the screen as prose."""

    return " ".join(
        part for part in (summary.headline, summary.summary, summary.gap) if part
    )


def validate_summary(
    summary: TechnologySummary,
    fact_pack: FactPack,
) -> tuple[ValidationFailure, ...]:
    """Return every reason this response must be discarded, empty when it passes."""

    failures: list[ValidationFailure] = []
    body = _body_text(summary)

    if summary.tech_id != fact_pack.technology.tech_id:
        failures.append(
            ValidationFailure(
                "TECH_ID_MISMATCH",
                f"expected {fact_pack.technology.tech_id!r}, got {summary.tech_id!r}",
            )
        )

    highlight_count = len(fact_pack.highlights)
    out_of_range = [
        index for index in summary.used_highlights if index >= highlight_count
    ]
    if out_of_range:
        failures.append(
            ValidationFailure(
                "HIGHLIGHT_INDEX_OUT_OF_RANGE",
                f"{out_of_range} not in 0..{highlight_count - 1}",
            )
        )

    if len(summary.headline) > MAX_HEADLINE_LENGTH:
        failures.append(
            ValidationFailure(
                "HEADLINE_TOO_LONG",
                f"{len(summary.headline)} > {MAX_HEADLINE_LENGTH}",
            )
        )
    if len(summary.summary) > MAX_SUMMARY_LENGTH:
        failures.append(
            ValidationFailure(
                "SUMMARY_TOO_LONG",
                f"{len(summary.summary)} > {MAX_SUMMARY_LENGTH}",
            )
        )

    ratio = _RATIO_PATTERN.search(body)
    if ratio is not None:
        failures.append(ValidationFailure("RATIO_MENTIONED", ratio.group()))

    grade = _GRADE_PATTERN.search(body)
    if grade is not None:
        failures.append(ValidationFailure("GRADE_WORD", grade.group()))

    if fact_pack.authorship is Authorship.NOT_VERIFIED:
        claim = _CLAIMS_AUTHORSHIP_PATTERN.search(body)
        if claim is not None:
            failures.append(
                ValidationFailure("UNVERIFIED_AUTHORSHIP_CLAIM", claim.group())
            )

    # The contract ties gap to next_level exactly: a sentence about the level
    # above when there is one, null when the technology is already at its
    # highest rule. Observed on qwen3.5:4b: it returns null anyway, dropping the
    # one field that makes the card actionable.
    if fact_pack.next_level is None and summary.gap is not None:
        failures.append(
            ValidationFailure("GAP_WITHOUT_NEXT_LEVEL", "next_level is null")
        )
    if fact_pack.next_level is not None and (
        summary.gap is None or not summary.gap.strip()
    ):
        failures.append(
            ValidationFailure(
                "GAP_MISSING",
                f"next_level {fact_pack.next_level.level.value} has no gap sentence",
            )
        )

    level = _LEVEL_PATTERN.search(body)
    if level is not None:
        failures.append(ValidationFailure("LEVEL_STRING_IN_BODY", level.group()))

    allowed = _allowed_tokens(fact_pack)
    invented = sorted(
        {
            identifier.rstrip(".@")
            for identifier in _IDENTIFIER_PATTERN.findall(body)
            if identifier.rstrip(".@").casefold() not in allowed
        }
    )
    if invented:
        failures.append(ValidationFailure("UNGROUNDED_IDENTIFIER", ", ".join(invented)))

    return tuple(failures)


def derive_confidence(fact_pack: FactPack) -> Confidence:
    """Grade how specific the input was, by the rule in the system prompt."""

    if fact_pack.authorship is Authorship.NOT_VERIFIED or not fact_pack.highlights:
        return Confidence.LOW
    mine = [highlight for highlight in fact_pack.highlights if highlight.mine]
    if not mine:
        return Confidence.LOW
    if any(highlight.fact_type in IMPLEMENTATION_FACT_TYPES for highlight in mine):
        return Confidence.HIGH
    return Confidence.MEDIUM


def _truncate(text: str, limit: int) -> str:
    """Cut to the contract's length, marking that something was dropped."""

    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def fallback_summary(fact_pack: FactPack) -> TechnologySummary:
    """Build a summary from the data alone, with no model involved.

    A failed generation must not empty the card. The level, the evidence and
    the permalinks exist without the model; the summary is a layer on top, and
    when the layer fails the sentence is assembled mechanically instead.

    The template names the levels, as chapter 5 of the contract writes it. That
    is the one place a level string is allowed in the prose: ``validate_summary``
    forbids it in generated text because the model has no reason to repeat what
    the card already renders, while this text exists precisely because there is
    nothing else to say.
    """

    technology = fact_pack.technology
    gap: str | None = None
    if fact_pack.next_level is not None:
        missing = ", ".join(fact_pack.next_level.missing)
        gap = _truncate(
            f"다음 수준 규칙 '{fact_pack.next_level.rule}' 중 {missing} 이(가) "
            "확인되지 않았다.",
            MAX_SUMMARY_LENGTH,
        )

    if fact_pack.authorship is Authorship.NOT_VERIFIED:
        # NOT_VERIFIED is not "they did not write it" -- the commit could not be
        # tied to the account. The template may not assert authorship either.
        body = (
            f"{technology.display_name} 를 저장소에서 "
            f"{technology.repository_level.value} 수준으로 사용했다. "
            "이 사람이 작성했는지는 확인되지 않았다."
        )
    else:
        body = (
            f"{technology.display_name} 를 저장소에서 "
            f"{technology.repository_level.value} 수준으로 사용했고, 그중 본인이 "
            f"작성한 근거로는 {technology.personal_level.value} 가 확인됐다."
        )

    return TechnologySummary(
        tech_id=technology.tech_id,
        headline=_truncate(
            f"{technology.display_name} 사용 근거가 확인됐다",
            MAX_HEADLINE_LENGTH,
        ),
        summary=_truncate(body, MAX_SUMMARY_LENGTH),
        gap=gap,
        used_highlights=tuple(highlight.index for highlight in fact_pack.highlights),
        confidence=derive_confidence(fact_pack),
    )
