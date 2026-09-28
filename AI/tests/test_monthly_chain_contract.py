"""The monthly chain's validator must accept exactly what the producer finishes.

`repo-snapshot-monthly-top10k-chain.sh` validates a finished month by reading
the bootstrap checkpoint and rejecting any repository that is not in a terminal
state. It cannot import `repo_fetch_orchestrator` to learn which statuses those
are — the chain runs `python3` on the deployment host, where the AI package and
its dependencies are not installed — so it restates the set inline.

Restating it is what broke the 2026-08 run. `HISTORICAL_HEAD_UNAVAILABLE`
arrived with `S15P21E102-198` and only appears when `REPO_REQUIRE_HISTORICAL_HEAD=1`,
which the chain began setting in `S15P21E102-194`. All 10,000 repositories had
reached a terminal state and the snapshot was published, and then the chain
rejected its own output and exited 1 — no pass-marker, no next month.

So the duplication stays, and this test is what keeps the copy honest. It reads
both files as text rather than importing either: the point is to compare what is
literally written in each place, which an import would paper over.

`RATE_LIMITED` is deliberately outside both sets. It is the one status that
means the repository is unfinished, and treating it as terminal would let a
month be sealed while repositories were still owed a retry.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHAIN_SCRIPT = REPOSITORY_ROOT / "Infra/scripts/repo-snapshot-monthly-top10k-chain.sh"
ORCHESTRATOR = REPOSITORY_ROOT / "AI/github/repo_fetch_orchestrator.py"


def _producer_terminal_statuses() -> set[str]:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    match = re.search(r"TERMINAL_STATUSES\s*=\s*\{(?P<body>[^}]*)\}", source, re.S)
    assert match is not None, "TERMINAL_STATUSES is no longer a set literal"
    return set(re.findall(r'"([A-Z_]+)"', match.group("body")))


def _producer_statuses() -> set[str]:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    match = re.search(
        r"class RepoExecutionStatus\(StrEnum\):\n(?P<body>(?:[ ]{4}.*\n)+)", source
    )
    assert match is not None, "RepoExecutionStatus is no longer a plain StrEnum"
    return set(re.findall(r'=\s*"([A-Z_]+)"', match.group("body")))


def _validator_terminal_statuses() -> set[str]:
    script = CHAIN_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"status\s*\n?\s*not in \{(?P<body>[^}]*)\}", script, re.S)
    assert match is not None, "the chain no longer rejects non-terminal statuses"
    return set(re.findall(r'"([A-Z_]+)"', match.group("body")))


def test_validator_accepts_exactly_the_producer_terminal_statuses() -> None:
    assert _validator_terminal_statuses() == _producer_terminal_statuses()


def test_historical_head_unavailable_is_terminal_on_both_sides() -> None:
    # The specific status that failed 2026-08. Named on its own so a regression
    # says which contract broke rather than only that two sets differ.
    assert "HISTORICAL_HEAD_UNAVAILABLE" in _producer_terminal_statuses()
    assert "HISTORICAL_HEAD_UNAVAILABLE" in _validator_terminal_statuses()


def test_rate_limited_is_the_only_non_terminal_status() -> None:
    # A repository the API deferred is owed another attempt; sealing a month
    # with one outstanding would publish an incomplete Top-N.
    assert _producer_statuses() - _producer_terminal_statuses() == {"RATE_LIMITED"}
    assert "RATE_LIMITED" not in _validator_terminal_statuses()


def test_chain_requires_historical_head_when_fetching_artifacts() -> None:
    # Without this the fetch falls back to the current default branch head and
    # HISTORICAL_HEAD_UNAVAILABLE never appears — which is how the missing
    # status stayed invisible until the flag was turned on.
    script = CHAIN_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"run_bootstrap\(\)\s*\{(?P<body>.*?)\n\}", script, re.S)
    assert match is not None, "run_bootstrap is no longer a shell function"
    assert "REPO_REQUIRE_HISTORICAL_HEAD=1" in match.group("body")
