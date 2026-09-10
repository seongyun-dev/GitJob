"""Resolution and rule evaluation, on hand-built registries.

No database. The rule set is a value, so every case here states exactly the
registry it is testing against — which is what makes it possible to pin the
semantics that only existed in migration comments until now.
"""

from __future__ import annotations

import pytest

from analysis.judge import (
    Fact,
    Judge,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
)
from analysis.manifests import DependencyOccurrence
from analysis.parse import CallOccurrence, ImportOccurrence
from analysis.rules import (
    Clause,
    Mapping,
    Predicate,
    Rule,
    RuleSet,
    UnknownRegistryVersion,
)


def tech_clause(fact_type: str, tech_id: str, *, group: int = 1, minimum: int = 1) -> Clause:
    """The shape V6 gave every generic rule: a condition on the resolved tech."""
    return Clause(
        clause_id=hash((fact_type, tech_id, group)) % 100000,
        group_no=group,
        clause_key="resolved-tech",
        role="REQUIRED",
        fact_type=fact_type,
        min_match_count=minimum,
        predicates=(Predicate("TECH_ID", "EXACT", None, (tech_id,)),),
    )


def module_clause(prefix: str, *, delimiter: str | None = ".") -> Clause:
    return Clause(
        clause_id=hash(prefix) % 100000,
        group_no=1,
        clause_key="module-prefix",
        role="REQUIRED",
        fact_type="IMPORT",
        min_match_count=1,
        predicates=(Predicate("MODULE", "PREFIX", delimiter, (prefix,)),),
    )


def rule(rule_id, tech_id, rule_type, clauses, *, language=None, scope="REPOSITORY"):
    return Rule(
        rule_id=rule_id,
        tech_id=tech_id,
        rule_type=rule_type,
        language=language,
        evaluation_scope=scope,
        priority=100,
        clauses=tuple(clauses),
    )


SPRING_MAPPINGS = (
    Mapping("spring-boot", "IMPORT_PATH", "JAVA", "org.springframework.boot", "PREFIX"),
    Mapping("spring-boot", "PACKAGE", "MAVEN",
            "org.springframework.boot:spring-boot-starter", "PREFIX"),
    Mapping("spring-data-jpa", "PACKAGE", "MAVEN",
            "org.springframework.boot:spring-boot-starter-data-jpa", "EXACT"),
)


def spring_registry() -> RuleSet:
    return RuleSet(
        registry_version="test.1",
        mappings=SPRING_MAPPINGS,
        rules=(
            rule("spring-boot.l0.dependency", "spring-boot", "L0",
                 [tech_clause("DEPENDENCY", "spring-boot")]),
            rule("spring-boot.l1.import", "spring-boot", "L1",
                 [tech_clause("IMPORT", "spring-boot")]),
            rule("spring-boot.l3.actuator", "spring-boot", "L3",
                 [module_clause("org.springframework.boot.actuate")]),
            rule("spring-data-jpa.l0.dependency", "spring-data-jpa", "L0",
                 [tech_clause("DEPENDENCY", "spring-data-jpa")]),
        ),
    )


def java_import(module: str, line: int = 1) -> Fact:
    return facts_from_imports(
        [ImportOccurrence(module, "java", "JAVA", "src/App.java", line)]
    )[0]


def maven_dependency(coordinate: str, scope: str = "implementation") -> Fact:
    return facts_from_dependencies(
        [DependencyOccurrence("MAVEN", coordinate, scope, "build.gradle", 3)]
    )[0]


# -- resolution -------------------------------------------------------------


def test_a_prefix_mapping_resolves_an_import_at_a_segment_boundary():
    judge = Judge(spring_registry())

    assert judge.resolve(java_import("org.springframework.boot.SpringApplication")) == {
        "spring-boot"
    }


def test_a_prefix_stops_at_the_segment_boundary():
    # org.springframeworkfoo is a different project. Getting this wrong is the
    # single most likely way to attach a technology to a repository that has none.
    judge = Judge(spring_registry())

    assert judge.resolve(java_import("org.springframeworkfoo.NotSpring")) == frozenset()


def test_one_dependency_can_resolve_to_several_technologies():
    # It evidences Spring Boot and it evidences Spring Data JPA. Choosing the
    # more specific one would throw away a fact that holds.
    judge = Judge(spring_registry())

    resolved = judge.resolve(
        maven_dependency("org.springframework.boot:spring-boot-starter-data-jpa")
    )

    assert resolved == {"spring-boot", "spring-data-jpa"}


