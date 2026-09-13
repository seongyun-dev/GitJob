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

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from hashlib import sha256

from analysis.manifests import DependencyOccurrence
from analysis.parse import (
    AnnotationOccurrence,
    CallOccurrence,
    ImportOccurrence,
    SourceFileOccurrence,
    SyntaxOccurrence,
)
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
    "fact_matches_clause",
    "facts_from_annotations",
    "facts_from_calls",
    "facts_from_dependencies",
    "facts_from_imports",
    "facts_from_sources",
    "facts_from_syntax",
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

    @property
    def fact_id(self) -> str:
        """Stable identity for the exact Rule Pack fact consumed downstream."""

        canonical = json.dumps(
            {
                "rule_id": self.rule_id,
                "tech_id": self.tech_id,
                "fact_type": self.fact.fact_type,
                "fields": self.fact.fields,
                "file": self.fact.file,
                "line": self.fact.line,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "fact_" + sha256(canonical.encode("utf-8")).hexdigest()


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
    rule_pack_version: str | None = None
    rule_pack_content_sha256: str | None = None
    technology_support: dict[str, object] = field(default_factory=dict)
    matched_rule_groups: dict[str, int] = field(default_factory=dict)
    #: Full matched evidence retained in-process for personal attribution. The
    #: public evidence tuple above remains display-capped for v1-v4 payloads.
    personal_evidence: tuple[EvidenceFact, ...] = ()


def facts_from_imports(occurrences: Iterable[ImportOccurrence]) -> tuple[Fact, ...]:
    return tuple(
        Fact(
            fact_type="IMPORT",
            fields={
                "MODULE": item.module,
                "LANGUAGE": item.language,
                "ECOSYSTEM": item.ecosystem,
                "FILE_PATH": item.file,
                "IS_TEST": str(_is_test_path(item.file)).lower(),
                "LOCAL_NAMES": "|".join(item.bindings),
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
                "IS_TEST": str(_dependency_is_test(item.scope, item.file)).lower(),
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
    facts: list[Fact] = []
    for item in occurrences:
        fields = {
            "CALL": item.callee,
            "METHOD": item.method,
            "RECEIVER": item.receiver or "",
            "LANGUAGE": item.language,
            "ECOSYSTEM": item.ecosystem,
            "FILE_PATH": item.file,
            "IS_TEST": str(_is_test_path(item.file)).lower(),
        }
        if item.shadowed_bindings:
            fields["SHADOWED_NAMES"] = "|".join(item.shadowed_bindings)
        if item.resolved_binding:
            fields["RESOLVED_LOCAL_NAME"] = item.resolved_binding
        if item.component:
            fields["COMPONENT"] = item.component
        if item.function:
            fields["FUNCTION"] = item.function
        facts.append(
            Fact(
                fact_type="API_CALL",
                fields=fields,
                file=item.file,
                line=item.line,
            )
        )
    return tuple(facts)


def facts_from_sources(occurrences: Iterable[SourceFileOccurrence]) -> tuple[Fact, ...]:
    return tuple(
        Fact(
            fact_type="SOURCE_FILE",
            fields={
                "FILE_PATH": item.file,
                "LANGUAGE": item.language,
                "EXTENSION": item.extension,
                "SLOC": str(item.sloc),
                "IS_TEST": str(item.is_test).lower(),
            },
            file=item.file,
            line=item.line,
        )
        for item in occurrences
    )


def facts_from_annotations(
    occurrences: Iterable[AnnotationOccurrence],
) -> tuple[Fact, ...]:
    facts = []
    for item in occurrences:
        fields = {
            "NAME": item.name,
            "LANGUAGE": item.language,
            "FILE_PATH": item.file,
            "IS_TEST": str(_is_test_path(item.file)).lower(),
        }
        if item.resolved_module:
            fields["RESOLVED_MODULE"] = item.resolved_module
        if item.component:
            fields["COMPONENT"] = item.component
        if item.function:
            fields["FUNCTION"] = item.function
        facts.append(Fact("ANNOTATION", fields, item.file, item.line))
    return tuple(facts)


def facts_from_syntax(
    occurrences: Iterable[SyntaxOccurrence],
) -> tuple[Fact, ...]:
    facts = []
    for item in occurrences:
        fields = {
            "KIND": item.kind,
            "NAME": item.name,
            "LANGUAGE": item.language,
            "FILE_PATH": item.file,
            "IS_TEST": str(_is_test_path(item.file)).lower(),
        }
        if item.resolved_module:
            fields["RESOLVED_MODULE"] = item.resolved_module
        if item.component:
            fields["COMPONENT"] = item.component
        if item.function:
            fields["FUNCTION"] = item.function
        facts.append(Fact("SYNTAX_NODE", fields, item.file, item.line))
    return tuple(facts)


def _is_test_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    parts = set(lowered.split("/")[:-1])
    stem = lowered.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return (
        bool(
            parts
            & {"test", "tests", "testing", "spec", "specs", "__tests__", "fixtures"}
        )
        or stem.startswith("test_")
        or stem.endswith(("test", "spec"))
    )


def _dependency_is_test(scope: str | None, path: str) -> bool:
    lowered = (scope or "").lower()
    manifest_name = path.lower().replace("\\", "/").rsplit("/", 1)[-1]
    requirements_dev = (
        manifest_name.startswith("requirements-")
        and manifest_name.endswith(".txt")
        and any(token in manifest_name for token in ("-dev", "-test"))
    )
    return (
        _is_test_path(path)
        or requirements_dev
        or "test" in lowered
        or lowered in {"devdependencies", "require-dev", "dev-dependencies"}
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
        initially_resolved = tuple(fact.resolved(self.resolve(fact)) for fact in facts)
        local_technologies: dict[tuple[str, str], set[str]] = defaultdict(set)
        local_modules: dict[tuple[str, str], set[str]] = defaultdict(set)
        module_technologies: dict[tuple[str, str], set[str]] = defaultdict(set)
        for fact in initially_resolved:
            if fact.fact_type != "IMPORT":
                continue
            module = fact.fields.get("MODULE", "")
            if module and fact.tech_ids:
                module_technologies[(fact.file, module)].update(fact.tech_ids)
            for name in fact.fields.get("LOCAL_NAMES", "").split("|"):
                if name:
                    if module:
                        local_modules[(fact.file, name)].add(module)
                    if fact.tech_ids:
                        local_technologies[(fact.file, name)].update(fact.tech_ids)
        resolved_list: list[Fact] = []
        for fact in initially_resolved:
            if fact.fact_type not in {"ANNOTATION", "API_CALL", "SYNTAX_NODE"}:
                resolved_list.append(fact)
                continue
            fields = fact.fields
            resolved_name = fields.get("RESOLVED_LOCAL_NAME", "")
            modules = local_modules.get((fact.file, resolved_name), set())
            if resolved_name and len(modules) == 1:
                fields = {**fields, "RESOLVED_MODULE": next(iter(modules))}
            resolved_module = fields.get("RESOLVED_MODULE", "")
            tech_ids = set(fact.tech_ids)
            if resolved_name:
                tech_ids.update(local_technologies.get((fact.file, resolved_name), ()))
            if resolved_module:
                tech_ids.update(
                    module_technologies.get((fact.file, resolved_module), ())
                )
            if fact.fact_type != "API_CALL":
                resolved_list.append(
                    Fact(
                        fact.fact_type,
                        fields,
                        fact.file,
                        fact.line,
                        frozenset(tech_ids),
                    )
                )
                continue
            receiver = fact.fields.get("RECEIVER", "").split(".", 1)[0]
            method = fact.fields.get("METHOD", "")
            shadowed = set(fact.fields.get("SHADOWED_NAMES", "").split("|"))
            if receiver and receiver not in shadowed:
                tech_ids.update(local_technologies.get((fact.file, receiver), ()))
            if method not in shadowed:
                tech_ids.update(local_technologies.get((fact.file, method), ()))
            resolved_list.append(
                Fact(fact.fact_type, fields, fact.file, fact.line, frozenset(tech_ids))
            )
        resolved = tuple(resolved_list)

        matched: dict[str, list[Rule]] = defaultdict(list)
        evidence: list[EvidenceFact] = []
        personal_evidence: list[EvidenceFact] = []
        skipped: list[str] = []
        matched_rule_groups: dict[str, int] = {}

        for rule in self.rule_set.rules:
            if rule.evaluation_scope != "REPOSITORY":
                # PERSONAL needs commit authorship, and `--depth 1` has no
                # history. Reported rather than dropped: an unimplemented level
                # and an unmet one look the same from the outside.
                skipped.append(rule.rule_id)
                continue
            matched_group = self._match(rule, resolved)
            if matched_group is None:
                continue
            group_no, supporting = matched_group
            matched[rule.tech_id].append(rule)
            matched_rule_groups[rule.rule_id] = group_no
            supporting_evidence = [
                EvidenceFact(rule.rule_id, rule.tech_id, fact) for fact in supporting
            ]
            personal_evidence.extend(supporting_evidence)
            evidence.extend(supporting_evidence[: self.max_evidence_per_rule])

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
            personal_evidence=tuple(personal_evidence),
            skipped_rule_ids=tuple(skipped),
            rule_pack_version=self.rule_set.rule_pack_version,
            rule_pack_content_sha256=self.rule_set.rule_pack_content_sha256,
            technology_support=dict(self.rule_set.technology_support),
            matched_rule_groups=matched_rule_groups,
        )

    def _match(
        self, rule: Rule, facts: tuple[Fact, ...]
    ) -> tuple[int, list[Fact]] | None:
        """Facts supporting `rule`, or `None` when no group is satisfied."""
        applicable = [
            fact
            for fact in facts
            if (
                self.rule_set.rule_pack_version is None
                or fact.fields.get("IS_TEST") != "true"
            )
            and (
                rule.language is None
                or _IMPORT_ECOSYSTEMS.get(fact.fields.get("LANGUAGE", ""))
                == rule.language
                or fact.fields.get("ECOSYSTEM") == rule.language
            )
        ]
        for group_no, clauses in rule.groups().items():
            hits_by_clause: list[tuple[Clause, list[Fact]]] = []
            for clause in clauses:
                hits = self._clause_hits(clause, applicable)
                if len(hits) < clause.min_match_count:
                    if clause.role == "REQUIRED":
                        break
                    continue
                hits_by_clause.append((clause, hits))
            else:
                supporting = self._bound_support(rule, hits_by_clause)
                if supporting is not None:
                    return group_no, supporting
        return None

    @staticmethod
    def _bound_support(
        rule: Rule, hits_by_clause: list[tuple[Clause, list[Fact]]]
    ) -> list[Fact] | None:
        if not rule.binding_fields:
            return [fact for _clause, hits in hits_by_clause for fact in hits]

        required = [
            (clause, hits)
            for clause, hits in hits_by_clause
            if clause.role == "REQUIRED"
        ]
        if not required:
            return [fact for _clause, hits in hits_by_clause for fact in hits]
        # Index each clause once: a rejected candidate must not hide later
        # matches, nor make every candidate rescan every repository fact.
        indexed = []
        keys_by_clause: list[set[tuple[str, ...]]] = []
        for clause, hits in hits_by_clause:
            by_key: dict[tuple[str, ...], list[Fact]] = defaultdict(list)
            for fact in hits:
                key = tuple(fact.fields.get(field, "") for field in rule.binding_fields)
                if all(key):
                    by_key[key].append(fact)
            indexed.append((clause, by_key))
            if clause.role == "REQUIRED":
                keys_by_clause.append(set(by_key))
        common = set.intersection(*keys_by_clause) if keys_by_clause else set()
        for selected in sorted(common):
            selected_hits = [
                (clause, by_key.get(selected, [])) for clause, by_key in indexed
            ]
            supporting = Judge._candidate_support(rule, selected_hits)
            if supporting is not None:
                return supporting
        return None

    @staticmethod
    def _candidate_support(
        rule: Rule, selected_hits: list[tuple[Clause, list[Fact]]]
    ) -> list[Fact] | None:
        """Validate counts and call attribution within one binding candidate."""
        imported_names = {
            name
            for clause, hits in selected_hits
            if clause.fact_type == "IMPORT"
            for fact in hits
            for name in fact.fields.get("LOCAL_NAMES", "").split("|")
            if name
        }
        supporting: list[Fact] = []
        for clause, hits in selected_hits:
            if clause.fact_type == "API_CALL":
                hits = [
                    fact
                    for fact in hits
                    for shadowed in (
                        set(fact.fields.get("SHADOWED_NAMES", "").split("|")),
                    )
                    if rule.tech_id in fact.tech_ids
                    or (
                        fact.fields.get("RESOLVED_MODULE", "")
                        and any(
                            predicate.fact_field == "RESOLVED_MODULE"
                            for predicate in clause.predicates
                        )
                    )
                    or (
                        fact.fields.get("RECEIVER", "").split(".", 1)[0]
                        in imported_names
                        and fact.fields.get("RECEIVER", "").split(".", 1)[0]
                        not in shadowed
                    )
                    or (
                        fact.fields.get("METHOD", "") in imported_names
                        and fact.fields.get("METHOD", "") not in shadowed
                    )
                ]
            if clause.role == "REQUIRED" and len(hits) < clause.min_match_count:
                return None
            supporting.extend(hits)
        return supporting

    def _clause_hits(self, clause: Clause, facts: list[Fact]) -> list[Fact]:
        return [
            fact
            for fact in facts
            if fact.fact_type == clause.fact_type
            and all(
                _predicate_holds(predicate, fact) for predicate in clause.predicates
            )
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


def fact_matches_clause(clause: Clause, fact: Fact) -> bool:
    """Return whether an already-resolved Fact satisfies one Rule Pack clause."""

    return fact.fact_type == clause.fact_type and all(
        _predicate_holds(predicate, fact) for predicate in clause.predicates
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
