"""Entry-point rules for the weekly cohort bundle generator."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[1] / "github/fixtures/github_repo_snapshot_v1.json"
)
WEEK = "2026-08-10"
ROOT = (
    "hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=weekcohort-"
    + WEEK
    + "-v1"
)


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    cohort = tmp_path / "cohort.json"
    cohort.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    activity = tmp_path / "activity.ndjson"
    activity.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"repo_id": 100001, "event_count": 10, "week_start": WEEK},
                {"repo_id": 100002, "event_count": 70, "week_start": WEEK},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return cohort, activity


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    cohort, activity = _inputs(tmp_path)
    return [
        "--week-start",
        WEEK,
        "--cohort-snapshot",
        str(cohort),
        "--week-activity",
        str(activity),
        "--dataset-snapshot-id",
        "weekcohort-" + WEEK + "-v1",
        "--pipeline-run-id",
        "weekcohort-" + WEEK + "-001",
        "--publication-root",
        ROOT,
        "--generated-at",
        "2026-09-18T12:00:00+00:00",
        *extra,
    ]


def test_dry_run_reports_the_bundle_without_writing_anything(tmp_path, capsys):
    from github.weekly_cohort_snapshot_cli import main

    assert main(_argv(tmp_path, "--dry-run")) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "DRY_RUN"
    assert report["week_start"] == WEEK
    assert report["record_count"] == 2
    assert sorted(report["objects"]) == [
        "_SUCCESS.json",
        "failures.json",
        "run-summary.json",
        "snapshot.json",
    ]
    assert list(tmp_path.glob("out/*")) == []


def test_output_directory_receives_every_published_object(tmp_path, capsys):
    from github.weekly_cohort_snapshot_cli import main

    out = tmp_path / "out"
    assert main(_argv(tmp_path, "--output-dir", str(out))) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "WRITTEN"
    written = sorted(path.name for path in out.iterdir())
    assert written == [
        "_SUCCESS.json",
        "failures.json",
        "run-summary.json",
        "snapshot.json",
    ]
    marker = json.loads((out / "_SUCCESS.json").read_text(encoding="utf-8"))
    assert marker["objects"]["snapshot"]["uri"] == ROOT + "/snapshot.json"


def test_rerun_into_the_same_directory_is_refused_rather_than_overwritten(tmp_path):
    from github.weekly_cohort_snapshot_cli import main

    out = tmp_path / "out"
    assert main(_argv(tmp_path, "--output-dir", str(out))) == 0

    assert main(_argv(tmp_path, "--output-dir", str(out))) == 1


def test_a_destination_is_required(tmp_path, capsys):
    from github.weekly_cohort_snapshot_cli import main

    assert main(_argv(tmp_path)) == 2

    assert "destination" in capsys.readouterr().err


def test_activity_rows_for_another_week_are_refused(tmp_path, capsys):
    from github.weekly_cohort_snapshot_cli import main

    argv = _argv(tmp_path, "--dry-run")
    (tmp_path / "activity.ndjson").write_text(
        json.dumps({"repo_id": 100001, "event_count": 10, "week_start": "2026-08-31"})
        + "\n",
        encoding="utf-8",
    )

    assert main(argv) == 2

    assert "week_start" in capsys.readouterr().err
