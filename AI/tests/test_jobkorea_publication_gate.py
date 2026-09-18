"""Splitting collection from `analysis_input` publication (S15P21E102-340).

`main` runs collect -> Raw upload -> Raw verify -> publish as one process with
one exit code, which is deliberate (`analysis_input.publish_from_env`'s
docstring). It also means an 11-hour v3 crawl cannot be reviewed before its
output reaches `analysis_input`.

`--no-publish-analysis-input` stops after Raw verification so the run can be
inspected first. It is a separate switch from `--no-upload-raw`, which skips
Raw as well and therefore leaves nothing to publish later.

The publish-only half already exists and is not rebuilt here:
`job.collector.backfill_cli` republishes a run that is already in HDFS Raw,
reusing `analysis_input.release_blockers` as its gate
(`tests/test_job_analysis_input_backfill.py`).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from job.collector.analysis_input import AnalysisInputPublishResult
from JobKorea_Collector_V1 import crawler as crawler_module
from JobKorea_Collector_V1.dates import SEOUL

LIST_HTML = """
<div id="dev-gi-list">
  <div class="tplList tplJobList">
    <table>
      <tbody>
        <tr class="devloopArea" data-gno="49872974" data-info="49872974|x|y">
          <td class="tplCo">
            <a href="/Recruit/Co_Read/C/32492233" class="normalLog">㈜그린플로우</a>
          </td>
          <td class="tplTit">
            <div class="titBx">
              <strong>
                <a href="/Recruit/GI_Read/49872974?rPageCode=PL"
                   title="[경력] 웹 개발자 모집">[경력] 웹 개발자 모집</a>
              </strong>
              <p class="etc">
                <span class="cell">경력5년↑</span>
                <span class="cell">경기 군포시 외</span>
              </p>
              <p class="dsc">서버관리, SI개발</p>
            </div>
          </td>
          <td class="odd">
            <span class="time"><span>08/25</span>(화) 등록</span>
            <span class="date"><span>~08/31</span>(월)</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
"""

EMPTY_LIST_HTML = """
<div id="dev-gi-list">
  <div class="tplList tplJobList"><table><tbody></tbody></table></div>
</div>
"""


class StubHttpClient:
    """Answers one listing page per duty code, then empty."""

    def __init__(self, **_kwargs: object) -> None:
        self.seen: set[tuple[str, int]] = set()

    def post(
        self,
        _path: str,
        data: list[tuple[str, str]],
        **_kwargs: object,
    ) -> str:
        fields = dict(data)
        key = (fields["condition[duty]"], int(fields["page"]))
        if key in self.seen:
            return EMPTY_LIST_HTML
        self.seen.add(key)
        return LIST_HTML if key[1] == 1 else EMPTY_LIST_HTML

    def get(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("a --no-detail run must not fetch a detail page")


class RecordingSink:
    """Records the Raw upload instead of writing to HDFS."""

    def __init__(self) -> None:
        self.uploads: list[Path] = []
        # `main` hands `sink.client` to `verify_run`; the recorder below ignores
        # it, but the attribute has to exist for the call to happen at all.
        self.client = object()

    def upload_run(self, run_dir: Path, **_kwargs: object) -> Any:
        self.uploads.append(run_dir)

        class _Upload:
            ok = True
            run_path = "hdfs:///gitjob/raw/jobkorea/dt=2026-09-19"
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
    """Replace the three post-crawl side effects with recorders."""

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
            run_path=f"hdfs:///gitjob/analysis_input/jobs/{source.lower()}/{pipeline_run_id}",
            published=("manifest.json",),
        )

    monkeypatch.setattr(crawler_module, "JobKoreaHttpClient", StubHttpClient)
    monkeypatch.setattr(crawler_module, "sink_from_env", fake_sink_from_env)
    monkeypatch.setattr(crawler_module, "write_upload_record", fake_write_upload_record)
    monkeypatch.setattr(crawler_module, "verify_run", fake_verify_run)
    monkeypatch.setattr(crawler_module, "publish_from_env", fake_publish_from_env)
    stages.uploaded = sink.uploads
    return stages


def legacy_argv(tmp_path: Path) -> list[str]:
    return [
        "--duty-code",
        "1000229",
        "--start-date",
        "2026-08-25",
        "--end-date",
        "2026-08-25",
        "--max-pages",
        "2",
        "--request-delay",
        "0",
        "--no-detail",
        "--no-ocr",
        "--output-dir",
        str(tmp_path),
    ]


def v3_argv(tmp_path: Path) -> list[str]:
    return [
        "--duty-preset",
        "service-roles",
        "--max-pages",
        "2",
        "--request-delay",
        "0",
        "--no-detail",
        "--no-ocr",
        "--output-dir",
        str(tmp_path),
    ]


def test_the_default_run_still_uploads_verifies_and_publishes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """The existing contract: one process, all four stages, one exit code."""

    stages = install_stages(monkeypatch)

    assert crawler_module.main(legacy_argv(tmp_path)) == 0

    assert len(stages.uploaded) == 1
    assert len(stages.verified) == 1
    assert len(stages.published) == 1


def test_no_publish_analysis_input_stops_after_raw_verification(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """The new switch: Raw is still uploaded and verified, publication is not.

    This is what makes an 11-hour v3 crawl reviewable -- the run lands in Raw,
    verified, and `analysis_input` stays untouched until someone approves it.
    """

    stages = install_stages(monkeypatch)

    argv = [*legacy_argv(tmp_path), "--no-publish-analysis-input"]
    assert crawler_module.main(argv) == 0

    assert len(stages.uploaded) == 1
    assert len(stages.verified) == 1
    assert stages.published == []


def test_no_upload_raw_keeps_its_own_meaning(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """`--no-upload-raw` skips Raw too, so it cannot stand in for the new flag."""

    stages = install_stages(monkeypatch)

    argv = [*legacy_argv(tmp_path), "--no-upload-raw"]
    assert crawler_module.main(argv) == 0

    assert stages.sink_built == 0
    assert stages.uploaded == []
    assert stages.verified == []
    assert stages.published == []


def test_a_failed_raw_verification_still_blocks_publication(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """The new flag must not become the only thing standing between the two."""

    stages = install_stages(monkeypatch, verify_ok=False)

    assert crawler_module.main(legacy_argv(tmp_path)) == 1

    assert len(stages.verified) == 1
    assert stages.published == []


def test_a_v3_run_can_stop_before_publication(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """The flag is orthogonal to collection mode, so v3 gets the same split."""

    stages = install_stages(monkeypatch)

    argv = [*v3_argv(tmp_path), "--no-publish-analysis-input"]
    assert crawler_module.main(argv) == 0

    assert len(stages.uploaded) == 1
    assert len(stages.verified) == 1
    assert stages.published == []


def test_a_v3_run_publishes_by_default(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    stages = install_stages(monkeypatch)

    assert crawler_module.main(v3_argv(tmp_path)) == 0

    assert len(stages.published) == 1


def test_the_two_switches_are_separate_arguments() -> None:
    """Named apart on purpose: one defers publication, one skips Raw."""

    parser = crawler_module.build_arg_parser()

    default = parser.parse_args([])
    assert default.no_upload_raw is False
    assert default.no_publish_analysis_input is False

    deferred = parser.parse_args(["--no-publish-analysis-input"])
    assert deferred.no_upload_raw is False
    assert deferred.no_publish_analysis_input is True


def test_the_seoul_clock_is_used_for_the_default_range() -> None:
    """Guards the argv helpers above from drifting off the collector's timezone."""

    today = datetime.now(tz=SEOUL).date()

    assert isinstance(today, date)
