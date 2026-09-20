#!/usr/bin/env bash

# Deliberately small, non-DB C regression gate for Jenkins. PostgreSQL-backed
# checks need an explicitly isolated database and stay a separate release
# evidence item; a skipped DB test must not make this gate look green.
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
ci_venv="$(mktemp -d "${TMPDIR:-/tmp}/gitjob-ai-ci.XXXXXX")"
results_xml="${ci_venv}/pytest-results.xml"

cleanup() {
  rm -rf "${ci_venv}"
}
trap cleanup EXIT

"${python_bin}" --version
command -v git >/dev/null
git --version
"${python_bin}" -m venv "${ci_venv}"
ci_python="${ci_venv}/bin/python"
# The Jenkins stage supplies the Worker Python Linux image. POSIX permission
# tests must actually run, so Windows/Git Bash is not an equivalent CI target.
test -x "${ci_python}"

"${ci_python}" -m pip install --disable-pip-version-check \
  --requirement "${repository_root}/AI/requirements.txt" \
  --requirement "${repository_root}/AI/requirements-dev.txt"

cd "${repository_root}/AI"
export PYTHONPATH="${repository_root}/AI:${repository_root}/Infra/spark${PYTHONPATH:+:${PYTHONPATH}}"

echo 'Running non-DB C regressions; PostgreSQL integration tests are intentionally not selected.'
"${ci_python}" -m pytest \
  tests/test_registry_review.py \
  tests/test_worker_intake.py \
  tests/test_public_intake.py \
  tests/test_worker_registry_source.py \
  tests/test_analysis_credentials.py \
  tests/test_analysis_clone.py \
  tests/test_analysis_consumer.py \
  tests/test_entrypoints.py \
  tests/test_job_review_provenance.py \
  tests/test_trend_archive.py \
  tests/test_recommendation_engine.py \
  tests/test_export_c_archive_activity.py \
  tests/test_week_public_selection.py \
  tests/test_compute_archive.py::test_archive_input_budget_supports_the_six_month_mvp_and_rejects_overage \
  tests/test_compute_archive.py::test_missing_archive_mount_is_retryable_operational_failure \
  --deselect tests/test_worker_intake.py::test_actual_app_startup_consumes_to_postgres_and_restart_deduplicates \
  --deselect tests/test_worker_registry_source.py::test_real_db_default_survives_app_restart \
  --deselect tests/test_analysis_clone.py::test_junction_cannot_redirect_cleanup_to_another_work_directory \
  --deselect tests/test_public_intake.py::test_postgres_publication_replay_after_restart_has_same_snapshot \
  --deselect tests/test_public_intake.py::test_database_failure_or_commit_response_loss_reuses_local_results \
  --deselect tests/test_public_intake.py::test_crashed_publication_waits_for_lease_then_reuses_local_parts \
  --junitxml "${results_xml}" \
  -q

"${ci_python}" - "${results_xml}" <<'PY'
import sys
from xml.etree import ElementTree

root = ElementTree.parse(sys.argv[1]).getroot()
skipped = sum(int(node.attrib.get("skipped", "0")) for node in root.iter("testsuite"))
if skipped:
    raise SystemExit(f"Non-DB CI selection unexpectedly skipped {skipped} test(s)")
PY
