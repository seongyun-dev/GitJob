import pytest

from llm.contracts import FactType
from llm.facts import EvidenceFact, fact_value, select_highlights


@pytest.mark.parametrize(
    ("fact_type", "payload", "expected"),
    [
        (
            FactType.IMPORT,
            {"MODULE": "org.springframework.security.web"},
            "org.springframework.security.web",
        ),
        (
            FactType.DEPENDENCY,
            {"COORDINATE": "org.projectlombok:lombok"},
            "org.projectlombok:lombok",
        ),
        (
            FactType.API_CALL,
            {"CALL": "SpringApplication.run", "METHOD": "run"},
            "SpringApplication.run",
        ),
        (FactType.API_CALL, {"METHOD": "run"}, "run"),
    ],
)
def test_fact_value_reads_the_key_for_its_fact_type(
    fact_type: FactType,
    payload: dict[str, object],
    expected: str,
) -> None:
    assert fact_value(fact_type, payload) == expected


def test_fact_value_ignores_keys_belonging_to_another_fact_type() -> None:
    assert (
        fact_value(FactType.IMPORT, {"COORDINATE": "org.projectlombok:lombok"}) is None
    )


def test_fact_value_returns_none_for_blank_or_missing_payload() -> None:
    assert fact_value(FactType.API_CALL, {"CALL": "   "}) is None
    assert fact_value(FactType.DEPENDENCY, {}) is None


def test_select_highlights_deduplicates_by_value() -> None:
    facts = [
        EvidenceFact(
            FactType.API_CALL, "SecurityFilterChain", "config/A.java", 10, True
        )
        for _ in range(12)
    ]

    highlights = select_highlights(facts)

    assert len(highlights) == 1
    assert highlights[0].index == 0


def test_select_highlights_prefers_mine_then_higher_fact_type() -> None:
    facts = [
        EvidenceFact(FactType.DEPENDENCY, "coord", "build.gradle", 1, True),
        EvidenceFact(FactType.API_CALL, "theirCall", "config/B.java", 1, False),
        EvidenceFact(FactType.API_CALL, "myCall", "config/A.java", 1, True),
        EvidenceFact(FactType.IMPORT, "myImport", "config/A.java", 2, True),
    ]

    values = [highlight.value for highlight in select_highlights(facts)]

    assert values == ["myCall", "myImport", "coord", "theirCall"]


def test_select_highlights_sorts_unattributed_evidence_last() -> None:
    facts = [
        EvidenceFact(FactType.API_CALL, "unknownCall", "config/A.java", 1, None),
        EvidenceFact(FactType.API_CALL, "theirCall", "config/A.java", 1, False),
        EvidenceFact(FactType.API_CALL, "myCall", "config/A.java", 1, True),
    ]

    values = [highlight.value for highlight in select_highlights(facts)]

    assert values == ["myCall", "theirCall", "unknownCall"]


def test_select_highlights_reports_unattributed_evidence_as_not_mine() -> None:
    facts = [EvidenceFact(FactType.API_CALL, "unknownCall", "config/A.java", 1, None)]

    assert select_highlights(facts)[0].mine is False


def test_select_highlights_breaks_ties_by_file_then_line() -> None:
    facts = [
        EvidenceFact(FactType.API_CALL, "second", "config/B.java", 1, True),
        EvidenceFact(FactType.API_CALL, "third", "config/B.java", 9, True),
        EvidenceFact(FactType.API_CALL, "first", "config/A.java", 5, True),
    ]

    values = [highlight.value for highlight in select_highlights(facts)]

    assert values == ["first", "second", "third"]


def test_select_highlights_caps_at_eight_and_numbers_them_densely() -> None:
    facts = [
        EvidenceFact(
            FactType.API_CALL, f"call{index:02d}", "config/A.java", index, True
        )
        for index in range(20)
    ]

    highlights = select_highlights(facts)

    assert len(highlights) == 8
    assert [highlight.index for highlight in highlights] == list(range(8))


def test_select_highlights_is_deterministic_regardless_of_input_order() -> None:
    facts = [
        EvidenceFact(FactType.IMPORT, "b", "config/A.java", 2, True),
        EvidenceFact(FactType.API_CALL, "a", "config/A.java", 1, True),
        EvidenceFact(FactType.DEPENDENCY, "c", "build.gradle", 3, False),
    ]

    assert select_highlights(facts) == select_highlights(reversed(facts))


def test_select_highlights_shortens_the_file_path() -> None:
    facts = [
        EvidenceFact(
            FactType.API_CALL,
            "SecurityFilterChain",
            "src/main/java/com/example/config/SecurityConfig.java",
            10,
            True,
        )
    ]

    assert select_highlights(facts)[0].file == "config/SecurityConfig.java"


def test_select_highlights_drops_rows_without_a_usable_value() -> None:
    facts = [
        EvidenceFact(FactType.API_CALL, "   ", "config/A.java", 1, True),
        EvidenceFact(FactType.API_CALL, "myCall", "config/A.java", 2, True),
    ]

    assert [highlight.value for highlight in select_highlights(facts)] == ["myCall"]


def test_fact_type_matches_what_the_rules_engine_emits() -> None:
    """The seven-type list in analysis/results.py is the authority.

    The contract document names three. Following it literally would silently
    drop the ANNOTATION, SYNTAX_NODE and CONFIG_KEY rows that carry most L3
    evidence in the shipped rule pack.
    """

    from typing import get_args

    from analysis.results import FactTypeV3

    assert {fact_type.value for fact_type in FactType} == set(get_args(FactTypeV3))


@pytest.mark.parametrize(
    ("fact_type", "payload", "expected"),
    [
        (
            FactType.ANNOTATION,
            {"NAME": "@EnableMethodSecurity"},
            "@EnableMethodSecurity",
        ),
        (FactType.SYNTAX_NODE, {"NAME": "SecurityConfig"}, "SecurityConfig"),
        (
            FactType.CONFIG_KEY,
            {"KEY": "spring.security.oauth2"},
            "spring.security.oauth2",
        ),
        (
            FactType.SOURCE_FILE,
            {"FILE_PATH": "config/SecurityConfig.java"},
            "config/SecurityConfig.java",
        ),
    ],
)
def test_fact_value_for_the_types_the_contract_left_out(
    fact_type: FactType,
    payload: dict[str, object],
    expected: str,
) -> None:
    assert fact_value(fact_type, payload) == expected


def test_config_key_never_reads_the_value_half() -> None:
    """A config value can be a connection string or a secret."""

    payload = {"KEY": "spring.datasource.password", "VALUE": "hunter2"}

    assert fact_value(FactType.CONFIG_KEY, payload) == "spring.datasource.password"


def test_annotation_evidence_outranks_an_import() -> None:
    facts = [
        EvidenceFact(
            FactType.IMPORT, "org.springframework.security", "a/A.java", 1, True
        ),
        EvidenceFact(FactType.ANNOTATION, "@EnableMethodSecurity", "a/A.java", 2, True),
    ]

    values = [highlight.value for highlight in select_highlights(facts)]

    assert values == ["@EnableMethodSecurity", "org.springframework.security"]


def test_source_file_evidence_is_selected_last_among_the_persons_own() -> None:
    facts = [
        EvidenceFact(FactType.SOURCE_FILE, "src/main.c", "src/main.c", 1, True),
        EvidenceFact(FactType.CONFIG_KEY, "server.port", "src/app.yml", 1, True),
    ]

    values = [highlight.value for highlight in select_highlights(facts)]

    assert values == ["server.port", "src/main.c"]
