"""The registry as the worker reads it: mappings, rules, and how to load them.

The database is the source of truth. `AI/registry/data/*.json` is C's input for
job-demand analysis and holds different content; reading it here would judge
repositories against a registry nobody curated for that purpose.

### Why a reader, not a second writer

`claim.py` explains why the worker does not write `analysis_job`. Reading is a
different matter: a reader does not constrain the schema's owner. The worker
therefore queries the registry tables directly and publishes its findings back
over the results topic.

### Why a version is loaded whole and then cached

`registry_version` is part of the primary key of every content table, so one
version's content cannot change. That removes the usual cache problem: there is
nothing to invalidate. A version is read once, indexed, and kept.

Loading per fact would be the alternative, and it is the wrong shape: a
repository produces hundreds of facts and the whole registry is a few thousand
rows.

### An unknown version must not be quiet

Selecting rules for a version that does not exist returns no rows, and no rows
evaluates to "no technology matched" — which is exactly what a repository using
nothing looks like. `UnknownRegistryVersion` exists so that failure is loud.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

__all__ = [
    "Clause",
    "Mapping",
    "Predicate",
    "RegistryStore",
    "Rule",
    "RuleSet",
    "UnknownRegistryVersion",
]

log = logging.getLogger("analysis.rules")


class UnknownRegistryVersion(LookupError):
    """The requested registry version has no content. Never treat as empty."""


@dataclass(frozen=True)
class Mapping:
    """One way a fact is recognised as a technology."""

    tech_id: str
    mapping_type: str  # IMPORT_PATH | PACKAGE
    ecosystem: str
    value: str
    match_mode: str  # EXACT | PREFIX


@dataclass(frozen=True)
class Predicate:
    """One condition on one field of a fact. Expected values are OR-ed."""

    fact_field: str
    match_operator: str
    segment_delimiter: str | None
    expected: tuple[str, ...]


@dataclass(frozen=True)
class Clause:
    """A condition that some number of facts must satisfy together."""

    clause_id: int
    group_no: int
    clause_key: str
    role: str  # REQUIRED | OPTIONAL
    fact_type: str
    min_match_count: int
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True)
class Rule:
    """One reason to assign one level to one technology."""

    rule_id: str
    tech_id: str
    rule_type: str  # L0 | L1 | L2 | L3
    language: str | None
    evaluation_scope: str  # REPOSITORY | PERSONAL
    priority: int
    clauses: tuple[Clause, ...]
    #: Required clauses must agree on these fact fields. FILE_PATH prevents a
    #: library import in one file from lending identity to an unrelated common
    #: method call in another file.
    binding_fields: tuple[str, ...] = ()

    def groups(self) -> dict[int, tuple[Clause, ...]]:
        """Clauses by `group_no`. Groups are alternatives; within one, AND."""
        grouped: dict[int, list[Clause]] = defaultdict(list)
        for clause in self.clauses:
            grouped[clause.group_no].append(clause)
        return {number: tuple(items) for number, items in sorted(grouped.items())}


@dataclass(frozen=True)
class RuleSet:
    """Everything one registry version says. Immutable, like the version."""

    registry_version: str
    mappings: tuple[Mapping, ...]
    rules: tuple[Rule, ...]
    display_names: dict[str, str] = field(default_factory=dict)
    rule_pack_version: str | None = None
    rule_pack_content_sha256: str | None = None
    technology_support: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mappings and not self.rules:
            raise UnknownRegistryVersion(
                f"registry {self.registry_version!r} has no mappings and no rules"
            )


_MAPPINGS_SQL = """
    SELECT tech_id, mapping_type, ecosystem, value, match_mode
    FROM technology_mapping
    WHERE registry_version = %s
      AND status = 'ACTIVE'
      AND mapping_type IN ('IMPORT_PATH', 'PACKAGE')
    ORDER BY tech_id, mapping_type, value
"""

_RULES_SQL = """
    SELECT rule_id, tech_id, rule_type, language, evaluation_scope, priority
    FROM evidence_rule
    WHERE registry_version = %s AND status = 'ACTIVE'
    ORDER BY tech_id, priority, rule_id
"""

_CLAUSES_SQL = """
    SELECT clause_id, rule_id, group_no, clause_key, role, fact_type, min_match_count
    FROM evidence_rule_clause
    WHERE registry_version = %s
    ORDER BY rule_id, group_no, clause_order, clause_id
