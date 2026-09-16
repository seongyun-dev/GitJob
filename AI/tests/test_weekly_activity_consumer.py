import pytest

from common.kafka import KafkaError, consumer_from_env
from worker.weekly_activity_intake import Outcome


def test_kafka_offset_reset_defaults_to_earliest():
    transport = consumer_from_env(
        "topic", "group", {"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"}
    )
    assert transport is not None
    assert transport.auto_offset_reset == "earliest"


def test_kafka_offset_reset_accepts_explicit_values():
    for value in ("earliest", "latest"):
        transport = consumer_from_env(
            "topic",
            "group",
            {
                "KAFKA_BOOTSTRAP_SERVERS": "broker:9092",
                "KAFKA_AUTO_OFFSET_RESET": value,
            },
        )
        assert transport is not None
        assert transport.auto_offset_reset == value


def test_kafka_offset_reset_rejects_invalid_value():
    for env in (
        {
            "KAFKA_BOOTSTRAP_SERVERS": "broker:9092",
            "KAFKA_AUTO_OFFSET_RESET": "middle",
        },
        {"KAFKA_AUTO_OFFSET_RESET": "middle"},
    ):
        with pytest.raises(KafkaError, match="KAFKA_AUTO_OFFSET_RESET"):
            consumer_from_env("topic", "group", env)


def test_retry_stays_in_process_reconnects_and_backs_off(monkeypatch, tmp_path):
    from worker import weekly_activity_consumer as entry

    class StopLoop(Exception):
        pass

    class Transport:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class Fake:
        def __init__(self, result=None):
            self.transport = Transport()
            self.result = result
            self.last_retry_code = "PUBLIC_GITHUB_NOT_READY"

        def run_once(self):
            if self.result is None:
                raise StopLoop
            return self.result

    first = Fake((Outcome.RETRY,))
    second = Fake()
    consumers = iter((first, second))
    sleeps = []
    monkeypatch.setenv("WEEKLY_ACTIVITY_RETRY_DELAY_SECONDS", "3")
    monkeypatch.setenv("WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS", "12")
    monkeypatch.setenv("WEEKLY_ACTIVITY_STATUS_FILE", str(tmp_path / "status.json"))
    with pytest.raises(StopLoop):
        entry.run(factory=lambda: next(consumers), sleeper=sleeps.append)
    assert sleeps == [3]
    assert first.transport.closed
    assert second.transport.closed


def test_retry_delay_is_exponential_and_capped(monkeypatch, tmp_path):
    from worker import weekly_activity_consumer as entry

    class StopLoop(Exception):
        pass

    class Fake:
        last_retry_code = "INPUT_ADAPTER_UNAVAILABLE"

        def __init__(self, retry):
            self.retry = retry
            self.transport = type("Transport", (), {"close": lambda self: None})()

        def run_once(self):
            if not self.retry:
                raise StopLoop
            return (Outcome.RETRY,)

    consumers = iter((Fake(True), Fake(True), Fake(True), Fake(False)))
    sleeps = []
    monkeypatch.setenv("WEEKLY_ACTIVITY_RETRY_DELAY_SECONDS", "3")
    monkeypatch.setenv("WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS", "5")
    monkeypatch.setenv("WEEKLY_ACTIVITY_STATUS_FILE", str(tmp_path / "status.json"))
    with pytest.raises(StopLoop):
        entry.run(factory=lambda: next(consumers), sleeper=sleeps.append)
    assert sleeps == [3, 5, 5]


def test_readiness_reports_ready_and_blocked(monkeypatch, tmp_path):
    from worker import weekly_activity_consumer as entry
    from worker import weekly_activity_health as health

    path = tmp_path / "status.json"
    monkeypatch.setenv("WEEKLY_ACTIVITY_STATUS_FILE", str(path))
    assert health.main() == 1
    entry._write_status("BLOCKED", reason="PUBLIC_GITHUB_NOT_READY")
    assert health.main() == 1
    entry._write_status("READY")
    assert health.main() == 0


def test_base_compose_configures_retry_backoff_and_readiness():
    from pathlib import Path

    compose = (
        Path(__file__).resolve().parents[2] / "Infra" / "compose" / "compose.yaml"
    ).read_text(encoding="utf-8")
    assert "WEEKLY_ACTIVITY_RETRY_DELAY_SECONDS" in compose
    assert "WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS" in compose
    assert 'test: ["CMD", "python", "-m", "worker.weekly_activity_health"]' in compose


def test_health_probe_does_not_announce_recovery_while_health_is_starting():
    from pathlib import Path

    probe = (
        Path(__file__).resolve().parents[2] / "Infra" / "scripts" / "health-probe.sh"
    ).read_text(encoding="utf-8")
    assert r"\(health: starting\)" in probe
    assert '"$health" == "starting"' in probe
    assert 'echo "[$HOST_LABEL] PENDING:' in probe


def test_environment_boolean_is_strict(monkeypatch):
    from worker import weekly_activity_consumer as entry

    monkeypatch.setenv("C_WEEKLY_INCLUDE_PARTIAL", "yes")
    try:
        entry._boolean("C_WEEKLY_INCLUDE_PARTIAL")
    except ValueError as error:
        assert "true or false" in str(error)
    else:
        raise AssertionError("invalid boolean must fail closed")


def test_datanode_host_mapping_becomes_reader_origin_routes(monkeypatch):
    from worker import weekly_activity_consumer as entry

    monkeypatch.setenv("WEBHDFS_URL", "http://namenode:9870/webhdfs/v1")
    monkeypatch.setenv("WEBHDFS_DATANODE_HOSTS", "datanode:9864=100.70.66.38:9864")
    assert entry._datanode_routes() == {
        "http://datanode:9864": "http://100.70.66.38:9864"
    }


def test_service_host_override_defaults_to_earliest():
    """The library default was never the problem — the override was.

    `consumer_from_env` has defaulted to `earliest` all along, but the
    Service-host override pinned `latest`, and that is the file Production
    runs. A new group then seeks past events already sitting in the topic,
    which is exactly how `gitjob-weekly-trend-prod-v1` ended up idling with an
    unread completion event at offset 0 (S15P21E102-282). Assert the rendered
    default here so the two cannot drift apart again.
    """

    from pathlib import Path

    override = (
        Path(__file__).resolve().parents[2]
        / "Infra"
        / "compose"
        / "compose.weekly-host.yaml"
    ).read_text(encoding="utf-8")
    assert (
        "KAFKA_AUTO_OFFSET_RESET: ${WEEKLY_CONSUMER_KAFKA_AUTO_OFFSET_RESET:-earliest}"
        in override
    )
    assert ":-latest}" not in override


def test_env_example_matches_the_override_default():
    from pathlib import Path

    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(
        encoding="utf-8"
    )
    assert "WEEKLY_CONSUMER_KAFKA_AUTO_OFFSET_RESET=earliest" in example


def test_offset_reset_is_scoped_to_the_weekly_consumer():
    """No other service may be forced onto a reset policy by compose.

    `earliest` is safe for a group that has never committed and a no-op for one
    that has, but forcing it across the stack would still be a change nobody
    asked for. Only the Weekly override sets this key.
    """

    from pathlib import Path

    compose_dir = Path(__file__).resolve().parents[2] / "Infra" / "compose"
    setters = [
        path.name
        for path in sorted(compose_dir.glob("*.yaml"))
        if "KAFKA_AUTO_OFFSET_RESET" in path.read_text(encoding="utf-8")
    ]
    assert setters == ["compose.weekly-host.yaml"]