def test_an_unmapped_import_resolves_to_nothing():
    assert Judge(spring_registry()).resolve(java_import("java.util.List")) == frozenset()


def test_a_malformed_coordinate_resolves_to_nothing_instead_of_raising():
    # The registry's own normalization calls this malformed. One bad manifest
    # line must not end the analysis.
    assert Judge(spring_registry()).resolve(maven_dependency("not-a-coordinate")) == frozenset()


# -- evaluation -------------------------------------------------------------


def test_an_import_produces_l1_and_a_dependency_produces_l0():
    judge = Judge(spring_registry())

    imports_only = judge.judge([java_import("org.springframework.boot.SpringApplication")])
    deps_only = judge.judge([maven_dependency("org.springframework.boot:spring-boot-starter-web")])

    assert [(v.tech_id, v.level) for v in imports_only.verdicts] == [("spring-boot", "L1")]
    assert [(v.tech_id, v.level) for v in deps_only.verdicts] == [("spring-boot", "L0")]


def test_the_highest_matched_level_wins_and_every_rule_is_named():
    # A level with no rule behind it cannot be explained, so the verdict keeps
    # all of them, not only the one that set the level.
    judge = Judge(spring_registry())

    judgement = judge.judge([
        java_import("org.springframework.boot.SpringApplication"),
        java_import("org.springframework.boot.actuate.health.HealthIndicator", 2),
        maven_dependency("org.springframework.boot:spring-boot-starter-actuator"),
    ])

    spring = next(v for v in judgement.verdicts if v.tech_id == "spring-boot")
    assert spring.level == "L3"
    assert set(spring.matched_rule_ids) == {
        "spring-boot.l0.dependency",
        "spring-boot.l1.import",
        "spring-boot.l3.actuator",
    }


def test_a_repository_using_nothing_gets_no_verdicts():
    judgement = Judge(spring_registry()).judge([java_import("java.util.List")])

    assert judgement.verdicts == ()
    assert judgement.evidence == ()


def test_evidence_names_the_rule_and_the_place():
    judge = Judge(spring_registry())

    judgement = judge.judge([java_import("org.springframework.boot.SpringApplication", 7)])

    item = next(e for e in judgement.evidence if e.rule_id == "spring-boot.l1.import")
    assert item.tech_id == "spring-boot"
    assert (item.fact.file, item.fact.line) == ("src/App.java", 7)


def test_evidence_is_capped_per_rule_without_changing_the_verdict():
    # spring-petclinic imports org.springframework.boot 41 times. The verdict is
    # decided before anything is dropped.
    judge = Judge(spring_registry(), max_evidence_per_rule=3)

    judgement = judge.judge(
        [java_import("org.springframework.boot.SpringApplication", n) for n in range(1, 31)]
    )

    assert [v.level for v in judgement.verdicts] == ["L1"]
    assert len(judgement.evidence) == 3


# -- clause, group and count semantics --------------------------------------


def test_groups_are_alternatives():
    # Kafka before V6: java OR python OR node. The shape still has to work.
    registry = RuleSet(
        registry_version="test.1",
        mappings=(Mapping("kafka", "IMPORT_PATH", "PYTHON", "kafka", "PREFIX"),),
        rules=(
            rule("kafka.l1", "kafka", "L1", [
                module_clause("org.apache.kafka"),
                Clause(2, 2, "python", "REQUIRED", "IMPORT", 1,
                       (Predicate("MODULE", "PREFIX", ".", ("kafka",)),)),
            ]),
        ),
    )
    python_import = facts_from_imports(
        [ImportOccurrence("kafka.admin", "python", "PYTHON", "a.py", 1)]
    )

    assert Judge(registry).judge(python_import).verdicts[0].tech_id == "kafka"


def test_min_match_count_needs_that_many_facts():
    registry = RuleSet(
        registry_version="test.1",
        mappings=SPRING_MAPPINGS,
        rules=(rule("spring-boot.l1.import", "spring-boot", "L1",
                    [tech_clause("IMPORT", "spring-boot", minimum=3)]),),
    )
    judge = Judge(registry)

    two = judge.judge([java_import("org.springframework.boot.A", 1),
                       java_import("org.springframework.boot.B", 2)])
    three = judge.judge([java_import("org.springframework.boot.A", 1),
                         java_import("org.springframework.boot.B", 2),
                         java_import("org.springframework.boot.C", 3)])

    assert two.verdicts == ()
    assert len(three.verdicts) == 1


