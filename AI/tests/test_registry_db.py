from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import psycopg
import pytest
from psycopg.rows import dict_row

from registry.contracts import TechnologyRegistry, load_registry
from registry.db import (
    ImmutableRegistryConflict,
    PostgresRegistryStore,
    RegistryIntegrityError,
    RegistryVersionUnavailable,
    registry_content_sha256,
)

AI_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = AI_ROOT / "registry/data/technology_registry_v1.json"


def _snapshot(version: str) -> TechnologyRegistry:
    seed = load_registry(SEED_PATH, repository_root=AI_ROOT.parent)
    return seed.model_copy(update={"registry_version": version})


@pytest.fixture
def registry_dsn() -> str:
    dsn = os.getenv("REGISTRY_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set REGISTRY_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    parameters = psycopg.conninfo.conninfo_to_dict(dsn)
    if not parameters.get("dbname", "").endswith("_test"):
        pytest.fail("REGISTRY_TEST_DATABASE_URL must name a dedicated *_test database")
    return dsn


@pytest.fixture
def clean_registry_versions(registry_dsn: str):
    versions = ("registry-20260909.91", "registry-20260909.92")
    with psycopg.connect(registry_dsn, row_factory=dict_row) as conn:
        _delete_registry_versions(conn, versions)
    yield versions
    with psycopg.connect(registry_dsn) as conn:
        _delete_registry_versions(conn, versions)


def _delete_registry_versions(conn, versions: tuple[str, ...]) -> None:
    parameters = (list(versions),)
    conn.execute(
        "DELETE FROM public.technology_registry_alias WHERE registry_version = ANY(%s)",
        parameters,
    )
    conn.execute(
        "DELETE FROM public.technology_category WHERE registry_version = ANY(%s)",
        parameters,
    )
    conn.execute(
        "DELETE FROM public.technology_mapping WHERE registry_version = ANY(%s)",
        parameters,
    )
    conn.execute(
        "DELETE FROM public.technology WHERE registry_version = ANY(%s)", parameters
    )
    conn.execute(
        "DELETE FROM public.technology_registry WHERE registry_version = ANY(%s)",
        parameters,
    )


def test_content_hash_is_a_stable_hash_of_the_validated_snapshot() -> None:
    snapshot = _snapshot("registry-20260909.91")

    assert registry_content_sha256(snapshot) == registry_content_sha256(
        TechnologyRegistry.model_validate_json(
            json.dumps(snapshot.model_dump(mode="json"))
        )
    )
    assert len(registry_content_sha256(snapshot)) == 64


def test_registry_connections_bound_statement_and_lock_waits(registry_dsn: str) -> None:
    with PostgresRegistryStore(registry_dsn)._connect() as conn:
        statement_timeout = conn.execute("SHOW statement_timeout").fetchone()
        lock_timeout = conn.execute("SHOW lock_timeout").fetchone()

    assert statement_timeout["statement_timeout"] == "15s"
    assert lock_timeout["lock_timeout"] == "5s"


def test_import_round_trips_versioned_content_and_provenance(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    version, _ = clean_registry_versions
    snapshot = _snapshot(version)
    store = PostgresRegistryStore(registry_dsn)

    imported = store.import_registry(
        snapshot,
        source_ref="AI/registry/data/technology_registry_v1.json",
        activate_alias=True,
    )

    loaded = store.load_registry(version)
    assert loaded == snapshot
    assert imported.registry_version == version
    assert imported.content_sha256 == registry_content_sha256(snapshot)
    assert imported.source_ref == "AI/registry/data/technology_registry_v1.json"
    assert store.resolve_version("technology-registry/v1") == imported


def test_alias_moves_only_when_activation_is_explicit_and_pinned_retry_stays_put(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    first_version, second_version = clean_registry_versions
    store = PostgresRegistryStore(registry_dsn)
    first = store.import_registry(
        _snapshot(first_version), source_ref="seed:first", activate_alias=True
    )
    store.import_registry(
        _snapshot(second_version), source_ref="seed:second", activate_alias=False
    )

    assert store.resolve_version("technology-registry/v1") == first

    store.activate_alias(second_version)

    assert (
        store.resolve_version("technology-registry/v1").registry_version
        == second_version
    )
    assert (
        store.resolve_version("technology-registry/v1", pinned_version=first_version)
        == first
    )


def test_c_import_and_alias_activation_leave_b_lifecycle_unchanged(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    first_version, second_version = clean_registry_versions
    with psycopg.connect(registry_dsn, row_factory=dict_row) as conn:
        before = conn.execute(
            """SELECT registry_version, status, published_at
               FROM public.technology_registry
               ORDER BY registry_version"""
        ).fetchall()

    store = PostgresRegistryStore(registry_dsn)
    store.import_registry(
        _snapshot(first_version), source_ref="seed:first", activate_alias=True
    )
    store.import_registry(_snapshot(second_version), source_ref="seed:second")
    store.activate_alias(second_version)

    with psycopg.connect(registry_dsn, row_factory=dict_row) as conn:
        unchanged = conn.execute(
            """SELECT registry_version, status, published_at
               FROM public.technology_registry
               WHERE registry_version <> ALL(%s)
               ORDER BY registry_version""",
            (list(clean_registry_versions),),
        ).fetchall()
        imported = conn.execute(
            """SELECT registry_version, status, published_at
               FROM public.technology_registry
               WHERE registry_version = ANY(%s)
               ORDER BY registry_version""",
            (list(clean_registry_versions),),
        ).fetchall()
        current_count = conn.execute(
            "SELECT count(*) AS count FROM public.technology_registry "
            "WHERE status = 'CURRENT'"
        ).fetchone()["count"]

    assert unchanged == before
    assert [row["status"] for row in imported] == ["RETIRED", "RETIRED"]
    assert all(row["published_at"] is not None for row in imported)
    assert current_count == 1


def test_native_b_version_without_c_metadata_cannot_be_claimed_by_import(
    registry_dsn: str,
) -> None:
    with psycopg.connect(registry_dsn, row_factory=dict_row) as conn:
        native = conn.execute(
            """SELECT registry_version, content_sha256, source_ref, imported_at
               FROM public.technology_registry
               WHERE status = 'CURRENT'"""
        ).fetchone()

    assert native is not None
    assert native["content_sha256"] is None
    assert native["source_ref"] is None
    assert native["imported_at"] is None
    with pytest.raises(ImmutableRegistryConflict):
        PostgresRegistryStore(registry_dsn).import_registry(
            _snapshot(native["registry_version"]), source_ref="test:must-not-backfill"
        )


def test_existing_content_version_cannot_be_overwritten(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    version, _ = clean_registry_versions
    store = PostgresRegistryStore(registry_dsn)
    original = _snapshot(version)
    store.import_registry(original, source_ref="seed:original")
    changed = original.model_copy(
        update={
            "technologies": (
                original.technologies[0].model_copy(update={"display_name": "Changed"}),
                *original.technologies[1:],
            )
        }
    )

    with pytest.raises(ImmutableRegistryConflict):
        store.import_registry(changed, source_ref="seed:changed")

    assert store.load_registry(version) == original


def test_different_versions_can_be_imported_concurrently_without_deadlock(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    versions = clean_registry_versions
    start = Barrier(len(versions))

    class SlowImportStore(PostgresRegistryStore):
        @staticmethod
        def _insert_snapshot_rows(conn, registry: TechnologyRegistry) -> None:
            PostgresRegistryStore._insert_snapshot_rows(conn, registry)
            # Keep both transactions holding their child-table write locks long
            # enough to expose a write-then-SHARE lock upgrade deadlock.
            time.sleep(0.25)

    def import_one(version: str) -> TechnologyRegistry:
        snapshot = _snapshot(version)
        start.wait(timeout=5)
        SlowImportStore(registry_dsn).import_registry(
            snapshot,
            source_ref=f"test:concurrent:{version}",
        )
        return snapshot

    with ThreadPoolExecutor(max_workers=len(versions)) as executor:
        imported = list(executor.map(import_one, versions))

    store = PostgresRegistryStore(registry_dsn)
    assert [store.load_registry(version) for version in versions] == imported


def test_db_mode_raises_when_version_or_alias_is_missing(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    store = PostgresRegistryStore(registry_dsn)

    with pytest.raises(RegistryVersionUnavailable):
        store.load_registry("registry-20260909.91")
    with pytest.raises(RegistryVersionUnavailable):
        store.resolve_version("technology-registry/v1")


def test_read_rejects_rows_that_no_longer_match_the_recorded_hash(
    registry_dsn: str,
    clean_registry_versions: tuple[str, str],
) -> None:
    version, _ = clean_registry_versions
    store = PostgresRegistryStore(registry_dsn)
    store.import_registry(_snapshot(version), source_ref="seed:integrity")
    with psycopg.connect(registry_dsn) as conn:
        conn.execute(
            "UPDATE public.technology SET display_name = 'tampered' "
            "WHERE registry_version = %s AND registry_order = 0",
            (version,),
        )

    with pytest.raises(RegistryIntegrityError, match="recorded hash"):
        store.load_registry(version)
    with pytest.raises(RegistryIntegrityError, match="recorded hash"):
        store.activate_alias(version)
    with pytest.raises(RegistryIntegrityError, match="recorded hash"):
        store.import_registry(
            _snapshot(version), source_ref="seed:integrity", activate_alias=True
        )
    with pytest.raises(RegistryVersionUnavailable):
        store.resolve_version("technology-registry/v1")
