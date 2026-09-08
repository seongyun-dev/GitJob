import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from github import public_run
from github.contracts import GitHubRepoSnapshotBatch


@pytest.fixture
def cli_input(tmp_path):
    payload = json.loads(
        Path("github/fixtures/github_repo_snapshot_v1.json").read_bytes()
    )
    row = payload["records"][0]
    body = b'{"dependencies":{"react":"1"}}'
    prefix = "hdfs:///fixture/artifacts/"
    row["artifacts"] = [
        {
            "artifact_type": "MANIFEST",
            "path": "package.json",
            "uri": prefix + "one.json",
            "size_bytes": len(body),
            "content_hash": hashlib.sha256(body).hexdigest(),
        }
    ]
    other = {
        **row,
        "repo_snapshot_id": "second",
        "github_repo_id": 2,
        "repo_full_name": "fixture/second",
        "activity_rank": 2,
    }
    payload["records"] = [row, other]
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(payload))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "one.json").write_bytes(body)
    return SimpleNamespace(
        snapshot=snapshot,
        artifacts=artifacts,
        prefix=prefix,
        checkpoint=tmp_path / "checkpoint",
        batch=GitHubRepoSnapshotBatch.model_validate(payload),
        registry=Path("registry/data/technology_registry_20260908_1.json"),
    )


def test_mirror_cli_bounded_run_then_resume_only_prints_final_when_complete(
    cli_input, capsys
):
    value = cli_input
    args = [
        "--mode",
        "mirror",
        "--snapshot",
        str(value.snapshot),
        "--registry",
        str(value.registry),
        "--artifact-root",
        str(value.artifacts),
        "--artifact-uri-prefix",
        value.prefix,
        "--checkpoint-dir",
        str(value.checkpoint),
        "--max-records",
        "1",
        "--max-new-partitions",
        "1",
    ]
    assert public_run.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "IN_PROGRESS" and output["final_path"] is None
    assert public_run.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "COMPLETED" and Path(output["final_path"]).is_file()
    assert output["analyzed_repo_count"] == 2
    assert "result" not in output


def test_mirror_plan_only_needs_no_artifact_or_checkpoint_paths(cli_input, capsys):
    assert (
        public_run.main(
            [
                "--snapshot",
                str(cli_input.snapshot),
                "--registry",
                str(cli_input.registry),
                "--plan-only",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "PLANNED"
    assert not cli_input.checkpoint.exists()


def test_hdfs_cli_uses_fixed_config_loader_hashes_and_exposes_reader_stats(
    cli_input, capsys, monkeypatch
):
    captured = {}

    class StubReader:
        def __init__(self, base_url, root_uri, **options):
            captured.update(base_url=base_url, root_uri=root_uri, options=options)
            self.stats = {"requests": 10, "retries": 0, "bytes_read": 2048}

        def read(self, uri, *, max_bytes):
            raise AssertionError("zero new partitions cannot read artifacts")

    def load(root_uri, reader):
        assert root_uri == "hdfs:///trusted/snapshot"
        return SimpleNamespace(
            batch=cli_input.batch,
            source_sha256="1" * 64,
            manifest_sha256="2" * 64,
            quality=SimpleNamespace(model_dump=lambda **_: {"candidate_count": 2}),
        )

    monkeypatch.setattr(public_run, "ReadOnlyWebHdfsReader", StubReader)
    monkeypatch.setattr(public_run, "load_published_snapshot", load)
    monkeypatch.setenv(
        "C_PUBLIC_DATANODE_ROUTES_JSON",
        '{"http://advertised:9864":"http://reachable:9864"}',
    )
    assert (
        public_run.main(
            [
                "--mode",
                "hdfs",
                "--root-uri",
                "hdfs:///trusted/snapshot",
                "--namenode-base-url",
                "http://nn:9870/webhdfs/v1",
                "--registry",
                str(cli_input.registry),
                "--checkpoint-dir",
                str(cli_input.checkpoint),
                "--max-new-partitions",
                "0",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "IN_PROGRESS"
    assert output["reader_stats"]["bytes_read"] == 2048
    assert captured["options"]["datanode_routes"] == {
        "http://advertised:9864": "http://reachable:9864"
    }
    state = json.loads((cli_input.checkpoint / "checkpoint.json").read_bytes())
    assert state["plan"]["manifest_sha256"] == "2" * 64


def test_cli_failure_does_not_print_invalid_argument_contents(capsys):
    assert public_run.main(["--unexpected", "secret-value"]) == 2
    output = capsys.readouterr()
    assert "secret-value" not in output.out + output.err
    assert json.loads(output.err)["status"] == "NOT_COMPLETED"
