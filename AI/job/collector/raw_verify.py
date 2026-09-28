"""Check that what a run says it archived is still in HDFS Raw.

### Why this exists

`raw_sink` records what it uploaded in `raw_upload.json`, and that record was
accurate when written. Nothing checks it afterwards.

On 2026-09-08 08:56 the HDFS volumes were recreated and everything archived
before that moment disappeared — GH Archive's 744-file August bootstrap and
5,124 Worknet postings among it. `hdfs fsck` reported HEALTHY with zero missing
blocks, because the NameNode metadata was reinitialised too: the files were not
damaged, they were never known. Nothing in the pipeline noticed. It was found
on 2026-09-09 by counting HDFS directories by hand.

The gap is structural, not a bug in the sink. `store_immutable` answers "is it
here now and are the bytes the same", which is the right question **at upload
time**. A run that ends with `unchanged` has no trigger to upload again, so
once a file leaves HDFS it stays gone. `-105` has a `validate` subcommand for
exactly this reason; the job collectors had no equivalent.

### What it checks, and what it deliberately does not

The URIs in `raw_upload.json` are used as written rather than rebuilt from
`raw_run_path`. The point is to verify **what the run claimed**, and a
recomputed path would hide a disagreement between the record and reality.

Length is compared, not content. Existence alone passes a truncated upload,
and reading a 34 MB batch back for every run costs more than the check is
worth — `store_immutable` already compared bytes when it wrote them. A
truncation shows up as a length mismatch.

### The four states are different problems

`NEVER_UPLOADED` and `MISSING` look alike in a directory listing and need
opposite responses. A run with no `raw_upload.json` was never archived — often
a host-side run where the WebHDFS 307 redirect could not resolve the DataNode
hostname. A run whose claimed files are gone was archived and then lost, which
means something removed them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from common.webhdfs import WebHdfsClient, WebHdfsError, normalize_hdfs_path
from job.collector.raw_sink import RAW_UPLOAD_RECORD, sink_from_env

__all__ = [
    "RunVerification",
    "VerifySummary",
    "verifier_from_env",
    "verify_output_root",
    "verify_run",
]

# States, ordered by how much they demand of a reader.
STATE_OK = "OK"
# Claimed by the run and absent from HDFS. Something removed it.
STATE_MISSING = "MISSING"
# Present with a different byte length. A truncated or replaced object.
STATE_SIZE_MISMATCH = "SIZE_MISMATCH"
# No `raw_upload.json` at all — the run never archived.
STATE_NEVER_UPLOADED = "NEVER_UPLOADED"
# The run's own record says the upload failed. Already known, not a new fact.
STATE_UPLOAD_FAILED = "UPLOAD_FAILED"
# The check itself could not be completed.
STATE_ERROR = "ERROR"

_PROBLEM_STATES = frozenset(
    {STATE_MISSING, STATE_SIZE_MISMATCH, STATE_UPLOAD_FAILED, STATE_ERROR}
)


@dataclass(frozen=True)
class RunVerification:
    """What one run directory looks like against HDFS."""

    run: str
    state: str
    files_claimed: int = 0
    files_present: int = 0
    problems: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == STATE_OK

    def as_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "run": self.run,
            "state": self.state,
            "files_claimed": self.files_claimed,
            "files_present": self.files_present,
        }
        if self.problems:
            body["problems"] = list(self.problems)
        if self.detail:
            body["detail"] = self.detail
        return body


@dataclass(frozen=True)
class VerifySummary:
    checked: tuple[RunVerification, ...] = ()

    @property
    def problems(self) -> tuple[RunVerification, ...]:
        return tuple(item for item in self.checked if item.state in _PROBLEM_STATES)

    @property
    def never_uploaded(self) -> tuple[RunVerification, ...]:
        return tuple(
            item for item in self.checked if item.state == STATE_NEVER_UPLOADED
        )

    @property
    def ok(self) -> bool:
        """Whether anything needs attention.

        `NEVER_UPLOADED` is deliberately excluded. Twelve Worknet development
        runs from 2026-09-07 were never archived and never will be; treating
        them as failures would make this check permanently red, which is the
        state that teaches people to ignore it (S15P21E102-186).
        """

        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return {
            "checked": len(self.checked),
            "ok": sum(1 for item in self.checked if item.ok),
            "never_uploaded": len(self.never_uploaded),
            "problems": [item.as_dict() for item in self.problems],
        }


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _claimed_uris(upload: dict[str, object]) -> list[str]:
    """Every URI the run says reached Raw.

    `unchanged` counts as claimed. It means "already there when we looked",
    which is exactly the state that later turned out to be untrue.
    """

    found: list[str] = []
    for key in ("uploaded", "unchanged"):
        entries = upload.get(key)
        if isinstance(entries, list):
            found.extend(uri for uri in entries if isinstance(uri, str) and uri)
    return found


def verify_run(client: WebHdfsClient, run_dir: Path) -> RunVerification:
    """Check one run directory. Never raises."""

    name = run_dir.name
    upload = _read_json(run_dir / RAW_UPLOAD_RECORD)
    if upload is None:
        return RunVerification(
            run=name,
            state=STATE_NEVER_UPLOADED,
            detail=f"{RAW_UPLOAD_RECORD} 없음",
        )

    failed = upload.get("failed")
    if isinstance(failed, list) and failed:
        return RunVerification(
            run=name,
            state=STATE_UPLOAD_FAILED,
            detail=f"회차 기록에 적재 실패 {len(failed)}건",
        )

    uris = _claimed_uris(upload)
    if not uris:
        return RunVerification(
            run=name,
            state=STATE_NEVER_UPLOADED,
            detail="적재 기록이 파일을 하나도 주장하지 않음",
        )

    present = 0
    problems: list[str] = []
    for uri in uris:
        remote = normalize_hdfs_path(uri)
        local = run_dir / PurePosixPath(remote).name
        try:
            length = client.length(remote)
        except (WebHdfsError, OSError) as error:
            return RunVerification(
                run=name,
                state=STATE_ERROR,
                files_claimed=len(uris),
                files_present=present,
                detail=str(error)[:300],
            )
        if length is None:
            problems.append(f"{remote.name}: HDFS 에 없음")
            continue
        present += 1
        if local.exists() and local.stat().st_size != length:
            problems.append(
                f"{remote.name}: 크기 불일치 로컬 {local.stat().st_size} / HDFS {length}"
            )

    if problems:
        state = (
            STATE_MISSING
            if any("없음" in problem for problem in problems)
            else STATE_SIZE_MISMATCH
        )
        return RunVerification(
            run=name,
            state=state,
            files_claimed=len(uris),
            files_present=present,
            problems=tuple(problems),
        )

    return RunVerification(
        run=name,
        state=STATE_OK,
        files_claimed=len(uris),
        files_present=present,
    )


def verify_output_root(
    client: WebHdfsClient,
    output_root: Path,
    *,
    prefix: str = "",
) -> list[RunVerification]:
    """Check every run directory under one collector's output directory.

    Sorted by name, which for these run ids is chronological — a reader
    scanning the report sees the oldest problem first.
    """

    if not output_root.is_dir():
        return []
    runs = sorted(
        (child for child in output_root.iterdir() if child.is_dir()),
        key=lambda child: child.name,
    )
    return [verify_run(client, run) for run in runs if run.name.startswith(prefix)]


def verify_sites(
    client: WebHdfsClient,
    data_root: Path,
    sites: Iterable[str],
) -> VerifySummary:
    checked: list[RunVerification] = []
    for site in sites:
        checked.extend(verify_output_root(client, data_root / site))
    return VerifySummary(checked=tuple(checked))


def verifier_from_env() -> WebHdfsClient | None:
    """The sink's client, or `None` when WebHDFS is not configured.

    Reuses `sink_from_env` so the check reads the same endpoint the uploads
    went to. A verifier pointed at a different cluster would be worse than no
    verifier.
    """

    sink = sink_from_env()
    return sink.client if sink is not None else None


def default_sites() -> Sequence[str]:
    """Collector output directories under `data/`.

    Hardcoded rather than derived from `schedule.toml`: a site whose schedule
    is disabled still has archived runs worth verifying, and 게임잡·커리어 are
    exactly that case.
    """

    return ("worknet", "saramin", "gamejob", "career")