"""

# One row per predicate, with its expected values already gathered. Doing this
# in SQL keeps the assembly below linear instead of a lookup per predicate.
_PREDICATES_SQL = """
    SELECT p.clause_id,
           p.fact_field,
           p.match_operator,
           p.segment_delimiter,
           array_agg(v.expected_value ORDER BY v.value_order, v.predicate_value_id)
    FROM evidence_rule_predicate p
    JOIN evidence_rule_predicate_value v ON v.predicate_id = p.predicate_id
    JOIN evidence_rule_clause c ON c.clause_id = p.clause_id
    WHERE c.registry_version = %s AND v.registry_version = %s
    GROUP BY p.predicate_id, p.clause_id, p.fact_field, p.match_operator,
             p.segment_delimiter, p.predicate_order
    ORDER BY p.clause_id, p.predicate_order, p.predicate_id
"""

_TECHNOLOGIES_SQL = """
    SELECT tech_id, display_name
    FROM technology
    WHERE registry_version = %s AND status = 'ACTIVE'
"""


def load_rule_set(connection, registry_version: str) -> RuleSet:
    """Read one version out of an open DB-API connection.

    Takes a connection rather than a DSN so the caller owns pooling, and so a
    test can hand in anything with `execute`.
    """
    if registry_version in {
        "registry-20260911.2",
        "registry-20260911.3",
        "registry-20260911.4",
    }:
        from registry.rulepack_db import load_published_rule_set

        return load_published_rule_set(connection, registry_version)

    mappings = tuple(
        Mapping(*row)
        for row in connection.execute(_MAPPINGS_SQL, (registry_version,)).fetchall()
    )
    display_names = dict(
        connection.execute(_TECHNOLOGIES_SQL, (registry_version,)).fetchall()
    )

    predicates_by_clause: dict[int, list[Predicate]] = defaultdict(list)
    for clause_id, fact_field, operator, delimiter, expected in connection.execute(
        _PREDICATES_SQL, (registry_version, registry_version)
    ).fetchall():
        predicates_by_clause[clause_id].append(
            Predicate(fact_field, operator, delimiter, tuple(expected))
        )

    clauses_by_rule: dict[str, list[Clause]] = defaultdict(list)
    for (
        clause_id,
        rule_id,
        group_no,
        clause_key,
        role,
        fact_type,
        min_match_count,
    ) in connection.execute(_CLAUSES_SQL, (registry_version,)).fetchall():
        predicates = tuple(predicates_by_clause.get(clause_id, ()))
        if not predicates:
            # A clause with no predicate places no condition, so every fact of
            # its type satisfies it. That is never what someone meant to write.
            log.warning(
                "clause %s of rule %s has no predicate and is ignored",
                clause_id,
                rule_id,
            )
            continue
        clauses_by_rule[rule_id].append(
            Clause(
                clause_id=clause_id,
                group_no=group_no,
                clause_key=clause_key,
                role=role,
                fact_type=fact_type,
                min_match_count=min_match_count,
                predicates=predicates,
            )
        )

    rules = []
    for rule_id, tech_id, rule_type, language, scope, priority in connection.execute(
        _RULES_SQL, (registry_version,)
    ).fetchall():
        clauses = tuple(clauses_by_rule.get(rule_id, ()))
        if not clauses:
            # Same reasoning: a rule with no clause would match everything.
            log.warning("rule %s has no usable clause and is ignored", rule_id)
            continue
        rules.append(
            Rule(
                rule_id=rule_id,
                tech_id=tech_id,
                rule_type=rule_type,
                language=language,
                evaluation_scope=scope,
                priority=priority,
                clauses=clauses,
            )
        )

    return RuleSet(
        registry_version=registry_version,
        mappings=mappings,
        rules=tuple(rules),
        display_names=display_names,
    )


@dataclass
class RegistryStore:
    """Loads a version once and keeps it.

    Bounded because a deployment briefly overlaps two versions: events produced
    before the switch still name the old one. Beyond that overlap, holding more
    would only pin memory to versions nobody asks for again.
    """

    connect: object  # callable returning a DB-API connection
    max_cached_versions: int = 2
    _cache: dict[str, RuleSet] = field(default_factory=dict, init=False, repr=False)

    def load(self, registry_version: str) -> RuleSet:
        cached = self._cache.get(registry_version)
        if cached is not None:
            return cached
        with self.connect() as connection:  # type: ignore[operator]
            rule_set = load_rule_set(connection, registry_version)
        if len(self._cache) >= self.max_cached_versions:
            self._cache.pop(next(iter(self._cache)))
        self._cache[registry_version] = rule_set
        log.info(
            "loaded registry %s: %s mappings, %s rules",
            registry_version,
            len(rule_set.mappings),
            len(rule_set.rules),
        )
        return rule_set
