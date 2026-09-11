"""The B family default resolves a DB snapshot; files require explicit local mode."""

# ruff: noqa: F811 -- pytest discovers the imported isolated-DB fixtures.

from types import SimpleNamespace

import pytest
from test_compute_api import REGISTRY

# Only the explicit isolated-DB integration test uses these fixtures.
from test_registry_db import clean_registry_versions, registry_dsn  # noqa: F401

from worker.api import default_registry


def test_default_source_resolves_b_family_and_loads_exact_snapshot(monkeypatch):
    from registry import db

    calls = []

    class Source:
        def __init__(self, dsn):
            calls.append(("dsn", dsn))

        def resolve_version(self, requested):
            calls.append(("resolve", requested))
            return SimpleNamespace(registry_version=REGISTRY.registry_version)

        def load_registry(self, version):
            calls.append(("load", version))
            return REGISTRY

    monkeypatch.setattr(db, "PostgresRegistryStore", Source)
    monkeypatch.setenv("C_COMPUTE_DATABASE_URL", "local-explicit-test-dsn")
    monkeypatch.delenv("C_REGISTRY_BACKEND", raising=False)
    monkeypatch.delenv("C_REGISTRY_VERSION", raising=False)
    assert default_registry() == REGISTRY
    assert calls == [
        ("dsn", "local-explicit-test-dsn"),
        ("resolve", "technology-registry/v1"),
        ("load", REGISTRY.registry_version),
    ]


def test_db_failure_never_falls_back_to_bundled_json(monkeypatch):
    from registry import db

    class Source:
        def __init__(self, dsn):
            pass

        def resolve_version(self, requested):
            raise db.RegistryVersionUnavailable("no approved snapshot")

    monkeypatch.setattr(db, "PostgresRegistryStore", Source)
    monkeypatch.setenv("C_REGISTRY_BACKEND", "postgres")
    monkeypatch.setenv("C_COMPUTE_DATABASE_URL", "local-explicit-test-dsn")
    with pytest.raises(db.RegistryVersionUnavailable):
        default_registry()


def test_file_mode_is_explicit_and_preserves_immutable_version(monkeypatch):
    monkeypatch.setenv("C_REGISTRY_BACKEND", "file")
    monkeypatch.delenv("C_REGISTRY_PATH", raising=False)
    assert default_registry().registry_version == "registry-20260911.1"


