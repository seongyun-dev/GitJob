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


def test_retry_exits_process_without_committing(monkeypatch):
    from worker import weekly_activity_consumer as entry

    class Fake:
        transport = type(
            "Transport",
            (),
            {"closed": False, "close": lambda self: setattr(self, "closed", True)},
        )()

        def run_once(self):
            return (Outcome.RETRY,)

    fake = Fake()
    monkeypatch.setattr(entry, "build_from_env", lambda: fake)
    assert entry.main() == 75
    assert fake.transport.closed


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

    example = (
        Path(__file__).resolve().parents[2] / ".env.example"
    ).read_text(encoding="utf-8")
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
