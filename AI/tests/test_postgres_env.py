import sys

from psycopg.conninfo import conninfo_to_dict

from worker import job_projection_head
from worker.postgres_env import dsn_from_postgres_env


def test_postgres_env_dsn_preserves_reserved_characters():
    values = {
        "POSTGRES_USER": "worker@tenant",
        "POSTGRES_PASSWORD": "p@ss:word/with#percent% and space",
        "POSTGRES_HOST": "postgres.internal",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "git-job",
    }

    parsed = conninfo_to_dict(dsn_from_postgres_env(values))

    assert parsed == {
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "host": values["POSTGRES_HOST"],
        "port": values["POSTGRES_PORT"],
        "dbname": values["POSTGRES_DB"],
    }


def test_projection_head_rollback_can_use_explicit_postgres_env(
    monkeypatch, capsys
):
    expected = "jp-" + "a" * 64
    target = "jp-" + "b" * 64
    calls = []

    class Store:
        def __init__(self, dsn):
            calls.append(("dsn", dsn))

        def rollback(self, **kwargs):
            calls.append(("rollback", kwargs))
            return target

    monkeypatch.setattr(
        job_projection_head, "dsn_from_postgres_env", lambda: "safe-dsn"
    )
    monkeypatch.setattr(job_projection_head, "JobProjectionStore", Store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "job_projection_head",
            "--from-postgres-env",
            "--expected-current",
            expected,
            "--to",
            target,
            "--actor",
            "operator-1",
            "--reason",
            "incident rollback",
        ],
    )

    job_projection_head.main()

    assert calls == [
        ("dsn", "safe-dsn"),
        (
            "rollback",
            {
                "expected_current": expected,
                "target_projection_version_id": target,
                "actor": "operator-1",
                "reason": "incident rollback",
            },
        ),
    ]
    assert '"status": "ROLLED_BACK"' in capsys.readouterr().out