def test_a_clause_only_counts_facts_of_its_own_type():
    # An L0 rule must not be satisfied by imports, or "declared" and "used"
    # collapse into the same level.
    judge = Judge(spring_registry())

    judgement = judge.judge([java_import("org.springframework.boot.SpringApplication")])

    assert "spring-boot.l0.dependency" not in {
        r for v in judgement.verdicts for r in v.matched_rule_ids
    }


def test_the_language_filter_restricts_which_facts_apply():
    registry = RuleSet(
        registry_version="test.1",
        mappings=(Mapping("redis", "IMPORT_PATH", "PYTHON", "redis", "PREFIX"),),
        rules=(rule("redis.l1", "redis", "L1", [tech_clause("IMPORT", "redis")],
                    language="JAVA"),),
    )
    python_import = facts_from_imports(
        [ImportOccurrence("redis.asyncio", "python", "PYTHON", "a.py", 1)]
    )

    assert Judge(registry).judge(python_import).verdicts == ()


def test_personal_scope_is_reported_as_skipped_not_as_unmet():
    # --depth 1 has no history, so contribution cannot be judged. An
    # unimplemented level and an unmet one must not look alike.
    registry = RuleSet(
        registry_version="test.1",
        mappings=SPRING_MAPPINGS,
        rules=(rule("spring-boot.l2.contribution", "spring-boot", "L2",
                    [tech_clause("IMPORT", "spring-boot")], scope="PERSONAL"),),
    )

    judgement = Judge(registry).judge(
        [java_import("org.springframework.boot.SpringApplication")]
    )

    assert judgement.verdicts == ()
    assert judgement.skipped_rule_ids == ("spring-boot.l2.contribution",)


# -- API_CALL and L2 --------------------------------------------------------


def java_call(callee: str, method: str, line: int = 5) -> Fact:
    receiver = callee.rsplit(".", 1)[0] if "." in callee else None
    return facts_from_calls([
        CallOccurrence(callee, method, receiver, "java", "JAVA", "src/App.java", line)
    ])[0]


def l2_registry() -> RuleSet:
    """An L2 rule of the shape V9 writes: the call AND the import, in one group."""
    return RuleSet(
        registry_version="test.1",
        mappings=SPRING_MAPPINGS,
        rules=(
            rule("spring-boot.l1.import", "spring-boot", "L1",
                 [tech_clause("IMPORT", "spring-boot")]),
            rule("spring-boot.l2.bootstrap", "spring-boot", "L2", [
                Clause(9001, 1, "api-call", "REQUIRED", "API_CALL", 1,
                       (Predicate("CALL", "EXACT", None, ("SpringApplication.run",)),)),
                Clause(9002, 1, "import-present", "REQUIRED", "IMPORT", 1,
                       (Predicate("TECH_ID", "EXACT", None, ("spring-boot",)),)),
            ]),
        ),
    )


def test_a_call_and_its_import_together_produce_l2():
    judgement = Judge(l2_registry()).judge([
        java_import("org.springframework.boot.SpringApplication"),
        java_call("SpringApplication.run", "run"),
    ])

    assert [(v.tech_id, v.level) for v in judgement.verdicts] == [("spring-boot", "L2")]


def test_a_call_without_the_import_does_not_produce_l2():
    # Found by running this on a tree containing CPython's standard library:
    # turtle.py calls backward() and statistics.py calls groupby(), which matched
    # PyTorch and pandas on the method name alone. Requiring the import removes
    # the whole class -- nothing calls a library's API without importing it.
    judgement = Judge(l2_registry()).judge([java_call("SpringApplication.run", "run")])

    assert judgement.verdicts == ()


def test_an_import_without_the_call_stops_at_l1():
    judgement = Judge(l2_registry()).judge(
        [java_import("org.springframework.boot.SpringApplication")]
    )

    assert [(v.tech_id, v.level) for v in judgement.verdicts] == [("spring-boot", "L1")]


def test_evidence_for_l2_includes_both_clauses():
    # The verdict rests on two facts, so both are the reason for it.
    judgement = Judge(l2_registry()).judge([
        java_import("org.springframework.boot.SpringApplication", 3),
        java_call("SpringApplication.run", "run", 11),
    ])

    supporting = [e for e in judgement.evidence if e.rule_id == "spring-boot.l2.bootstrap"]
    assert {e.fact.fact_type for e in supporting} == {"API_CALL", "IMPORT"}


