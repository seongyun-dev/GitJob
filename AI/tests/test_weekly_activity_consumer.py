from worker.weekly_activity_intake import Outcome


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
