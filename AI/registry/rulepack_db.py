"""Atomic immutable Registry + executable Rule Pack publication and read-back.

The C alias and B CURRENT pointer are deliberately separate activation steps.
Every read verifies the JSON hash and the normalized executable rows, so edits
to a published predicate cannot silently change the meaning of an old version.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from analysis.rulepack import load_rule_pack, parse_rule_pack
from analysis.rules import Mapping, UnknownRegistryVersion
from registry.contracts import TechnologyRegistry, load_registry
from registry.db import (
    ImmutableRegistryConflict,
    PostgresRegistryStore,
    RegistryIntegrityError,
    RegistrySnapshotRef,
)


@dataclass(frozen=True)
class PublishedRulePack:
    registry_version: str
    rule_pack_version: str
    registry_content_sha256: str
    rule_pack_content_sha256: str


def _lock_pack_tables(conn, *, for_import=False):
    mode = "SHARE ROW EXCLUSIVE" if for_import else "SHARE"
    conn.execute(
        "LOCK TABLE technology_rule_pack, technology_rule_support, evidence_rule, "
        "evidence_rule_clause, evidence_rule_predicate, evidence_rule_predicate_value "
        f"IN {mode} MODE"
    )


def _insert_pack_rows(conn, pack):
    version = pack.registry_version
    for technology in pack.technologies:
        conn.execute(
            """INSERT INTO technology_rule_support
                   (tech_id, registry_version, rule_pack_version, evaluation_scope,
                    max_supported_level, coverage, required_fact_types, limitations)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                technology.tech_id,
                version,
                pack.rule_pack_version,
                technology.evaluation_scope,
                technology.max_supported_level,
                technology.coverage,
                list(technology.required_fact_types),
                Jsonb(list(technology.limitations)),
            ),
        )
        for rule in technology.rules:
            conn.execute(
                """INSERT INTO evidence_rule
                       (rule_id, tech_id, registry_version, rule_type, language,
                        rule_name, evaluation_scope, priority, status, binding_fields)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s)""",
                (
                    rule.rule_id,
                    technology.tech_id,
                    version,
                    rule.rule_type,
                    rule.language,
                    rule.rule_id,
                    technology.evaluation_scope,
                    rule.priority,
                    list(rule.binding_fields),
                ),
            )
            for group_no, group in enumerate(rule.groups, start=1):
                for order, clause in enumerate(group, start=1):
                    clause_id = conn.execute(
                        """INSERT INTO evidence_rule_clause
                               (registry_version, rule_id, group_no, clause_key,
                                role, fact_type, min_match_count, clause_order)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           RETURNING clause_id""",
                        (
                            version,
                            rule.rule_id,
                            group_no,
                            clause.clause_key,
                            clause.role,
                            clause.fact_type,
                            clause.min_match_count,
                            order,
                        ),
                    ).fetchone()["clause_id"]
                    for predicate_order, predicate in enumerate(clause.predicates, 1):
                        predicate_id = conn.execute(
                            """INSERT INTO evidence_rule_predicate
                                   (clause_id, fact_field, match_operator,
                                    segment_delimiter, predicate_order)
                               VALUES (%s, %s, %s, %s, %s) RETURNING predicate_id""",
                            (
                                clause_id,
                                predicate.fact_field,
                                predicate.match_operator,
                                predicate.segment_delimiter,
                                predicate_order,
                            ),
                        ).fetchone()["predicate_id"]
                        for value_order, expected in enumerate(predicate.expected, 1):
                            conn.execute(
                                """INSERT INTO evidence_rule_predicate_value
                                       (predicate_id, tech_id, registry_version,
                                        expected_value, value_order)
                                   VALUES (%s, %s, %s, %s, %s)""",
                                (
                                    predicate_id,
                                    technology.tech_id,
                                    version,
                                    expected,
                                    value_order,
                                ),
                            )