def test_a_bare_method_name_matches_without_a_receiver():
    # useState() has no receiver, and the hook name is distinctive on its own.
    registry = RuleSet(
        registry_version="test.1",
        mappings=(Mapping("react", "IMPORT_PATH", "JAVASCRIPT", "react", "PREFIX"),),
        rules=(rule("react.l2.hooks", "react", "L2", [
            Clause(9101, 1, "api-call", "REQUIRED", "API_CALL", 1,
                   (Predicate("METHOD", "EXACT", None, ("useState", "useEffect")),)),
            Clause(9102, 1, "import-present", "REQUIRED", "IMPORT", 1,
                   (Predicate("TECH_ID", "EXACT", None, ("react",)),)),
        ]),),
    )
    facts = facts_from_imports(
        [ImportOccurrence("react", "javascript", "JAVASCRIPT", "a.jsx", 1)]
    ) + facts_from_calls(
        [CallOccurrence("useState", "useState", None, "javascript", "JAVASCRIPT", "a.jsx", 4)]
    )

    assert Judge(registry).judge(facts).verdicts[0].level == "L2"


def test_api_call_facts_are_not_resolved_to_technologies():
    # Resolution is for imports and dependencies. A call has no coordinate to
    # look up, so TECH_ID on a call fact is empty and only the import clause
    # can supply it.
    assert Judge(l2_registry()).resolve(java_call("SpringApplication.run", "run")) == frozenset()


# -- candidates -------------------------------------------------------------


def test_an_unmatched_dependency_becomes_a_candidate():
    judgement = Judge(spring_registry()).judge(
        [maven_dependency("com.h2database:h2", "runtimeOnly")]
    )

    assert len(judgement.candidates) == 1
    candidate = judgement.candidates[0]
    assert (candidate.ecosystem, candidate.coordinate) == ("MAVEN", "com.h2database:h2")
    assert candidate.scope == "runtimeOnly"


def test_an_unmatched_import_is_not_a_candidate():
    # A class path is the wrong granularity, and no truncation recovers the
    # package boundary. Only dependencies are promotable.
    judgement = Judge(spring_registry()).judge([java_import("org.junit.jupiter.api.Test")])

    assert judgement.candidates == ()


def test_a_matched_dependency_is_not_a_candidate():
    judgement = Judge(spring_registry()).judge(
        [maven_dependency("org.springframework.boot:spring-boot-starter-web")]
    )

    assert judgement.candidates == ()


def test_the_same_dependency_declared_twice_is_one_candidate():
    judgement = Judge(spring_registry()).judge(
        facts_from_dependencies([
            DependencyOccurrence("MAVEN", "com.h2database:h2", "runtimeOnly", "a/build.gradle", 3),
            DependencyOccurrence("MAVEN", "com.h2database:h2", "runtimeOnly", "b/build.gradle", 4),
        ])
    )

    assert len(judgement.candidates) == 1
    assert judgement.candidates[0].occurrence_count == 2


def test_a_differing_scope_does_not_split_one_candidate():
    # Found on spring-petclinic, which ships both a pom.xml and a build.gradle:
    # h2 is `runtime` in one and `runtimeOnly` in the other. Keying on scope
    # made two candidates out of one and the admin screen would rank halves.
    judgement = Judge(spring_registry()).judge(
        facts_from_dependencies([
            DependencyOccurrence("MAVEN", "com.h2database:h2", "runtime", "pom.xml", 20),
            DependencyOccurrence("MAVEN", "com.h2database:h2", "runtimeOnly", "build.gradle", 4),
        ])
    )

    assert len(judgement.candidates) == 1
    assert judgement.candidates[0].occurrence_count == 2
    # No single answer, so none is invented.
    assert judgement.candidates[0].scope is None


def test_a_scope_every_declaration_agrees_on_is_reported():
    judgement = Judge(spring_registry()).judge(
        facts_from_dependencies([
            DependencyOccurrence("MAVEN", "org.x:y", "testImplementation", "a/build.gradle", 3),
            DependencyOccurrence("MAVEN", "org.x:y", "testImplementation", "b/build.gradle", 9),
        ])
    )

    assert judgement.candidates[0].scope == "testImplementation"


# -- the rule set itself ----------------------------------------------------


def test_an_empty_registry_version_is_refused_rather_than_treated_as_empty():
    # No rows and "no technology matched" are indistinguishable downstream, and
    # the second is a normal result.
    with pytest.raises(UnknownRegistryVersion):
        RuleSet(registry_version="does-not-exist", mappings=(), rules=())
