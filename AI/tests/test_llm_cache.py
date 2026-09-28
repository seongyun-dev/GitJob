import json
from pathlib import Path

from llm.cache import summary_cache_key
from llm.contracts import FactPack

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm"
    / "fixtures"
    / "technology_summary_request_v1.json"
)


def fact_pack(**overrides: object) -> FactPack:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    return FactPack.model_validate(payload)


def key(pack: FactPack | None = None, **overrides: object) -> str:
    arguments: dict[str, object] = {
        "user_id": "user-1",
        "prompt_version": "tech-summary/2026-09-14.2",
        "model": "qwen3.5:4b",
    }
    arguments.update(overrides)
    return summary_cache_key(
        arguments.pop("user_id"),
        pack if pack is not None else fact_pack(),
        **arguments,
    )


def test_key_is_a_sha256_hex_digest() -> None:
    digest = key()

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_same_input_gives_the_same_key() -> None:
    assert key() == key()


def test_key_separates_users() -> None:
    assert key() != key(user_id="user-2")


def test_key_changes_when_the_prompt_is_edited() -> None:
    assert key() != key(prompt_version="tech-summary/2026-10-01.1")


def test_key_changes_when_the_model_changes() -> None:
    assert key() != key(model="qwen3.5:8b")


def test_key_changes_with_the_registry_version() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["technology"]["registry_version"] = "registry-20260911.1"

    assert key() != key(FactPack.model_validate(payload))


def test_key_changes_with_the_authorship_band() -> None:
    assert key() != key(fact_pack(authorship="MIXED"))


def test_key_changes_when_a_highlight_changes() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["highlights"][0]["value"] = "SecurityWebFilterChain"

    assert key() != key(FactPack.model_validate(payload))


def test_key_survives_equivalent_input_written_differently() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["highlights"][0]["file"] = (
        "src/main/java/com/example/config/SecurityConfig.java"
    )

    assert key() == key(FactPack.model_validate(payload))
