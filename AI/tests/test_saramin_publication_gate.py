"""Splitting collection from `analysis_input` publication (S15P21E102-344).

Saramin's `main` uploaded a run to Raw and then published it to
`analysis_input` in the same breath, with no read-back in between. The only
way to withhold publication was `--no-upload-raw`, which also skips Raw and
so leaves nothing to publish later.

This mirrors JobKorea's `-340` contract: `--no-publish-analysis-input` stops
after Raw verification, and the Raw upload now gets the same `verify_run`
read-back JobKorea has. The publish-only half is not rebuilt here --
`job.collector.backfill_cli` already republishes a run out of Raw for any
source, reusing `analysis_input.release_blockers` as its gate, and
`tests/test_job_analysis_input_backfill.py` already pins that for saramin
(`test_a_second_pass_republishes_nothing` seeds `saramin/SARAMIN-A` and
asserts the second pass stores nothing).

One deliberate difference from JobKorea: its deferred branch returns
`0 if records else 1` directly. Saramin, Career, GameJob and Worknet all end
on `collector_exit_code(...)`, so skipping publication must not change how the
run's own quality is reported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job.collector.analysis_input import AnalysisInputPublishResult
from Saramin_Collector_V1 import crawler as crawler_module
from test_saramin import LIST_HTML, FakeClient

TODAY = "2026-09-09"


class StubHttpClient(FakeClient):
    """`main` builds its own client, so stand in at the construction site."""

    def __init__(self, **_kwargs: object) -> None:
        super().__init__([LIST_HTML])


class RecordingSink:
    """Records the Raw upload instead of writing to HDFS."""

    def __init__(self) -> None:
        self.uploads: list[Path] = []
        # `main` hands `sink.client` to `verify_run`; the recorder ignores it,
        # but the attribute has to exist for the call to happen at all.
        self.client = object()

    def upload_run(self, run_dir: Path, **_kwargs: object) -> Any:
        self.uploads.append(run_dir)

        class _Upload:
            ok = True
            run_path = "hdfs:///gitjob/raw/saramin/dt=2026-09-09"
            uploaded = ("manifest.json",)
            unchanged = ()
            failed = ()

            def as_dict(self) -> dict[str, object]:
                return {"ok": True, "run_path": _Upload.run_path}

        return _Upload()


class Stages:
    """What each stage did, so a test asserts on the sequence not a mock."""

    def __init__(self) -> None:
        self.sink_built = 0
        self.uploaded: list[Path] = []
        self.upload_records: list[Path] = []
        self.verified: list[Path] = []
        self.published: list[Path] = []


def install_stages(monkeypatch: Any, *, verify_ok: bool = True) -> Stages:
    """Replace the post-crawl side effects with recorders."""

    stages = Stages()
    sink = RecordingSink()

    def fake_sink_from_env() -> Any:
        stages.sink_built += 1
        return sink

    def fake_write_upload_record(run_dir: Path, _upload: object) -> Path:
        stages.upload_records.append(run_dir)
        return run_dir / "raw_upload.json"

    class _Verification:
        ok = verify_ok
        state = "OK" if verify_ok else "MISMATCH"

    def fake_verify_run(_client: object, run_dir: Path) -> Any:
        stages.verified.append(run_dir)
        return _Verification()

    def fake_publish_from_env(
        run_dir: Path,
        *,
        source: str,
        pipeline_run_id: str,
    ) -> AnalysisInputPublishResult:
        stages.published.append(run_dir)
        return AnalysisInputPublishResult(
            run_path=(
                f"hdfs:///gitjob/analysis_input/jobs/{source.lower()}/{pipeline_run_id}"
            ),
            published=("manifest.json",),
        )

    monkeypatch.setattr(crawler_module, "PoliteHttpClient", StubHttpClient)
    monkeypatch.setattr(crawler_module, "sink_from_env", fake_sink_from_env)
    monkeypatch.setattr(crawler_module, "write_upload_record", fake_write_upload_record)
    monkeypatch.setattr(crawler_module, "verify_run", fake_verify_run)
    monkeypatch.setattr(crawler_module, "publish_from_env", fake_publish_from_env)
    stages.uploaded = sink.uploads
    return stages


def argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--start-date",
        TODAY,
        "--end-date",
        TODAY,
        "--max-pages",
        "1",
        "--request-delay",
        "0",
        "--no-detail",
        "--output-dir",
        str(tmp_path),
        *extra,
    ]


def test_the_default_run_still_uploads_verifies_and_publishes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The existing contract, plus the read-back Saramin was missing."""

    stages = install_stages(monkeypatch)

    crawler_module.main(argv(tmp_path))

    assert len(stages.uploaded) == 1
    assert len(stages.verified) == 1
    assert len(stages.published) == 1


def test_no_publish_analysis_input_stops_after_raw_verification(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Raw is still uploaded and verified; `analysis_input` stays untouched."""

    stages = install_stages(monkeypatch)

    crawler_module.main(argv(tmp_path, "--no-publish-analysis-input"))

    assert len(stages.uploaded) == 1
    assert len(stages.verified) == 1
    assert stages.published == []


def test_a_deferred_run_keeps_the_collector_exit_code_contract(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Skipping publication must not change how the run's quality is reported.

    JobKorea returns `0 if records else 1` from its deferred branch. Saramin
    shares `collector_exit_code` with Career, GameJob and Worknet, so an early
    return here would drop that contract for this collector alone.
    """

    install_stages(monkeypatch)
    monkeypatch.setattr(crawler_module, "collector_exit_code", lambda *_a, **_k: 7)

    assert crawler_module.main(argv(tmp_path, "--no-publish-analysis-input")) == 7


def test_no_upload_raw_keeps_its_own_meaning(tmp_path: Path, monkeypatch: Any) -> None:
    """`--no-upload-raw` skips Raw too, so it cannot stand in for the new flag."""

    stages = install_stages(monkeypatch)

    crawler_module.main(argv(tmp_path, "--no-upload-raw"))

    assert stages.sink_built == 0
    assert stages.verified == []
    assert stages.published == []


def test_a_failed_raw_verification_blocks_publication(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A run that did not survive read-back must not become a C input."""

    stages = install_stages(monkeypatch, verify_ok=False)

    exit_code = crawler_module.main(argv(tmp_path))

    assert stages.published == []
    assert exit_code != 0


def test_the_two_switches_are_separate_arguments() -> None:
    parser = crawler_module.build_arg_parser()

    default = parser.parse_args([])
    assert default.no_upload_raw is False
    assert default.no_publish_analysis_input is False

    deferred = parser.parse_args(["--no-publish-analysis-input"])
    assert deferred.no_upload_raw is False
    assert deferred.no_publish_analysis_input is True


def test_the_deferred_message_names_the_saramin_backfill_command(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """The log has to say how to finish the job, for this source."""

    install_stages(monkeypatch)

    crawler_module.main(argv(tmp_path, "--no-publish-analysis-input"))

    message = capsys.readouterr().err
    assert "analysis_input=deferred" in message
    assert "backfill_cli --source saramin --execute" in message