def _verify_pack_rows(conn, pack):
    """Compare ordered semantic rows, ignoring generated primary keys."""
    expected_support = []
    expected_rules = []
    expected_clauses = []
    expected_predicates = []
    expected_values = []
    for technology in pack.technologies:
        expected_support.append(
            (
                technology.tech_id,
                pack.rule_pack_version,
                technology.evaluation_scope,
                technology.max_supported_level,
                technology.coverage,
                list(technology.required_fact_types),
                list(technology.limitations),
            )
        )
        for rule in technology.rules:
            expected_rules.append(
                (
                    rule.rule_id,
                    technology.tech_id,
                    rule.rule_type,
                    rule.language,
                    technology.evaluation_scope,
                    rule.priority,
                    "ACTIVE",
                    list(rule.binding_fields),
                )
            )
            for group_no, group in enumerate(rule.groups, 1):
                for clause_order, clause in enumerate(group, 1):
                    key = (rule.rule_id, group_no, clause_order)
                    expected_clauses.append(
                        (
                            *key,
                            clause.clause_key,
                            clause.role,
                            clause.fact_type,
                            clause.min_match_count,
                        )
                    )
                    for predicate_order, predicate in enumerate(clause.predicates, 1):
                        expected_predicates.append(
                            (
                                *key,
                                predicate_order,
                                predicate.fact_field,
                                predicate.match_operator,
                                predicate.segment_delimiter,
                            )
                        )
                        for value_order, expected in enumerate(predicate.expected, 1):
                            expected_values.append(
                                (
                                    *key,
                                    predicate_order,
                                    value_order,
                                    technology.tech_id,
                                    pack.registry_version,
                                    expected,
                                )
                            )
    comparisons = (
        (
            expected_support,
            """SELECT tech_id, rule_pack_version, evaluation_scope,
            max_supported_level, coverage, required_fact_types, limitations
            FROM technology_rule_support WHERE registry_version = %s""",
        ),
        (
            expected_rules,
            """SELECT rule_id, tech_id, rule_type, language, evaluation_scope,
            priority, status, binding_fields FROM evidence_rule WHERE registry_version = %s""",
        ),
        (
            expected_clauses,
            """SELECT rule_id, group_no, clause_order, clause_key, role,
            fact_type, min_match_count FROM evidence_rule_clause WHERE registry_version = %s""",
        ),
        (
            expected_predicates,
            """SELECT c.rule_id, c.group_no, c.clause_order,
            p.predicate_order, p.fact_field, p.match_operator, p.segment_delimiter
            FROM evidence_rule_predicate p JOIN evidence_rule_clause c USING (clause_id)
            WHERE c.registry_version = %s""",
        ),
        (
            expected_values,
            """SELECT c.rule_id, c.group_no, c.clause_order,
            p.predicate_order, v.value_order, v.tech_id, v.registry_version, v.expected_value
            FROM evidence_rule_predicate_value v
            JOIN evidence_rule_predicate p USING (predicate_id)
            JOIN evidence_rule_clause c USING (clause_id)
            WHERE c.registry_version = %s""",
        ),
    )
    for expected, query in comparisons:
        actual = [
            tuple(row.values())
            for row in conn.execute(query, (pack.registry_version,)).fetchall()
        ]
        # JSON is an unambiguous sortable key even for nulls and array columns.
        key = lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False)
        if sorted(actual, key=key) != sorted(expected, key=key):
            raise RegistryIntegrityError(
                "published Rule Pack executable rows differ from immutable content"
            )


def _read_pack(conn, registry_version):
    row = conn.execute(
        "SELECT content, content_sha256, rule_pack_version FROM technology_rule_pack "
        "WHERE registry_version = %s",
        (registry_version,),
    ).fetchone()
    if row is None:
        raise UnknownRegistryVersion(f"no published Rule Pack for {registry_version!r}")
    snapshot = PostgresRegistryStore._find_snapshot_ref_in(
        conn, registry_version, lock=True
    )
    registry = PostgresRegistryStore._load_registry_from_connection(conn, snapshot)
    try:
        pack = parse_rule_pack(row["content"], registry=registry)
    except ValueError as invalid:
        raise RegistryIntegrityError(
            "persisted Rule Pack content is invalid"
        ) from invalid
    if (
        pack.content_sha256 != row["content_sha256"]
        or pack.rule_pack_version != row["rule_pack_version"]
    ):
        raise RegistryIntegrityError(
            "persisted Rule Pack hash/version differs from metadata"
        )
    _verify_pack_rows(conn, pack)
    return pack, registry, snapshot


