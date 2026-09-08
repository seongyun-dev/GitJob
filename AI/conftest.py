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

Both directories are added here so the suite runs with no environment setup:

    python -m pytest AI/tests -q
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
