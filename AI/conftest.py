"""Import paths for the test suite.

Two things were only working by accident before this file existed.

**The AI packages are imported as top level** — `job.contracts`,
`Worknet_Collector_V1`, `registry.mapper`. `python -m pytest` happens to put
the working directory on `sys.path`, so running it from `AI/` worked while a
bare `pytest tests/` did not.

**Two suites import Spark job modules that live outside `AI/`.**
`test_repo_activity_topn.py` and `test_repo_fetch_benchmark.py` import
`repo_activity_topn` and `repo_fetch_candidates` from `Infra/spark/`, which no
`PYTHONPATH=AI` covers. They failed at collection for anyone who did not know
to add that directory by hand, so `pytest tests/` reported two errors on a
clean checkout and the rest of the suite never ran.

Both directories are added here so imports resolve with no environment setup.

### What this file cannot fix is the working directory

Five suites read fixture files through a bare relative path — six sites across
`test_trend_job.py`, `test_trend_github.py`, `test_public_analysis.py`,
`test_public_pipeline.py` and `test_public_run.py`:

    Path("registry/data/technology_registry_v1.json").read_text(...)

That resolves against the process's current directory, not against the test
file, so no `sys.path` entry reaches it. Run the suite from `AI/`:

    cd AI && python -m pytest tests -q      # 1199 passed, 42 skipped

From the repository root the same 1241 tests collect without a single error and
then 161 of them fail at fixture setup with `FileNotFoundError`, plus one
outright failure. That reads like a broken checkout rather than a wrong
directory, which is why it is written down here. Measured 2026-09-09.
"""

import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parent
SPARK_ROOT = AI_ROOT.parent / "Infra" / "spark"

for candidate in (AI_ROOT, SPARK_ROOT):
    if not candidate.is_dir():
        continue
    entry = str(candidate)
    if entry not in sys.path:
        sys.path.insert(0, entry)
