"""Publish callable-scoped .4 rules without changing stored .2/.3 packs."""

from pathlib import Path

import psycopg
import pytest
from test_rulepack_db import migrate, publish
from test_rulepack_db import (
    rulepack_dsn as rulepack_dsn,  # noqa: PLC0414 -- pytest fixture re-export
)

from analysis.rulepack import SCOPE_REGISTRY_PATH, SCOPE_RULE_PACK_PATH
from analysis.rules import load_rule_set
from registry.contracts import load_registry
from registry.rulepack_db import PostgresRulePackStore

AI_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = AI_ROOT.parent / "BE/src/main/resources/db/migration"
DEPTH_REGISTRY = AI_ROOT / "registry/data/technology_registry_20260911_3.json"
DEPTH_PACK = AI_ROOT / "analysis/data/rule_pack_20260911_3.json"


def test_scope_publication_preserves_depth_pack_and_roundtrips_function_binding(
    rulepack_dsn,
):
    migrate(rulepack_dsn)
    publish(rulepack_dsn)
    store = PostgresRulePackStore(rulepack_dsn)
    common_before = store.load_pack("registry-20260911.2")
    with psycopg.connect(rulepack_dsn) as conn:
        conn.execute(
            (MIGRATIONS / "V11_2__rule_pack_structural_evidence.sql").read_text("utf-8")
        )
    store.import_pack(
        load_registry(DEPTH_REGISTRY, repository_root=AI_ROOT.parent),
        DEPTH_PACK,
        source_ref="test:depth-v3",
    )
    depth_before = store.load_pack("registry-20260911.3")

    with psycopg.connect(rulepack_dsn) as conn:
        conn.execute(
            (MIGRATIONS / "V11_3__rule_pack_function_scope.sql").read_text("utf-8")
        )
    imported = store.import_pack(
        load_registry(SCOPE_REGISTRY_PATH, repository_root=AI_ROOT.parent),
        SCOPE_RULE_PACK_PATH,
        source_ref="test:scope-v4",
    )

    assert imported.registry_version == "registry-20260911.4"
    assert (
        store.import_pack(
            load_registry(SCOPE_REGISTRY_PATH, repository_root=AI_ROOT.parent),
            SCOPE_RULE_PACK_PATH,
            source_ref="test:scope-v4",
        )
        == imported
    )
    assert store.load_pack("registry-20260911.2") == common_before
    assert store.load_pack("registry-20260911.3") == depth_before
    with psycopg.connect(rulepack_dsn) as conn:
        scope = load_rule_set(conn, "registry-20260911.4")
    kafka_l3 = next(
        rule
        for rule in scope.rules
        if rule.rule_id == "apache-kafka.l3.transactional-consumer"
    )
    assert kafka_l3.binding_fields == ("FILE_PATH", "FUNCTION")


def test_scope_rule_failure_rolls_back_registry(rulepack_dsn):
    migrate(rulepack_dsn)
    with psycopg.connect(rulepack_dsn) as conn:
        conn.execute(
            (MIGRATIONS / "V11_2__rule_pack_structural_evidence.sql").read_text("utf-8")
        )
        conn.execute(
            (MIGRATIONS / "V11_3__rule_pack_function_scope.sql").read_text("utf-8")
        )
        conn.execute(
            "ALTER TABLE evidence_rule ADD CONSTRAINT test_refuse_scope "
            "CHECK (registry_version <> 'registry-20260911.4')"
        )
    store = PostgresRulePackStore(rulepack_dsn)

    with pytest.raises(psycopg.errors.CheckViolation):
        store.import_pack(
            load_registry(SCOPE_REGISTRY_PATH, repository_root=AI_ROOT.parent),
            SCOPE_RULE_PACK_PATH,
            source_ref="test:scope-v4",
        )

    with psycopg.connect(rulepack_dsn) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM technology_registry WHERE registry_version = %s",
                ("registry-20260911.4",),
            ).fetchone()[0]
            == 0
        )
