"""Fresh V1-V11 migration proof for B lifecycle and C snapshot coexistence."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from registry.contracts import TechnologyRegistry, load_registry
from registry.db import PostgresRegistryStore

AI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AI_ROOT.parent
MIGRATION_ROOT = REPOSITORY_ROOT / "BE/src/main/resources/db/migration"
SEED_PATH = AI_ROOT / "registry/data/technology_registry_v1.json"


def _migration_number(path: Path) -> int:
    match = re.fullmatch(r"V([0-9]+)__.+\.sql", path.name)
    if match is None:
        raise AssertionError(f"unexpected migration filename: {path.name}")
    return int(match.group(1))


@pytest.fixture
def freshly_migrated_registry_dsn() -> Iterator[str]:
    configured = os.getenv("REGISTRY_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("Set REGISTRY_TEST_DATABASE_URL to an isolated PostgreSQL server")
    parameters = conninfo_to_dict(configured)
    if not parameters.get("dbname", "").endswith("_test"):
        pytest.fail("REGISTRY_TEST_DATABASE_URL must name a dedicated *_test database")

    database = f"registry_migration_{uuid4().hex}_test"
    admin_dsn = make_conninfo(configured, dbname="postgres")
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("PostgreSQL test role cannot create a fresh migration database")

    migrated_dsn = make_conninfo(configured, dbname=database)
    try:
        # This proof intentionally reproduces the unchanged V1-V11 baseline.
        # New common Rule Pack migration/read-back is exercised separately.
        migrations = [
            next(MIGRATION_ROOT.glob(f"V{version}__*.sql")) for version in range(1, 12)
        ]
        assert [_migration_number(path) for path in migrations] == list(range(1, 12))
        for migration in migrations:
            with psycopg.connect(migrated_dsn) as conn:
                conn.execute(migration.read_text(encoding="utf-8"))
        yield migrated_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                """SELECT pg_terminate_backend(pid)
                   FROM pg_stat_activity
                   WHERE datname = %s AND pid <> pg_backend_pid()""",
                (database,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_fresh_upstream_schema_accepts_c_snapshot_without_changing_b_current(
    freshly_migrated_registry_dsn: str,
) -> None:
    dsn = freshly_migrated_registry_dsn
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        before = conn.execute(
            """SELECT registry_version, status, published_at, content_sha256,
                      source_ref, imported_at
               FROM public.technology_registry
               ORDER BY registry_version"""
        ).fetchall()
        current_version = conn.execute(
            """SELECT registry_version
               FROM public.technology_registry
               WHERE status = 'CURRENT'"""
        ).fetchone()["registry_version"]
        current_rule_count = conn.execute(
            """SELECT count(*) AS count
               FROM public.evidence_rule
               WHERE registry_version = %s""",
            (current_version,),
        ).fetchone()["count"]

    assert current_version == "registry-20260910.2"
    assert current_rule_count > 0
    assert all(row["content_sha256"] is None for row in before)
    assert all(row["source_ref"] is None for row in before)
    assert all(row["imported_at"] is None for row in before)

    snapshot: TechnologyRegistry = load_registry(
        SEED_PATH, repository_root=REPOSITORY_ROOT
    ).model_copy(update={"registry_version": "registry-20260910.99"})
    store = PostgresRegistryStore(dsn)
    imported = store.import_registry(
        snapshot, source_ref="test:fresh-v11", activate_alias=True
    )

    assert store.load_registry(snapshot.registry_version) == snapshot
    assert store.resolve_version(snapshot.schema_version) == imported
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        native_after = conn.execute(
            """SELECT registry_version, status, published_at, content_sha256,
                      source_ref, imported_at
               FROM public.technology_registry
               WHERE registry_version <> %s
               ORDER BY registry_version""",
            (snapshot.registry_version,),
        ).fetchall()
        imported_lifecycle = conn.execute(
            """SELECT status, published_at
               FROM public.technology_registry
               WHERE registry_version = %s""",
            (snapshot.registry_version,),
        ).fetchone()
        imported_rule_count = conn.execute(
            """SELECT count(*) AS count
               FROM public.evidence_rule
               WHERE registry_version = %s""",
            (snapshot.registry_version,),
        ).fetchone()["count"]
        current_after = conn.execute(
            """SELECT registry_version
               FROM public.technology_registry
               WHERE status = 'CURRENT'"""
        ).fetchone()["registry_version"]
        rule_count_after = conn.execute(
            """SELECT count(*) AS count
               FROM public.evidence_rule
               WHERE registry_version = %s""",
            (current_version,),
        ).fetchone()["count"]

    assert native_after == before
    assert imported_lifecycle["status"] == "RETIRED"
    assert imported_lifecycle["published_at"] is not None
    assert imported_rule_count == 0
    assert current_after == current_version
    assert rule_count_after == current_rule_count
