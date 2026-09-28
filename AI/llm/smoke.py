"""Run the contract's hard cases against the real local model.

The unit tests use a fake client, so they prove the code is right and say
nothing about whether ``qwen3.5:4b`` can actually satisfy the contract. This
does the opposite: one request per case against a running Ollama, printing what
came back and which checks rejected it.

    python -m llm.smoke

Every case here exists because the model got it wrong at least once. Read the
``why`` line before changing one.
"""

import json
import sys
import time
from pathlib import Path

from llm.client import OllamaChatClient, OllamaSettings
from llm.contracts import FactPack
from llm.prompt import PROMPT_VERSION
from llm.service import SummaryStatus, generate_summary

CASES_PATH = Path(__file__).resolve().parent / "fixtures"
CASES_PATH = CASES_PATH / "technology_summary_smoke_cases.json"


def main() -> int:
    """Generate every smoke case and report the fallback count as the status."""

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    settings = OllamaSettings.from_env()
    client = OllamaChatClient(settings)

    print(f"model           {settings.model}")
    print(f"ollama          {settings.base_url}")
    print(f"prompt_version  {PROMPT_VERSION}")

    fallbacks = 0
    for case in cases:
        fact_pack = FactPack.model_validate(case["fact_pack"])
        started = time.monotonic()
        result = generate_summary(fact_pack, user_id="smoke-user", client=client)
        elapsed = time.monotonic() - started
        fallbacks += result.status is SummaryStatus.FALLBACK

        summary = result.summary
        print(f"\n### {case['name']}  [{elapsed:.1f}s]  {result.status.value}")
        print(f"    왜        {case['why']}")
        for attempt in result.attempts:
            reason = [failure.code for failure in attempt.failures] or attempt.error
            print(f"    시도 t={attempt.temperature}  {reason or 'accepted'}")
        if result.model_confidence is not None:
            print(
                f"    confidence 모델 {result.model_confidence.value} "
                f"-> 규칙 {summary.confidence.value}"
            )
        print(f"    headline  {summary.headline}  ({len(summary.headline)}자)")
        print(f"    summary   {summary.summary}  ({len(summary.summary)}자)")
        print(f"    gap       {summary.gap}")
        print(
            f"    used      {list(summary.used_highlights)}  {summary.confidence.value}"
        )

    print(f"\n== {len(cases) - fallbacks} OK / {fallbacks} FALLBACK")
    # A fallback is a working outcome, not a crash, so this never fails the run.
    # The number is the signal: a prompt edit that raises it made things worse.
    return 0


if __name__ == "__main__":
    sys.exit(main())
