"""Validated immutable Rule Pack data compiled into the existing Judge models."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.rules import Clause, Mapping, Predicate, Rule, RuleSet

__all__ = [
    "DEPTH_RULE_PACK_PATH",
    "EXPECTED_TECH_IDS",
    "RULE_PACK_PATH",
    "SCOPE_REGISTRY_PATH",
    "SCOPE_RULE_PACK_PATH",
    "InvalidRulePack",
    "RulePack",
    "load_rule_pack",
    "mappings_from_registry_artifact",
    "parse_rule_pack",
]

RULE_PACK_PATH = Path(__file__).with_name("data") / "rule_pack_20260911_2.json"
DEPTH_RULE_PACK_PATH = Path(__file__).with_name("data") / "rule_pack_20260911_3.json"
SCOPE_RULE_PACK_PATH = Path(__file__).with_name("data") / "rule_pack_20260911_4.json"
SCOPE_REGISTRY_PATH = (
    SCOPE_RULE_PACK_PATH.parents[2]
    / "registry"
    / "data"
    / "technology_registry_20260911_4.json"
)
EXPECTED_REGISTRY_VERSION = "registry-20260911.2"
EXPECTED_RULE_PACK_VERSION = "rule-pack-20260911.2"
SUPPORTED_VERSION_PAIRS = {
    "rule-pack-20260911.2": "registry-20260911.2",
    "rule-pack-20260911.3": "registry-20260911.3",
    "rule-pack-20260911.4": "registry-20260911.4",
}
EXPECTED_TECH_IDS = frozenset(
    (
        "c",
        "cpp",
        "csharp",
        "go",
        "java",
        "kotlin",
        "python",
        "javascript",
        "typescript",
        "php",
        "sql",
        "html",
        "css",
        "spring-framework",
        "spring-boot",
        "jpa",
        "mybatis",
        "dotnet",
        "nodejs",
        "nestjs",
        "django",
        "fastapi",
        "react",
        "nextjs",
        "vuejs",
        "unity",
        "numpy",
        "pandas",
        "scikit-learn",
        "pytorch",
        "tensorflow",
        "apache-spark",
        "hadoop",
        "apache-kafka",
        "mysql",
        "postgresql",
        "mongodb",
        "redis",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "jenkins",
    )
)
_FACT_TYPES = {
    "IMPORT",
    "DEPENDENCY",
    "ANNOTATION",
    "CONFIG_KEY",
    "API_CALL",
    "SOURCE_FILE",
    "SYNTAX_NODE",
}
_FACT_FIELDS = {
    "TECH_ID",
    "MODULE",
    "COORDINATE",
    "ECOSYSTEM",
    "SCOPE",
    "LANGUAGE",
    "FILE_PATH",
    "CALL",
    "METHOD",
    "RECEIVER",
    "NAME",
    "FORMAT",
    "KEY",
    "VALUE",
    "EXTENSION",
    "SLOC",
    "IS_TEST",
    "LOCAL_NAMES",
    "KIND",
    "RESOLVED_LOCAL_NAME",
    "RESOLVED_MODULE",
    "COMPONENT",
}
_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


class InvalidRulePack(ValueError):
    pass


class PredicateData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_field: str
    match_operator: Literal["EXACT", "PREFIX", "SUFFIX", "CONTAINS"]
    expected: tuple[str, ...] = Field(min_length=1)
    segment_delimiter: str | None = None

    @model_validator(mode="after")
    def _coherent(self):
        if not self.fact_field.strip():
            raise ValueError("fact_field must not be blank")
        if any(not value.strip() for value in self.expected):
            raise ValueError("expected values must not be blank")
        if self.segment_delimiter is not None:
            if not self.segment_delimiter:
                raise ValueError("segment_delimiter must not be blank")
            if self.match_operator != "PREFIX":
                raise ValueError("segment_delimiter is valid only for PREFIX")
        return self


class ClauseData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    clause_key: str
    role: Literal["REQUIRED", "OPTIONAL"] = "REQUIRED"
    fact_type: str
    min_match_count: int = Field(default=1, ge=1)
    predicates: tuple[PredicateData, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _nonblank_key(self):
        if not self.clause_key.strip():
            raise ValueError("clause_key must not be blank")
        return self


class RuleData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_id: str
    rule_type: Literal["L0", "L1", "L2", "L3"]
    language: str | None = None
    priority: int = Field(ge=0)
    binding_fields: tuple[str, ...] = ()
    groups: tuple[tuple[ClauseData, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent(self):
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be blank")
        if len(self.binding_fields) != len(set(self.binding_fields)):
            raise ValueError("binding_fields must be unique")
        if any(
            field not in {"FILE_PATH", "COMPONENT", "FUNCTION"}
            for field in self.binding_fields
        ):
            raise ValueError(
                "only FILE_PATH, COMPONENT and FUNCTION are supported binding fields"
            )
        if {"COMPONENT", "FUNCTION"} & set(
            self.binding_fields
        ) and "FILE_PATH" not in self.binding_fields:
            raise ValueError("COMPONENT and FUNCTION bindings also require FILE_PATH")
        for group in self.groups:
            if not group:
                raise ValueError("rule groups must not be empty")
            keys = [clause.clause_key for clause in group]
            if len(keys) != len(set(keys)):
                raise ValueError("clause_key must be unique within a group")
            if not any(clause.role == "REQUIRED" for clause in group):
                raise ValueError("each rule group must contain a REQUIRED clause")
        return self


class TechnologyRuleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tech_id: str
    evaluation_scope: Literal["REPOSITORY"]
    required_fact_types: tuple[str, ...] = Field(min_length=1)
    max_supported_level: Literal["L0", "L1", "L2", "L3"]
    coverage: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    limitations: tuple[str, ...] = ()
    rules: tuple[RuleData, ...] = Field(min_length=1)


class RulePack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["technology-rule-pack/v1"]
    rule_pack_version: str
    registry_version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    technologies: tuple[TechnologyRuleProfile, ...]

    @model_validator(mode="after")
    def _coherent(self):
        if self.rule_pack_version not in SUPPORTED_VERSION_PAIRS:
            raise ValueError(
                f"unsupported rule_pack_version {self.rule_pack_version!r}"
            )
        if self.registry_version != SUPPORTED_VERSION_PAIRS[self.rule_pack_version]:
            raise ValueError(f"unsupported registry_version {self.registry_version!r}")
        ids = [profile.tech_id for profile in self.technologies]
        if len(ids) != len(set(ids)) or set(ids) != EXPECTED_TECH_IDS:
            raise ValueError("technologies must be exactly the fixed 44 tech_id set")
        rule_ids: set[str] = set()
        for profile in self.technologies:
            required = set(profile.required_fact_types)
            if len(required) != len(profile.required_fact_types):
                raise ValueError(
                    f"{profile.tech_id} required_fact_types must be unique"
                )
            if not required <= _FACT_TYPES:
                raise ValueError(f"{profile.tech_id} names unknown required_fact_types")
            observed: set[str] = set()
            for rule in profile.rules:
                if rule.rule_id in rule_ids:
                    raise ValueError(f"duplicate rule_id {rule.rule_id!r}")
                rule_ids.add(rule.rule_id)
                if (
                    _LEVEL_ORDER[rule.rule_type]
                    > _LEVEL_ORDER[profile.max_supported_level]
                ):
                    raise ValueError(
                        f"{rule.rule_id} exceeds declared assessment ceiling"
                    )
                for group in rule.groups:
                    for clause in group:
                        observed.add(clause.fact_type)
                        if clause.fact_type not in _FACT_TYPES:
                            raise ValueError(f"{rule.rule_id} has unknown fact_type")
                        if any(
                            p.fact_field not in _FACT_FIELDS for p in clause.predicates
                        ):
                            raise ValueError(f"{rule.rule_id} has unknown fact_field")
            if required != observed:
                raise ValueError(
                    f"{profile.tech_id} required_fact_types must exactly describe rule facts"
                )
            highest = max(
                profile.rules, key=lambda rule: _LEVEL_ORDER[rule.rule_type]
            ).rule_type
            if profile.max_supported_level != highest:
                raise ValueError(
                    f"{profile.tech_id} max_supported_level must equal highest rule level"
                )
            if profile.coverage == "UNSUPPORTED":
                raise ValueError(
                    f"{profile.tech_id} cannot be UNSUPPORTED while it has rules"
                )
        return self

    @property
    def support(self) -> dict[str, TechnologyRuleProfile]:
        return {profile.tech_id: profile for profile in self.technologies}

    def as_rule_set(self, *, mappings: tuple[Mapping, ...] = ()) -> RuleSet:
        rules: list[Rule] = []
        clause_id = 1
        for profile in self.technologies:
            for source in profile.rules:
                clauses: list[Clause] = []
                for group_no, group in enumerate(source.groups, start=1):
                    for item in group:
                        clauses.append(
                            Clause(
                                clause_id=clause_id,
                                group_no=group_no,
                                clause_key=item.clause_key,
                                role=item.role,
                                fact_type=item.fact_type,
                                min_match_count=item.min_match_count,
                                predicates=tuple(
                                    Predicate(
                                        p.fact_field,
                                        p.match_operator,
                                        p.segment_delimiter,
                                        p.expected,
                                    )
                                    for p in item.predicates
                                ),
                            )
                        )
                        clause_id += 1
                rules.append(
                    Rule(
                        rule_id=source.rule_id,
                        tech_id=profile.tech_id,
                        rule_type=source.rule_type,
                        language=source.language,
                        evaluation_scope=profile.evaluation_scope,
                        priority=source.priority,
                        clauses=tuple(clauses),
                        binding_fields=source.binding_fields,
                    )
                )
        return RuleSet(
            registry_version=self.registry_version,
            mappings=mappings,
            rules=tuple(rules),
            rule_pack_version=self.rule_pack_version,
            rule_pack_content_sha256=self.content_sha256,
            technology_support=dict(self.support),
        )


def _hash_payload(payload: dict) -> str:
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def parse_rule_pack(payload: dict, *, registry=None) -> RulePack:
    supplied_hash = payload.get("content_sha256") if isinstance(payload, dict) else None
    if not isinstance(supplied_hash, str) or _hash_payload(payload) != supplied_hash:
        raise InvalidRulePack(
            "content_sha256 does not match canonical Rule Pack content"
        )
    try:
        pack = RulePack.model_validate(payload)
    except Exception as invalid:
        raise InvalidRulePack(str(invalid)) from invalid
    if registry is not None:
        technologies = (
            registry.get("technologies", ())
            if isinstance(registry, dict)
            else registry.technologies
        )
        ids = {
            item.get("tech_id") if isinstance(item, dict) else item.tech_id
            for item in technologies
            if (item.get("status") if isinstance(item, dict) else item.status)
            == "ACTIVE"
        }
        if ids != EXPECTED_TECH_IDS:
            raise InvalidRulePack(
                "registry ACTIVE technologies do not match Rule Pack fixed 44"
            )
        registry_version = (
            registry.get("registry_version")
            if isinstance(registry, dict)
            else registry.registry_version
        )
        if registry_version != pack.registry_version:
            raise InvalidRulePack("registry_version does not match Rule Pack")
    return pack


def load_rule_pack(path: Path, *, registry=None) -> RulePack:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as invalid:
        raise InvalidRulePack(str(invalid)) from invalid
    return parse_rule_pack(payload, registry=registry)


def mappings_from_registry_artifact(path: Path) -> tuple[Mapping, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("registry_version") not in SUPPORTED_VERSION_PAIRS.values():
        raise InvalidRulePack("registry_version is not supported by this Rule Pack")
    return tuple(
        Mapping(
            item["tech_id"],
            item["mapping_type"],
            item.get("ecosystem") or "",
            item["value"],
            item["match_mode"],
        )
        for item in payload.get("mappings", ())
        if item.get("status") == "ACTIVE"
        and item["mapping_type"] in {"IMPORT_PATH", "PACKAGE"}
    )
