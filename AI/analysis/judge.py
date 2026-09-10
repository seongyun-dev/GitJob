"""Turn facts into technology verdicts.

Two stages, and keeping them apart is the whole design (V6, V7).

    resolve   fact ──mapping──▶ tech_id     "무슨 기술인가"
    evaluate  fact ──rule────▶ L0..L3       "어느 수준인가"

Mappings own the prefix lists. A rule that restated them meant adding a Redis
client library had to be done twice, and forgetting one half was silent. So a
generic rule now says only "an IMPORT fact resolved to redis", and the specific
ones — `org.springframework.boot.actuate` — say what a mapping cannot.

### Why a fact may resolve to several technologies

`org.springframework.boot:spring-boot-starter-data-jpa` matches the spring-boot
prefix and the spring-data-jpa coordinate. Both are true: it evidences Spring
Boot and it evidences Spring Data JPA. Picking the more specific one would
discard a fact that holds.

### What an unmatched fact means

An unmatched dependency is a candidate: something declared often enough that an
administrator may want it in the registry. An unmatched import is not. Its
granularity is a class path, and no truncation recovers the package boundary —
`org.springframework.web` is three segments, `org.springframework.data.redis`
is four. Only dependencies become candidates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from analysis.manifests import DependencyOccurrence
from analysis.parse import CallOccurrence, ImportOccurrence
from analysis.rules import Clause, Predicate, Rule, RuleSet
from registry.normalization import (
    import_path_has_prefix,
    normalize_mapping_value,
    package_has_prefix,
)

__all__ = [
    "Candidate",
    "EvidenceFact",
    "Fact",
    "Judge",
    "Judgement",
    "Verdict",
    "facts_from_calls",
    "facts_from_dependencies",
    "facts_from_imports",
]

log = logging.getLogger("analysis.judge")

#: tree-sitter language name -> the registry's ImportEcosystem.
_IMPORT_ECOSYSTEMS = {
    "java": "JAVA",
    "python": "PYTHON",
    "javascript": "JAVASCRIPT",
    "typescript": "JAVASCRIPT",
    "tsx": "JAVASCRIPT",
    "csharp": "DOTNET",
}

_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


@dataclass(frozen=True)
class Fact:
    """One observation, in the shape rules read.

    `fields` is keyed by the registry's `fact_field` vocabulary so a predicate
    can name what it looks at without this module knowing which rule exists.
    `tech_ids` is filled by resolution and is the field `TECH_ID` reads.
    """

    fact_type: str  # IMPORT | DEPENDENCY
    fields: dict[str, str]
    file: str
    line: int
    tech_ids: frozenset[str] = frozenset()

    def resolved(self, tech_ids: frozenset[str]) -> Fact:
        return Fact(self.fact_type, self.fields, self.file, self.line, tech_ids)


@dataclass(frozen=True)
class EvidenceFact:
    """A fact that supported a rule. One row of `analysis_evidence`."""

    rule_id: str
    tech_id: str
    fact: Fact


@dataclass(frozen=True)
class Verdict:
    tech_id: str
    level: str
    matched_rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """A declared dependency that matched nothing in the registry."""

    ecosystem: str
    coordinate: str
    scope: str | None
    occurrence_count: int


@dataclass(frozen=True)
class Judgement:
    verdicts: tuple[Verdict, ...]
    evidence: tuple[EvidenceFact, ...]
    candidates: tuple[Candidate, ...]
    #: Rules skipped because this worker cannot evaluate them yet. Reported so
    #: a missing level is visibly unimplemented rather than apparently absent.
    skipped_rule_ids: tuple[str, ...] = ()


def facts_from_imports(occurrences: Iterable[ImportOccurrence]) -> tuple[Fact, ...]:
    return tuple(
        Fact(
            fact_type="IMPORT",
            fields={
                "MODULE": item.module,
                "LANGUAGE": item.language,
                "ECOSYSTEM": item.ecosystem,
                "FILE_PATH": item.file,
            },
            file=item.file,
            line=item.line,
        )
        for item in occurrences
    )


def facts_from_dependencies(
    occurrences: Iterable[DependencyOccurrence],
) -> tuple[Fact, ...]:
    return tuple(
        Fact(
            fact_type="DEPENDENCY",
            fields={
                "COORDINATE": item.coordinate,
                "ECOSYSTEM": item.ecosystem,
                "SCOPE": item.scope or "",
                "FILE_PATH": item.file,
            },
            file=item.file,
            line=item.line,
        )
        for item in occurrences
    )


def facts_from_calls(occurrences: Iterable[CallOccurrence]) -> tuple[Fact, ...]:
    """Calls, for the rules that ask what the code does rather than what it imports.

    Nothing is resolved. `CALL` is the callee as written and `METHOD` its last
    segment, so a rule picks whichever is distinctive enough: `useState` needs
    no receiver, `SpringApplication.run` does.
    """
    return tuple(
        Fact(
            fact_type="API_CALL",
            fields={
                "CALL": item.callee,
                "METHOD": item.method,
                "RECEIVER": item.receiver or "",
                "LANGUAGE": item.language,
                "ECOSYSTEM": item.ecosystem,
                "FILE_PATH": item.file,
            },
            file=item.file,
            line=item.line,
        )
        for item in occurrences
    )


@dataclass
class Judge:
    """Resolves and evaluates one repository's facts against one registry version."""

    rule_set: RuleSet
    #: Per rule, because one rule can be supported by hundreds of identical
    #: imports. The cap is on evidence, not on the verdict: matching is decided
    #: before anything is dropped.
    max_evidence_per_rule: int = 20
    _exact: dict[tuple[str, str, str], set[str]] = field(
        default_factory=dict, init=False, repr=False
    )
    _prefix: dict[tuple[str, str], list[tuple[str, str]]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for mapping in self.rule_set.mappings:
            key = (mapping.mapping_type, mapping.ecosystem)
            if mapping.match_mode == "EXACT":
                try:
                    value = normalize_mapping_value(
                        mapping.mapping_type, mapping.ecosystem, mapping.value
                    )
                except ValueError as invalid:
                    log.warning("ignoring mapping %s: %s", mapping.value, invalid)
                    continue
                self._exact.setdefault((*key, value), set()).add(mapping.tech_id)
            else:
                self._prefix.setdefault(key, []).append(
                    (mapping.value, mapping.tech_id)
                )

    # -- resolution ---------------------------------------------------------

    def resolve(self, fact: Fact) -> frozenset[str]:
        if fact.fact_type == "IMPORT":
            kind, value = "IMPORT_PATH", fact.fields.get("MODULE", "")
            ecosystem = _IMPORT_ECOSYSTEMS.get(fact.fields.get("LANGUAGE", ""))
        elif fact.fact_type == "DEPENDENCY":
            kind, value = "PACKAGE", fact.fields.get("COORDINATE", "")
            ecosystem = fact.fields.get("ECOSYSTEM")
        else:
            return frozenset()
        if not value or not ecosystem:
            return frozenset()

        try:
            normalized = normalize_mapping_value(kind, ecosystem, value)
        except ValueError:
            # A coordinate the registry's own rules call malformed. It cannot
            # match anything, and it is not a candidate either.
            return frozenset()

        found = set(self._exact.get((kind, ecosystem, normalized), ()))
        matches = (
            import_path_has_prefix if kind == "IMPORT_PATH" else package_has_prefix
        )
        for prefix, tech_id in self._prefix.get((kind, ecosystem), ()):
            if tech_id in found:
                continue
            try:
                if matches(prefix, value, ecosystem):
                    found.add(tech_id)
            except ValueError as invalid:
                # PREFIX on a flat namespace, for one. Loud in the log rather
                # than a mapping that silently never fires.
                log.warning("unusable prefix mapping %r: %s", prefix, invalid)
        return frozenset(found)

    # -- evaluation ---------------------------------------------------------

    def judge(self, facts: Iterable[Fact]) -> Judgement:
        resolved = tuple(fact.resolved(self.resolve(fact)) for fact in facts)

        matched: dict[str, list[Rule]] = defaultdict(list)
        evidence: list[EvidenceFact] = []
        skipped: list[str] = []

        for rule in self.rule_set.rules:
            if rule.evaluation_scope != "REPOSITORY":
                # PERSONAL needs commit authorship, and `--depth 1` has no
                # history. Reported rather than dropped: an unimplemented level
                # and an unmet one look the same from the outside.
                skipped.append(rule.rule_id)
                continue
            supporting = self._match(rule, resolved)
            if supporting is None:
                continue
            matched[rule.tech_id].append(rule)
            for fact in supporting[: self.max_evidence_per_rule]:
                evidence.append(EvidenceFact(rule.rule_id, rule.tech_id, fact))

        verdicts = tuple(
            Verdict(
                tech_id=tech_id,
                level=max(
                    (rule.rule_type for rule in rules), key=lambda t: _LEVEL_ORDER[t]
                ),
                matched_rule_ids=tuple(rule.rule_id for rule in rules),
            )
            for tech_id, rules in sorted(matched.items())
        )
        return Judgement(
            verdicts=verdicts,
            evidence=tuple(evidence),
            candidates=self._candidates(resolved),
            skipped_rule_ids=tuple(skipped),
        )

    def _match(self, rule: Rule, facts: tuple[Fact, ...]) -> list[Fact] | None:
        """Facts supporting `rule`, or `None` when no group is satisfied."""
        applicable = [
            fact
            for fact in facts
            if rule.language is None
            or _IMPORT_ECOSYSTEMS.get(fact.fields.get("LANGUAGE", ""))
            == rule.language
            or fact.fields.get("ECOSYSTEM") == rule.language
        ]
        for clauses in rule.groups().values():
            supporting: list[Fact] = []
            satisfied = True
            for clause in clauses:
                hits = self._clause_hits(clause, applicable)
                if len(hits) < clause.min_match_count:
                    if clause.role == "REQUIRED":
                        satisfied = False
                        break
                    continue
                supporting.extend(hits)
            if satisfied:
                return supporting
        return None

    def _clause_hits(self, clause: Clause, facts: list[Fact]) -> list[Fact]:
        return [
            fact
            for fact in facts
            if fact.fact_type == clause.fact_type
            and all(_predicate_holds(predicate, fact) for predicate in clause.predicates)
        ]

    def _candidates(self, facts: tuple[Fact, ...]) -> tuple[Candidate, ...]:
        """Group by what the administrator promotes: ecosystem and coordinate.

        Scope is deliberately not part of the key. spring-petclinic ships both a
        pom.xml and a build.gradle, so `com.h2database:h2` is declared as
        `runtime` in one and `runtimeOnly` in the other -- keying on scope split
        one candidate into two, and the admin screen would rank halves.

        The scope is still reported, but only when every declaration agrees.
        Disagreement is what `None` means here: a library that is production in
        one module and test-only in another has no single answer, and inventing
        one would later be read as fact.
        """
        counts: dict[tuple[str, str], int] = defaultdict(int)
        scopes: dict[tuple[str, str], set[str | None]] = defaultdict(set)
        for fact in facts:
            if fact.fact_type != "DEPENDENCY" or fact.tech_ids:
                continue
            key = (
                fact.fields.get("ECOSYSTEM", ""),
                fact.fields.get("COORDINATE", ""),
            )
            counts[key] += 1
            scopes[key].add(fact.fields.get("SCOPE") or None)
        return tuple(
            Candidate(
                ecosystem=ecosystem,
                coordinate=coordinate,
                scope=next(iter(scopes[key])) if len(scopes[key]) == 1 else None,
                occurrence_count=count,
            )
            for key, count in sorted(counts.items())
            for ecosystem, coordinate in (key,)
        )


def _predicate_holds(predicate: Predicate, fact: Fact) -> bool:
    if predicate.fact_field == "TECH_ID":
        # Derived by resolution rather than read off the fact. A fact that maps
        # to several technologies satisfies the predicate if any of them match.
        values: Iterable[str] = fact.tech_ids
    else:
        value = fact.fields.get(predicate.fact_field)
        if value is None:
            return False
        values = (value,)
    return any(
        _operator_holds(predicate, value, expected)
        for value in values
        for expected in predicate.expected
    )


def _operator_holds(predicate: Predicate, value: str, expected: str) -> bool:
    operator = predicate.match_operator
    if operator == "EXACT":
        return value == expected
    if operator == "PREFIX":
        delimiter = predicate.segment_delimiter
        if delimiter:
            # Without this `org.springframework` also matches
            # `org.springframeworkfoo`, which is a different project.
            return value == expected or value.startswith(expected + delimiter)
        return value.startswith(expected)
    if operator == "SUFFIX":
        return value.endswith(expected)
    if operator == "CONTAINS":
        return expected in value
    log.warning("unknown match_operator %r", operator)
    return False
