import json

from test_compute_client import TOKEN, completed, job_event

from worker.client import CompletionReceipt, SubmissionError
from worker.submit import main


def test_cli_uses_environment_credentials_and_emits_only_completed_references(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "completion.json"
    path.write_text(json.dumps(job_event()), encoding="utf-8")
    monkeypatch.setenv("C_COMPUTE_URL", "http://worker")
    monkeypatch.setenv("C_COMPUTE_TOKEN", TOKEN)
    calls = []

    class Client:
        def __init__(self, base_url, token, **kwargs):
            assert base_url == "http://worker" and token == TOKEN

        def submit(self, kind, payload):
            calls.append((kind, payload))
            return CompletionReceipt.model_validate(completed()["data"])

    monkeypatch.setattr("worker.submit.CompletionClient", Client)
    assert main(["--kind", "JOB_BATCH", "--input", str(path)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "COMPLETED"
    assert TOKEN not in output.out + output.err
    assert len(calls) == 1


def test_cli_exhaustion_is_nonzero_without_printing_payload_or_credentials(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "completion.json"
    path.write_text(json.dumps(job_event()), encoding="utf-8")
    monkeypatch.setenv("C_COMPUTE_URL", "http://worker")
    monkeypatch.setenv("C_COMPUTE_TOKEN", TOKEN)

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args):
            raise SubmissionError("RETRY_EXHAUSTED", attempts=3, exhausted=True)

    monkeypatch.setattr("worker.submit.CompletionClient", Client)
    assert main(["--kind", "JOB_BATCH", "--input", str(path)]) != 0
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["status"] == "NOT_COMPLETED"
    assert TOKEN not in output.err


def test_cli_rejects_token_argument_without_echoing_it(capsys):
    assert (
        main(["--kind", "JOB_BATCH", "--input", "missing.json", "--token", TOKEN]) != 0
    )
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err


def test_cli_missing_file_and_invalid_payload_fail_before_network(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("C_COMPUTE_URL", "http://worker")
    monkeypatch.setenv("C_COMPUTE_TOKEN", TOKEN)
    assert main(["--kind", "JOB_BATCH", "--input", str(tmp_path / "missing.json")]) != 0
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"event_id": TOKEN}), encoding="utf-8")
    assert main(["--kind", "JOB_BATCH", "--input", str(path)]) != 0
    assert TOKEN not in capsys.readouterr().err
