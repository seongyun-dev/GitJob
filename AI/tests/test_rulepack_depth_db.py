"""Publish structural rules beside .2 without rewriting historical rows."""

from pathlib import Path

import psycopg
import pytest
from test_rulepack_db import legacy_state, migrate, publish
from test_rulepack_db import (
    rulepack_dsn as rulepack_dsn,  # noqa: PLC0414 -- pytest fixture re-export
)

from analysis.rules import UnknownRegistryVersion, load_rule_set
from registry.contracts import load_registry
from registry.db import RegistryIntegrityError
from registry.rulepack_db import PostgresRulePackStore

AI_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    AI_ROOT.parent
    / "BE/src/main/resources/db/migration/V11_2__rule_pack_structural_evidence.sql"
)
REGISTRY = AI_ROOT / "registry/data/technology_registry_20260911_3.json"
PACK = AI_ROOT / "analysis/data/rule_pack_20260911_3.json"


def test_depth_publication_preserves_old_rules_and_roundtrips_new_fields(rulepack_dsn):
    migrate(rulepack_dsn)
    publish(rulepack_dsn)
    store = PostgresRulePackStore(rulepack_dsn)
    before = store.load_pack("registry-20260911.2")
    with psycopg.connect(rulepack_dsn) as conn:
        legacy = legacy_state(conn)
        conn.execute(MIGRATION.read_text("utf-8"))
    registry = load_registry(REGISTRY, repository_root=AI_ROOT.parent)
    imported = store.import_pack(registry, PACK, source_ref="test:depth-v3")
    assert store.import_pack(registry, PACK, source_ref="test:depth-v3") == imported
    assert store.load_pack("registry-20260911.2") == before
    with psycopg.connect(rulepack_dsn) as conn:
        current = load_rule_set(conn, "registry-20260911.3")
        old_versions, old_rules = legacy
        assert load_rule_set(conn, "registry-20260910.2") == old_rules
        assert (
            conn.execute(
                "SELECT registry_version, status FROM technology_registry WHERE registry_version <> 'registry-20260911.3' ORDER BY 1"
            ).fetchall()
            == old_versions
        )
        assert any(
            c.fact_type == "SYNTAX_NODE" for r in current.rules for c in r.clauses
        )
        assert any("COMPONENT" in r.binding_fields for r in current.rules)
        with pytest.raises(UnknownRegistryVersion):
            load_rule_set(conn, "registry-unknown-depth")


def test_structural_predicate_tamper_fails_closed(rulepack_dsn):
    migrate(rulepack_dsn)
    with psycopg.connect(rulepack_dsn) as conn:
        conn.execute(MIGRATION.read_text("utf-8"))
    store = PostgresRulePackStore(rulepack_dsn)
    store.import_pack(
        load_registry(REGISTRY, repository_root=AI_ROOT.parent),
        PACK,
        source_ref="test:depth-v3",
    )
    with psycopg.connect(rulepack_dsn) as conn:
        conn.execute(
            "UPDATE evidence_rule_predicate SET fact_field = 'NAME' WHERE fact_field = 'KIND'"
        )
    with pytest.raises(RegistryIntegrityError):
        store.load_pack("registry-20260911.3")