def load_published_rule_set(connection, registry_version):
    """Normal analysis RegistryStore path for an explicitly selected common version."""
    # The existing analysis loader uses tuple rows. A dedicated cursor preserves
    # its connection's row_factory and transaction ownership.
    with connection.cursor(row_factory=dict_row) as cursor:
        PostgresRegistryStore._lock_content_tables(cursor)
        _lock_pack_tables(cursor)
        pack, registry, _ = _read_pack(cursor, registry_version)
    mappings = tuple(
        Mapping(
            m.tech_id,
            m.mapping_type.value,
            m.ecosystem.value if m.ecosystem else "",
            m.value,
            m.match_mode.value,
        )
        for m in registry.mappings
        if m.status.value == "ACTIVE"
        and m.mapping_type.value in {"PACKAGE", "IMPORT_PATH"}
    )
    result = pack.as_rule_set(mappings=mappings)
    # RuleSet remains the single execution model consumed by Judge.
    from dataclasses import replace

    return replace(
        result, display_names={t.tech_id: t.display_name for t in registry.technologies}
    )


class PostgresRulePackStore(PostgresRegistryStore):
    def import_pack(
        self, registry: TechnologyRegistry, pack_path: Path, *, source_ref: str
    ):
        pack = load_rule_pack(pack_path, registry=registry)
        content = json.loads(pack_path.read_text(encoding="utf-8"))
        with self._connect() as conn:
            snapshot = self._import_registry_in(conn, registry, source_ref=source_ref)
            _lock_pack_tables(conn, for_import=True)
            inserted = conn.execute(
                """INSERT INTO technology_rule_pack
                       (rule_pack_version, registry_version, content_sha256, content, source_ref)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING RETURNING rule_pack_version""",
                (
                    pack.rule_pack_version,
                    pack.registry_version,
                    pack.content_sha256,
                    Jsonb(content),
                    source_ref,
                ),
            ).fetchone()
            if inserted is not None:
                _insert_pack_rows(conn, pack)
            else:
                existing = conn.execute(
                    "SELECT rule_pack_version, content_sha256, source_ref "
                    "FROM technology_rule_pack WHERE registry_version = %s",
                    (pack.registry_version,),
                ).fetchone()
                if (
                    existing is None
                    or existing["rule_pack_version"] != pack.rule_pack_version
                    or existing["content_sha256"] != pack.content_sha256
                    or existing["source_ref"] != source_ref
                ):
                    raise ImmutableRegistryConflict(
                        "Rule Pack version already names different content/provenance"
                    )
            _read_pack(conn, pack.registry_version)
            return self._ref(snapshot, pack)

    @staticmethod
    def _ref(snapshot: RegistrySnapshotRef, pack):
        return PublishedRulePack(
            snapshot.registry_version,
            pack.rule_pack_version,
            snapshot.content_sha256,
            pack.content_sha256,
        )

    def load_pack(self, registry_version):
        with self._connect() as conn:
            self._lock_content_tables(conn)
            _lock_pack_tables(conn)
            pack, _, _ = _read_pack(conn, registry_version)
        return pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--rule-pack", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    registry = load_registry(args.registry, repository_root=args.repository_root)
    # Credentials stay in the process environment, never CLI arguments or logs.
    result = PostgresRulePackStore(os.environ["REGISTRY_DATABASE_URL"]).import_pack(
        registry,
        args.rule_pack,
        source_ref=args.source_ref,
    )
    print(json.dumps(result.__dict__, sort_keys=True))


if __name__ == "__main__":
    main()
