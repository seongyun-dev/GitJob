"""Turn raw evidence rows into the bounded ``highlights`` array.

One technology can carry dozens of evidence rows -- ``spring-security`` reaches
82 in the sample repository. Sending them verbatim overruns the 8K context, so
the rows collapse to at most eight distinct facts here, deterministically: the
cache key is computed over the normalized Fact Pack, and a selection that
reordered between runs would miss the cache every time.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from llm.contracts import MAX_HIGHLIGHTS, FactType, Highlight, shorten_file_path

#: ``fact_payload`` has no ``value`` key. The worker stores a different key per
#: fact type (``judge.py``), and the backend flattens all of them to ``value``
#: rather than teaching the model three key names.
#:
#: ``API_CALL`` reads ``CALL`` before ``METHOD``: ``METHOD`` holds only the last
#: segment, so ``run``, ``get`` and ``build`` come out alone and a summary built
#: on them says "run 을 호출했다". ``CALL`` keeps the receiver --
#: ``SpringApplication.run``.
#: ``CONFIG_KEY`` reads ``KEY`` and never ``VALUE``. The value half of a config
#: row is whatever was written in the file -- a connection string, a secret --
#: and none of it belongs in a prompt or in a sentence on a card.
FACT_VALUE_KEYS: dict[FactType, tuple[str, ...]] = {
    FactType.IMPORT: ("MODULE",),
    FactType.DEPENDENCY: ("COORDINATE",),
    FactType.API_CALL: ("CALL", "METHOD"),
    FactType.ANNOTATION: ("NAME",),
    FactType.SYNTAX_NODE: ("NAME",),
    FactType.CONFIG_KEY: ("KEY",),
    FactType.SOURCE_FILE: ("FILE_PATH",),
}

#: Higher-level evidence is more worth the context budget than a dependency
#: line, so it is selected first. The order follows the highest rule level each
#: type reaches in the shipped rule pack: API_CALL, ANNOTATION, SYNTAX_NODE and
#: CONFIG_KEY carry L3 rules, IMPORT and SOURCE_FILE stop at L2, DEPENDENCY at
#: L0. SOURCE_FILE sits near the bottom for a second reason -- its value is a
#: path the highlight already carries in ``file``.
_FACT_TYPE_RANK: dict[FactType, int] = {
    FactType.API_CALL: 0,
    FactType.ANNOTATION: 1,
    FactType.SYNTAX_NODE: 2,
    FactType.CONFIG_KEY: 3,
    FactType.IMPORT: 4,
    FactType.SOURCE_FILE: 5,
    FactType.DEPENDENCY: 6,
}


@dataclass(frozen=True)
class EvidenceFact:
    """One evidence row as the backend reads it out of the database.

    ``mine`` is ``None`` when no contribution row exists for the user -- the
    join that produces it must stay a ``LEFT JOIN``, or every piece of evidence
    from an analysis without contribution judgment disappears and
    ``highlights`` ships empty.
    """

    fact_type: FactType
    value: str
    file_path: str
    start_line: int = 0
    mine: bool | None = None


def fact_value(fact_type: FactType, fact_payload: dict[str, object]) -> str | None:
    """Read the one payload key that carries a usable name for this fact type.

    Returns ``None`` when the payload holds nothing under that type's keys; such
    a row cannot be described and is dropped rather than sent as an empty name.
    """

    for key in FACT_VALUE_KEYS[fact_type]:
        value = fact_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _selection_key(fact: EvidenceFact) -> tuple[int, int, str, int]:
    """Order facts the way chapter 2 of the contract specifies.

    ``mine`` unknown sorts after ``mine`` false, matching the SQL's
    ``DESC NULLS LAST``. Without it PostgreSQL puts unattributed evidence ahead
    of the user's own, because ``DESC`` defaults to ``NULLS FIRST``.
    """

    mine_rank = 0 if fact.mine is True else (1 if fact.mine is False else 2)
    return (
        mine_rank,
        _FACT_TYPE_RANK[fact.fact_type],
        fact.file_path,
        fact.start_line,
    )


def select_highlights(
    facts: Iterable[EvidenceFact],
    *,
    limit: int = MAX_HIGHLIGHTS,
) -> tuple[Highlight, ...]:
    """Deduplicate by value, rank, cut to ``limit``, and number the survivors.

    ``SecurityFilterChain`` appearing twelve times is one highlight. The index
    is assigned here rather than left for the model to count, which is what
    makes ``used_highlights`` checkable.
    """

    best_by_value: dict[str, EvidenceFact] = {}
    for fact in facts:
        value = fact.value.strip()
        if not value:
            continue
        normalized = EvidenceFact(
            fact_type=fact.fact_type,
            value=value,
            file_path=fact.file_path,
            start_line=fact.start_line,
            mine=fact.mine,
        )
        current = best_by_value.get(value)
        if current is None or _selection_key(normalized) < _selection_key(current):
            best_by_value[value] = normalized

    ranked = sorted(
        best_by_value.values(),
        key=lambda fact: (*_selection_key(fact), fact.value),
    )
    return tuple(
        Highlight(
            index=index,
            fact_type=fact.fact_type,
            value=fact.value,
            file=shorten_file_path(fact.file_path),
            mine=fact.mine is True,
        )
        for index, fact in enumerate(ranked[:limit])
    )
