"""Publish a common Rule Pack beside legacy B data in an isolated database."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from analysis.rules import UnknownRegistryVersion, load_rule_set
from registry.contracts import load_registry
from registry.db import (
    ImmutableRegistryConflict,
    PostgresRegistryStore,
    RegistryIntegrityError,
)
from registry.rulepack_db import PostgresRulePackStore

AI_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = AI_ROOT.parent / "BE/src/main/resources/db/migration"
REGISTRY_PATH = AI_ROOT / "registry/data/technology_registry_20260911_2.json"
PACK_PATH = AI_ROOT / "analysis/data/rule_pack_20260911_2.json"
VERSION = "registry-20260911.2"


@pytest.fixture
def rulepack_dsn():
    configured = os.getenv("REGISTRY_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("Set REGISTRY_TEST_DATABASE_URL to an isolated PostgreSQL server")
    if not conninfo_to_dict(configured).get("dbname", "").endswith("_test"):
        pytest.fail("Registry tests require a dedicated *_test database")
    name = f"common_rulepack_{uuid4().hex}_test"
    admin_dsn = make_conninfo(configured, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(configured, dbname=name)
    try:
        # Real, unchanged V1-V11 artifacts establish the legacy baseline first.
        for version in range(1, 12):
            (path,) = MIGRATIONS.glob(f"V{version}__*.sql")
            with psycopg.connect(dsn) as conn:
                conn.execute(path.read_text(encoding="utf-8"))
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def migrate(dsn):
    with psycopg.connect(dsn) as conn:
        conn.execute((MIGRATIONS / "V11_1__common_rule_pack.sql").read_text("utf-8"))


def legacy_state(conn):
    return (
        conn.execute(
            "SELECT registry_version, status FROM technology_registry ORDER BY 1"
        ).fetchall(),
        load_rule_set(conn, "registry-20260910.2"),
    )


def publish(dsn, *, source_ref="test:common44"):
    registry = load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    return PostgresRulePackStore(dsn).import_pack(
        registry, PACK_PATH, source_ref=source_ref
    )


def test_atomic_publication_readback_legacy_and_unknown_version(rulepack_dsn):
    dsn = rulepack_dsn
    with psycopg.connect(dsn) as conn:
        legacy_versions, old_rules = legacy_state(conn)
    migrate(dsn)
    published = publish(dsn)
    assert published.registry_version == VERSION
    assert publish(dsn) == published  # Exact retry is idempotent.
    store = PostgresRulePackStore(dsn)
    pack = store.load_pack(VERSION)
    assert len(pack.technologies) == 44
    with psycopg.connect(dsn) as conn:
        assert load_rule_set(conn, "registry-20260910.2") == old_rules
        assert (
            conn.execute(
                "SELECT registry_version, status FROM technology_registry "
                "WHERE registry_version <> %s ORDER BY 1",
                (VERSION,),
            ).fetchall()
            == legacy_versions
        )
        assert (
            conn.execute("SELECT count(*) FROM technology_registry_alias").fetchone()[0]
            == 0
        )
        current = load_rule_set(conn, VERSION)
        assert {rule.tech_id for rule in current.rules} <= {
            t.tech_id for t in pack.technologies
        }
        assert current.rules
        assert any(rule.binding_fields == ("FILE_PATH",) for rule in current.rules)
        with pytest.raises(UnknownRegistryVersion):
            load_rule_set(conn, "registry-20991231.99")


def test_rule_pack_can_pair_with_a_preexisting_registry_provenance(rulepack_dsn):
    dsn = rulepack_dsn
    migrate(dsn)
    registry = load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    PostgresRegistryStore(dsn).import_registry(
        registry,
        source_ref="manual:registry-reviewed-commit",
    )

    store = PostgresRulePackStore(dsn)
    published = store.import_pack(
        registry,
        PACK_PATH,
        source_ref="release:rule-pack-reviewed-commit",
        registry_source_ref="manual:registry-reviewed-commit",
    )

    assert published.registry_version == VERSION
    assert store.load_pack(VERSION).rule_pack_version == "rule-pack-20260911.2"
    with psycopg.connect(dsn) as conn:
        assert (
            conn.execute(
                "SELECT source_ref FROM technology_registry WHERE registry_version = %s",
                (VERSION,),
            ).fetchone()[0]
            == "manual:registry-reviewed-commit"
        )
        assert (
            conn.execute(
                "SELECT source_ref FROM technology_rule_pack WHERE registry_version = %s",
                (VERSION,),
            ).fetchone()[0]
            == "release:rule-pack-reviewed-commit"
        )


def test_conflict_and_tampering_fail_closed(rulepack_dsn):
    dsn = rulepack_dsn
    migrate(dsn)
    publish(dsn)
    with pytest.raises(ImmutableRegistryConflict):
        publish(dsn, source_ref="test:different-source")
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE evidence_rule SET priority = priority + 1 WHERE registry_version = %s",
            (VERSION,),
        )
    with pytest.raises(RegistryIntegrityError):
        PostgresRulePackStore(dsn).load_pack(VERSION)
    with psycopg.connect(dsn) as conn, pytest.raises(RegistryIntegrityError):
        load_rule_set(conn, VERSION)


def test_failed_rule_insert_rolls_back_registry_too(rulepack_dsn):
    dsn = rulepack_dsn
    migrate(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "ALTER TABLE evidence_rule ADD CONSTRAINT test_refuse_new_version "
            "CHECK (registry_version <> 'registry-20260911.2')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        publish(dsn)
    with psycopg.connect(dsn) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM technology_registry WHERE registry_version = %s",
                (VERSION,),
            ).fetchone()[0]
            == 0
        )