def test_real_db_default_survives_app_restart(
    monkeypatch, registry_dsn, clean_registry_versions
):
    from fastapi.testclient import TestClient
    from test_compute_api import TOKEN

    from registry.db import PostgresRegistryStore
    from worker.api import create_compute_app
    from worker.store import ComputeStore, apply_migration

    selected = REGISTRY.model_copy(
        update={"registry_version": clean_registry_versions[0]}
    )
    PostgresRegistryStore(registry_dsn).import_registry(
        selected, source_ref="test:worker-default", activate_alias=True
    )
    apply_migration(registry_dsn)
    monkeypatch.setenv("C_REGISTRY_BACKEND", "postgres")
    monkeypatch.setenv("C_REGISTRY_VERSION", "technology-registry/v1")
    for _ in range(2):
        with TestClient(
            create_compute_app(store=ComputeStore(registry_dsn), token=TOKEN),
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            assert client.get("/ready").status_code == 200
            reply = client.get("/internal/v1/c/registry")
            assert reply.json()["data"]["registry_version"] == selected.registry_version
            assert reply.json()["data"] == selected.model_dump(mode="json")


def test_missing_registry_keeps_process_alive_but_blocks_compute(monkeypatch):
    from fastapi.testclient import TestClient
    from test_compute_api import TOKEN

    from registry.db import RegistryVersionUnavailable
    from worker import api

    def unavailable(**kwargs):
        raise RegistryVersionUnavailable("seed not approved")

    monkeypatch.setattr(api, "default_registry", unavailable)
    with TestClient(api.create_compute_app(token=TOKEN)) as client:
        assert client.get("/health").status_code == 200
        reply = client.get("/ready", headers={"Authorization": f"Bearer {TOKEN}"})
        assert reply.status_code == 503
        assert reply.json()["code"] == "C_REGISTRY_UNAVAILABLE"


def test_configured_intake_without_registry_reports_unavailable_not_disabled(
    monkeypatch, tmp_path
):
    from fastapi.testclient import TestClient
    from test_compute_api import TOKEN

    from registry.db import RegistryVersionUnavailable
    from worker import api

    def unavailable(**kwargs):
        raise RegistryVersionUnavailable("seed not approved")

    monkeypatch.setattr(api, "default_registry", unavailable)
    # A configured path cannot become a healthy HTTP-only mode while the
    # Registry is unavailable. Authorization must run before the status body.
    monkeypatch.setenv("C_INTAKE_CONFIG", str(tmp_path / "intake.json"))
    with TestClient(api.create_compute_app(token=TOKEN)) as client:
        endpoint = "/internal/v1/c/intake/status"
        assert client.get("/health").status_code == 200
        assert client.get(endpoint).status_code == 401
        reply = client.get(endpoint, headers={"Authorization": f"Bearer {TOKEN}"})
        assert reply.status_code == 503
        assert reply.json()["code"] == "C_REGISTRY_UNAVAILABLE"
        assert "data" not in reply.json()


def test_transient_startup_failure_recovers_once_and_then_pins_registry(monkeypatch):
    import psycopg
    from fastapi.testclient import TestClient
    from test_compute_api import TOKEN

    from worker import api

    attempts, delays = [], []

    def load(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise psycopg.errors.LockNotAvailable("temporary import lock")
        return REGISTRY

    monkeypatch.setattr(api, "default_registry", load)
    monkeypatch.setattr("time.sleep", delays.append)
    store = SimpleNamespace(ready=lambda: True)
    with TestClient(
        api.create_compute_app(store=store, token=TOKEN),
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/internal/v1/c/registry").json()["data"] == (
            REGISTRY.model_dump(mode="json")
        )
    assert len(attempts) == 2
    assert delays == [1]


def test_exhausted_transient_startup_failure_stops_instead_of_staying_unready(
    monkeypatch, caplog
):
    import psycopg

    from worker import api

    attempts, delays = [], []

    def unavailable(**kwargs):
        attempts.append(kwargs)
        raise psycopg.OperationalError("password=must-not-enter-logs")

    monkeypatch.setattr(api, "default_registry", unavailable)
    monkeypatch.setattr("time.sleep", delays.append)
    with pytest.raises(RuntimeError, match="Registry startup retries exhausted"):
        api.create_compute_app()
    assert len(attempts) == 3
    assert delays == [1, 2]
    assert "OperationalError" in caplog.text
    assert "must-not-enter-logs" not in caplog.text


@pytest.mark.parametrize("failure_kind", ["missing", "integrity", "schema"])
def test_nontransient_registry_failure_is_reported_without_retry(
    monkeypatch, caplog, failure_kind
):
    import psycopg
    from fastapi.testclient import TestClient
    from test_compute_api import TOKEN

    from registry.db import RegistryIntegrityError, RegistryVersionUnavailable
    from worker import api

    failures = {
        "missing": RegistryVersionUnavailable,
        "integrity": RegistryIntegrityError,
        "schema": psycopg.errors.UndefinedTable,
    }
    attempts, delays = [], []

    def unavailable(**kwargs):
        attempts.append(kwargs)
        raise failures[failure_kind]("private details must not be logged")

    monkeypatch.setattr(api, "default_registry", unavailable)
    monkeypatch.setattr("time.sleep", delays.append)
    with TestClient(api.create_compute_app(token=TOKEN)) as client:
        reply = client.get("/ready", headers={"Authorization": f"Bearer {TOKEN}"})
        assert reply.status_code == 503
        assert reply.json()["code"] == "C_REGISTRY_UNAVAILABLE"
    assert len(attempts) == 1
    assert delays == []
    assert failures[failure_kind].__name__ in caplog.text
    assert "private details" not in caplog.text
