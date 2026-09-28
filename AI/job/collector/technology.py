"""Conservative technology and requirement extraction for job descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

from job.contracts import RequirementType, SourceSurface, TechnologyMentionInput


@dataclass(frozen=True)
class TechnologyRule:
    technology_id: str
    pattern: Pattern[str]


def _rule(technology_id: str, expression: str) -> TechnologyRule:
    return TechnologyRule(
        technology_id=technology_id,
        pattern=re.compile(expression, re.IGNORECASE),
    )


TECHNOLOGY_RULES = (
    _rule("dotnet-maui", r"(?<![A-Za-z0-9])\.NET[\s-]*MAUI(?![A-Za-z0-9])"),
    _rule("aspnet-core", r"(?<![A-Za-z0-9])ASP\.NET[\s-]*Core(?![A-Za-z0-9])"),
    _rule("docker-compose", r"(?<![A-Za-z0-9])Docker[\s-]+Compose(?![A-Za-z0-9])"),
    _rule("github-actions", r"(?<![A-Za-z0-9])GitHub[\s-]+Actions(?![A-Za-z0-9])"),
    _rule("aws-lambda", r"(?<![A-Za-z0-9])AWS[\s-]+Lambda(?![A-Za-z0-9])"),
    _rule("spring-boot", r"(?<![A-Za-z0-9])Spring[\s-]*Boot(?![A-Za-z0-9])"),
    _rule("nodejs", r"(?<![A-Za-z0-9])Node(?:\.js|JS)(?![A-Za-z0-9])"),
    _rule("nextjs", r"(?<![A-Za-z0-9])Next(?:\.js|JS)(?![A-Za-z0-9])"),
    _rule("vuejs", r"(?<![A-Za-z0-9])Vue(?:\.js|JS)(?![A-Za-z0-9])"),
    _rule("express", r"(?<![A-Za-z0-9])Express(?:\.js|JS)?(?![A-Za-z0-9])"),
    _rule("nestjs", r"(?<![A-Za-z0-9])Nest(?:\.js|JS)?(?![A-Za-z0-9])"),
    _rule("rest-api", r"(?<![A-Za-z0-9])REST(?:ful)?[\s-]+API(?![A-Za-z0-9])"),
    _rule("ci-cd", r"(?<![A-Za-z0-9])CI\s*/?\s*CD(?![A-Za-z0-9])"),
    _rule(
        "postgresql",
        r"(?<![A-Za-z0-9])(?:PostgreSQL|Postgres)(?![A-Za-z0-9])",
    ),
    _rule("elasticsearch", r"(?<![A-Za-z0-9])Elastic(?:search|Search)(?![A-Za-z0-9])"),
    _rule(
        "kubernetes",
        r"(?<![A-Za-z0-9])(?:Kubernetes|K8s)(?![A-Za-z0-9])",
    ),
    _rule("typescript", r"(?<![A-Za-z0-9])TypeScript(?![A-Za-z0-9])"),
    _rule("javascript", r"(?<![A-Za-z0-9])JavaScript(?![A-Za-z0-9])"),
    _rule("csharp", r"(?<![A-Za-z0-9])C\s*#(?![A-Za-z0-9])"),
    _rule("cpp", r"(?<![A-Za-z0-9])C\s*\+\+(?![A-Za-z0-9])"),
    _rule("aspnet", r"(?<![A-Za-z0-9])ASP\.NET(?![A-Za-z0-9])"),
    _rule("dotnet", r"(?<![A-Za-z0-9])\.NET(?![A-Za-z0-9])"),
    _rule("graphql", r"(?<![A-Za-z0-9])GraphQL(?![A-Za-z0-9])"),
    _rule("fastapi", r"(?<![A-Za-z0-9])FastAPI(?![A-Za-z0-9])"),
    _rule("spring", r"(?<![A-Za-z0-9])Spring(?![A-Za-z0-9])"),
    _rule("django", r"(?<![A-Za-z0-9])Django(?![A-Za-z0-9])"),
    _rule("flask", r"(?<![A-Za-z0-9])Flask(?![A-Za-z0-9])"),
    _rule("kotlin", r"(?<![A-Za-z0-9])Kotlin(?![A-Za-z0-9])"),
    _rule("java", r"(?<![A-Za-z0-9])Java(?![A-Za-z0-9])"),
    _rule("python", r"(?<![A-Za-z0-9])Python(?![A-Za-z0-9])"),
    _rule(
        "golang",
        r"(?<![A-Za-z0-9])(?:Golang|Go(?=\s*(?:언어|개발|개발자|"
        r"프로그래밍|백엔드|서버|서비스)))(?![A-Za-z0-9])",
    ),
    _rule("ruby", r"(?<![A-Za-z0-9])Ruby(?![A-Za-z0-9])"),
    _rule("php", r"(?<![A-Za-z0-9])PHP(?![A-Za-z0-9])"),
    _rule("rust", r"(?<![A-Za-z0-9])Rust(?![A-Za-z0-9])"),
    _rule("react", r"(?<![A-Za-z0-9])React(?:\.js|JS)?(?![A-Za-z0-9])"),
    _rule("angular", r"(?<![A-Za-z0-9])Angular(?![A-Za-z0-9])"),
    _rule("svelte", r"(?<![A-Za-z0-9])Svelte(?![A-Za-z0-9])"),
    _rule("mysql", r"(?<![A-Za-z0-9])MySQL(?![A-Za-z0-9])"),
    _rule("mariadb", r"(?<![A-Za-z0-9])MariaDB(?![A-Za-z0-9])"),
    _rule("oracle", r"(?<![A-Za-z0-9])Oracle(?![A-Za-z0-9])"),
    _rule(
        "mssql",
        r"(?<![A-Za-z0-9])(?:MS\s*SQL|MSSQL)(?![A-Za-z0-9])",
    ),
    _rule("mongodb", r"(?<![A-Za-z0-9])MongoDB(?![A-Za-z0-9])"),
    _rule("redis", r"(?<![A-Za-z0-9])Redis(?![A-Za-z0-9])"),
    _rule("kafka", r"(?<![A-Za-z0-9])Kafka(?![A-Za-z0-9])"),
    _rule("rabbitmq", r"(?<![A-Za-z0-9])RabbitMQ(?![A-Za-z0-9])"),
    _rule("aws", r"(?<![A-Za-z0-9])AWS(?![A-Za-z0-9])"),
    _rule(
        "azure",
        r"(?<![A-Za-z0-9])(?:Microsoft\s+Azure|Azure)(?![A-Za-z0-9])",
    ),
    _rule(
        "gcp",
        r"(?<![A-Za-z0-9])(?:Google\s+Cloud|GCP)(?![A-Za-z0-9])",
    ),
    _rule("docker", r"(?<![A-Za-z0-9])Docker(?![A-Za-z0-9])"),
    _rule("linux", r"(?<![A-Za-z0-9])Linux(?![A-Za-z0-9])"),
    _rule("nginx", r"(?<![A-Za-z0-9])Nginx(?![A-Za-z0-9])"),
    _rule("jenkins", r"(?<![A-Za-z0-9])Jenkins(?![A-Za-z0-9])"),
    _rule("terraform", r"(?<![A-Za-z0-9])Terraform(?![A-Za-z0-9])"),
    _rule("sql", r"(?<![A-Za-z0-9])SQL(?![A-Za-z0-9])"),
    _rule("jpa", r"(?<![A-Za-z0-9])JPA(?![A-Za-z0-9])"),
    _rule("hibernate", r"(?<![A-Za-z0-9])Hibernate(?![A-Za-z0-9])"),
    _rule("mybatis", r"(?<![A-Za-z0-9])MyBatis(?![A-Za-z0-9])"),
    _rule("git", r"(?<![A-Za-z0-9])Git(?![A-Za-z0-9])"),
    _rule("html", r"(?<![A-Za-z0-9])HTML5?(?![A-Za-z0-9])"),
    _rule("css", r"(?<![A-Za-z0-9])CSS3?(?![A-Za-z0-9])"),
)

_REQUIRED_RE = re.compile(
    r"필수|필수사항|필수조건|필수 역량|자격요건|자격 요건|요구사항|\bmust\b|\brequired\b",
    re.IGNORECASE,
)
_PREFERRED_RE = re.compile(
    r"우대|우대사항|우대 조건|선호|있으면 좋은|\bpreferred\b|\bnice to have\b",
    re.IGNORECASE,
)


def extract_technology_mentions(
    title: str,
    description_text: str | None,
) -> tuple[TechnologyMentionInput, ...]:
    """Extract known stacks while retaining requirement evidence and surface."""

    candidates: list[
        tuple[int, int, TechnologyRule, str, SourceSurface, str | None]
    ] = []
    title_value = title.strip()
    if title_value:
        candidates.extend(
            _find_candidates(title_value, SourceSurface.TITLE, "공고 제목")
        )
    if description_text:
        candidates.extend(_find_candidates(description_text, SourceSurface.BODY, None))

    candidates.sort(key=lambda item: (item[4].value, item[0], -(item[1] - item[0])))
    accepted: list[tuple[int, int, TechnologyRule, str, SourceSurface, str | None]] = []
    for candidate in candidates:
        if any(
            candidate[4] is other[4]
            and candidate[0] < other[1]
            and other[0] < candidate[1]
            for other in accepted
        ):
            continue
        accepted.append(candidate)

    mentions: dict[tuple[str, str, str], TechnologyMentionInput] = {}
    for start, end, rule, raw_text, surface, section in accepted:
        evidence_source = (
            title_value if surface is SourceSurface.TITLE else description_text or ""
        )
        evidence_text = _evidence_text(evidence_source, start, end)
        requirement_type = _requirement_type(evidence_source, start, end)
        extraction_method = (
            "OCR_RULE_BASED_V1"
            if evidence_source.rfind("[OCR 이미지]", 0, start + 1) >= 0
            else "RULE_BASED_V1"
        )
        if section is None:
            section = _section_name(evidence_source, start)
        mention = TechnologyMentionInput(
            raw_technology=raw_text,
            technology_id=rule.technology_id,
            requirement_type=requirement_type,
            source_surface=surface,
            evidence_section=section,
            evidence_text=evidence_text,
            extraction_method=extraction_method,
        )
        key = (
            rule.technology_id,
            requirement_type.value,
            surface.value,
        )
        current = mentions.get(key)
        if current is None or len(mention.evidence_text) > len(current.evidence_text):
            mentions[key] = mention
    return tuple(mentions.values())


def _find_candidates(
    text: str,
    surface: SourceSurface,
    title_section: str | None,
) -> list[tuple[int, int, TechnologyRule, str, SourceSurface, str | None]]:
    result: list[tuple[int, int, TechnologyRule, str, SourceSurface, str | None]] = []
    for rule in TECHNOLOGY_RULES:
        for match in rule.pattern.finditer(text):
            raw_text = match.group(0).strip()
            if raw_text:
                result.append(
                    (
                        match.start(),
                        match.end(),
                        rule,
                        raw_text,
                        surface,
                        title_section,
                    )
                )
    return result


def _requirement_type(text: str, start: int, end: int) -> RequirementType:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    current_line = text[line_start:line_end]
    required_match = list(_REQUIRED_RE.finditer(current_line))
    preferred_match = list(_PREFERRED_RE.finditer(current_line))
    if not required_match and not preferred_match:
        preceding_lines = text[:line_start].splitlines()
        for line in reversed(preceding_lines[-12:]):
            if _PREFERRED_RE.search(line):
                return RequirementType.PREFERRED
            if _REQUIRED_RE.search(line):
                return RequirementType.REQUIRED
        context = text[max(0, line_start - 240) : line_start]
        required_match = list(_REQUIRED_RE.finditer(context))
        preferred_match = list(_PREFERRED_RE.finditer(context))
        if not required_match and not preferred_match:
            return RequirementType.MENTIONED
    last_required = required_match[-1].start() if required_match else -1
    last_preferred = preferred_match[-1].start() if preferred_match else -1
    if last_preferred > last_required:
        return RequirementType.PREFERRED
    return RequirementType.REQUIRED


def _evidence_text(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end].strip()
    if line:
        return line[:500]
    return text[max(0, start - 100) : min(len(text), end + 100)].strip()[:500]


def _section_name(text: str, start: int) -> str:
    before = text[:start].splitlines()
    for line in reversed(before[-5:]):
        candidate = line.strip()
        if not candidate:
            continue
        if (
            candidate.endswith(":")
            or len(candidate) <= 30
            and any(
                word in candidate for word in ("자격", "업무", "우대", "기술", "담당")
            )
        ):
            return candidate.rstrip(":")
    return "본문"
