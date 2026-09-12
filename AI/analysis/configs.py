"""Bounded extraction of configuration facts used by repository Rule Packs."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from analysis.parse import walk_files

__all__ = [
    "ConfigOccurrence",
    "ConfigReport",
    "ConfigScanner",
    "facts_from_configs",
    "parse_config_bytes",
]

log = logging.getLogger("analysis.configs")


@dataclass(frozen=True)
class ConfigOccurrence:
    format: str
    key: str
    value: str
    file: str
    line: int
    scope: str = ""
    component: str = ""


@dataclass(frozen=True)
class ConfigReport:
    occurrences: tuple[ConfigOccurrence, ...]
    files_read: int
    skipped_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class ConfigScanner:
    max_file_bytes: int = 512 * 1024
    max_files: int = 1_000
    max_occurrences: int = 100_000

    def scan(self, root: Path) -> ConfigReport:
        occurrences: list[ConfigOccurrence] = []
        skipped: Counter[str] = Counter()
        files_read = 0
        for path in walk_files(root):
            relative = path.relative_to(root).as_posix()
            if _format_for(relative) is None:
                continue
            if files_read >= self.max_files:
                skipped["file_limit"] += 1
                continue
            try:
                with path.open("rb") as stream:
                    content = stream.read(self.max_file_bytes + 1)
            except OSError:
                skipped["unreadable"] += 1
                continue
            if len(content) > self.max_file_bytes:
                skipped["too_large"] += 1
                continue
            try:
                found = parse_config_bytes(relative, content)
            except (ValueError, json.JSONDecodeError) as invalid:
                log.debug("could not parse config %s: %s", relative, invalid)
                skipped["config_error"] += 1
                continue
            files_read += 1
            budget = self.max_occurrences - len(occurrences)
            if budget <= 0:
                skipped["occurrence_limit"] += 1
                continue
            occurrences.extend(found[:budget])
            if len(found) > budget:
                skipped["occurrence_limit"] += 1
        return ConfigReport(tuple(occurrences), files_read, dict(skipped))


def parse_config_bytes(path: str, content: bytes) -> tuple[ConfigOccurrence, ...]:
    """Parse one artifact in memory; public/archive callers need no temp checkout."""
    if len(content) > 512 * 1024:
        raise ValueError("config exceeds 512 KiB")
    relative = Path(path.replace("\\", "/")).as_posix()
    format_name = _format_for(relative)
    if format_name is None:
        return ()
    text = content.decode("utf-8", "replace")
    if format_name == "DOCKERFILE":
        return tuple(_dockerfile(text, relative))
    if format_name == "JENKINS":
        return tuple(_jenkins(text, relative))
    if format_name in {"COMPOSE", "KUBERNETES", "SPRING_YAML", "GCP_YAML", "YAML"}:
        kubernetes_profiles = (
            list(_kubernetes_profiles(text, relative))
            if format_name in {"KUBERNETES", "YAML"}
            else []
        )
        if format_name == "YAML" and kubernetes_profiles:
            format_name = "KUBERNETES"
        parsed = list(_yaml(text, relative, format_name))
        if format_name == "KUBERNETES":
            parsed.extend(kubernetes_profiles)
        return tuple(parsed)
    if format_name == "TERRAFORM":
        return tuple(_terraform(text, relative))
    if format_name == "PROPERTIES":
        return tuple(_properties(text, relative))
    if format_name == "JSON":
        return tuple(_json_config(text, relative))
    if format_name in {"UNITY", "XML"}:
        return tuple(_properties_or_xml(text, relative, format_name))
    return ()


def facts_from_configs(occurrences):
    from analysis.judge import Fact

    facts = []
    for item in occurrences:
        fields = {
            "FORMAT": item.format,
            "KEY": item.key,
            "VALUE": item.value,
            "FILE_PATH": item.file,
            "IS_TEST": str(_is_test_path(item.file)).lower(),
        }
        if item.scope:
            fields["SCOPE"] = item.scope
        if item.component:
            fields["COMPONENT"] = item.component
        facts.append(
            Fact(
                fact_type="CONFIG_KEY",
                fields=fields,
                file=item.file,
                line=item.line,
            )
        )
    return tuple(facts)


def _format_for(path: str) -> str | None:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "DOCKERFILE"
    if name == "jenkinsfile" or name.startswith("jenkinsfile."):
        return "JENKINS"
    if name in {
        "compose.yml",
        "compose.yaml",
        "docker-compose.yml",
        "docker-compose.yaml",
    }:
        return "COMPOSE"
    if name.startswith("application") and name.endswith((".yml", ".yaml")):
        return "SPRING_YAML"
    if name == "app.yaml":
        return "GCP_YAML"
    if name.endswith((".yml", ".yaml")) and any(
        part in lowered for part in ("k8s", "kubernetes", "helm", "templates")
    ):
        return "KUBERNETES"
    if name.endswith((".yml", ".yaml")):
        return "YAML"
    if name.endswith(".tf"):
        return "TERRAFORM"
    if name.endswith(".properties"):
        return "PROPERTIES"
    if name == "appsettings.json":
        return "JSON"
    if lowered.endswith("projectsettings/projectversion.txt"):
        return "UNITY"
    if name in {"core-site.xml", "hdfs-site.xml", "yarn-site.xml"} or name.endswith(
        "mapper.xml"
    ):
        return "XML"
    return None


def _dockerfile(text: str, path: str):
    instructions = _docker_instructions(text)
    for key, value, number in instructions:
        yield ConfigOccurrence("DOCKERFILE", key, value, path, number)

    stages: list[dict[str, object]] = []
    global_args: dict[str, str] = {}
    stage_values: dict[str, str] = {}
    for key, value, number in instructions:
        if key == "ARG":
            name, separator, default = value.partition("=")
            name = name.strip()
            if not name:
                continue
            if not stages:
                if separator:
                    global_args[name] = default.strip()
            elif separator:
                stage_values[name] = default.strip()
            elif name in global_args:
                # A global ARG is only available after FROM when the stage
                # explicitly redeclares it. Docker then inherits its value.
                stage_values[name] = global_args[name]
            else:
                stage_values.pop(name, None)
            continue
        if key == "FROM":
            resolved, unresolved = _docker_substitute(value, global_args)
            alias_match = re.search(r"(?i)\s+AS\s+([A-Za-z0-9_.-]+)\s*$", resolved)
            stages.append(
                {
                    "line": number,
                    "alias": alias_match.group(1)
                    if alias_match
                    else str(len(stages) + 1),
                    "unresolved": unresolved,
                    "user": None,
                    "healthcheck": None,
                }
            )
            # Pre-FROM ARG values are in scope for FROM interpolation only.
            stage_values = {}
            continue
        if not stages:
            continue
        if key == "ENV":
            env_name, separator, env_value = value.partition("=")
            if not separator:
                env_name, _, env_value = value.partition(" ")
            if env_name.strip() and env_value.strip():
                stage_values[env_name.strip()] = env_value.strip()
        elif key == "USER":
            resolved, unresolved = _docker_substitute(value, stage_values)
            stages[-1]["user"] = resolved.strip()
            stages[-1]["unresolved"] = bool(stages[-1]["unresolved"] or unresolved)
        elif key == "HEALTHCHECK":
            stages[-1]["healthcheck"] = value.strip()

    if not stages:
        return
    final = stages[-1]
    tokens = ["FINAL_STAGE"]
    if len(stages) > 1:
        tokens.append("MULTISTAGE")
    if final["unresolved"]:
        tokens.append("UNRESOLVED_ARG")
    user = str(final["user"] or "").split(":", 1)[0].strip().casefold()
    if user and "$" not in user and user not in {"0", "root"}:
        tokens.append("EXPLICIT_NONROOT_USER")
    elif user in {"0", "root"}:
        tokens.append("FINAL_USER_ROOT")
    healthcheck = str(final["healthcheck"] or "")
    if healthcheck:
        without_options = re.sub(r"^(?:--[^\s]+(?:=[^\s]+)?\s+)*", "", healthcheck)
        if without_options.strip().upper() == "NONE":
            tokens.append("HEALTHCHECK_NONE")
        else:
            tokens.append("ACTIVE_HEALTHCHECK")
    yield ConfigOccurrence(
        "DOCKERFILE",
        "DOCKER_FINAL_STAGE_PROFILE",
        " ".join(tokens),
        path,
        int(final["line"]),
        scope=f"stage:{len(stages)}",
        component=str(final["alias"]),
    )


def _docker_instructions(text: str) -> list[tuple[str, str, int]]:
    """Return real Docker instructions while skipping continuations and heredoc bodies."""
    lines = text.splitlines()
    found: list[tuple[str, str, int]] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        number = index + 1
        index += 1
        if not stripped or stripped.startswith("#"):
            continue
        logical = stripped
        while logical.rstrip().endswith("\\") and index < len(lines):
            logical = logical.rstrip()[:-1] + " " + lines[index].strip()
            index += 1
        match = re.match(r"([A-Za-z]+)\s+(.*)", logical)
        if not match:
            continue
        key, value = match.group(1).upper(), match.group(2).strip()
        found.append((key, value, number))
        heredoc = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", value)
        if heredoc:
            marker = heredoc.group(1)
            while index < len(lines):
                terminal = lines[index].strip()
                index += 1
                if terminal == marker:
                    break
    return found


def _docker_substitute(value: str, variables: dict[str, str]) -> tuple[str, bool]:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group(1) or match.group(2)
        if name not in variables:
            unresolved = True
            return match.group(0)
        return variables[name]

    return re.sub(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", replace, value
    ), unresolved


def _jenkins(text: str, path: str):
    # Groovy strings and comments can contain example pipeline text. Preserve
    # line positions while removing them before matching executable DSL forms.
    masked = re.sub(
        r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|/\*[\s\S]*?\*/|//[^\n]*",
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        text,
    )
    forms = {
        "pipeline": r"\bpipeline\s*\{",
        "node": r"\bnode\s*(?:\([^)]*\))?\s*\{",
        "stage": r"\bstage\s*\(",
        "agent": r"\bagent\s+(?:any\b|none\b|\{)",
        "environment": r"\benvironment\s*\{",
        "post": r"\bpost\s*\{",
        "parallel": r"\bparallel\s*(?:\{|\()",
        "credentials": r"\bcredentials\s*\(",
        "withCredentials": r"\bwithCredentials\s*\(",
        "@Library": r"@Library\s*\(",
    }
    observed: list[tuple[str, int, int]] = []
    for keyword, pattern in forms.items():
        for match in re.finditer(pattern, masked):
            number = masked.count("\n", 0, match.start()) + 1
            observed.append((keyword, match.start(), number))
            yield ConfigOccurrence("JENKINS", keyword, keyword, path, number)
    roots = _jenkins_pipeline_spans(masked)
    for index, (start, end, root_key) in enumerate(roots, start=1):
        keys = [
            key
            for key, offset, _line in observed
            if start <= offset < end or key == "@Library"
        ]
        tokens = [
            "PIPELINE_BOUND",
            "DECLARATIVE" if root_key == "pipeline" else "SCRIPTED",
        ]
        stage_count = keys.count("stage")
        if stage_count:
            tokens.append("STAGE")
        if stage_count >= 2:
            tokens.append("MULTI_STAGE")
        for key, token in (
            ("agent", "AGENT"),
            ("post", "POST"),
            ("parallel", "PARALLEL"),
            ("@Library", "SHARED_LIBRARY"),
        ):
            if key in keys:
                tokens.append(token)
        if {"credentials", "withCredentials"} & set(keys):
            tokens.append("CREDENTIALS_BOUND")
        line = masked.count("\n", 0, start) + 1
        yield ConfigOccurrence(
            "JENKINS",
            "JENKINS_PIPELINE_PROFILE",
            " ".join(tokens),
            path,
            line,
            scope=f"pipeline:{index}",
            component=f"pipeline:{index}",
        )


def _jenkins_pipeline_spans(text: str) -> list[tuple[int, int, str]]:
    candidates = []
    for root_key, pattern in (
        ("pipeline", r"\bpipeline\s*\{"),
        ("node", r"\bnode\s*(?:\([^)]*\))?\s*\{"),
    ):
        for match in re.finditer(pattern, text):
            depth = 0
            end = None
            for index in range(text.find("{", match.start()), len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end is not None:
                candidates.append((match.start(), end, root_key))
    candidates.sort()
    return [
        candidate
        for candidate in candidates
        if not any(
            outer_start <= candidate[0] and candidate[1] <= outer_end
            for outer_start, outer_end, _outer_key in candidates
            if (outer_start, outer_end) != candidate[:2]
        )
    ]


def _yaml(text: str, path: str, format_name: str):
    stack: list[tuple[int, str, bool]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(
            r"^(?P<indent>\s*)(?:-\s*)?(?P<key>[A-Za-z0-9_.-]+):(?:\s*(?P<value>.*))?$",
            line,
        )
        if not match:
            continue
        indent = len(match.group("indent").replace("\t", "  "))
        sequence_item = line.lstrip().startswith("-")
        _trim_yaml_stack(stack, indent, sequence_item)
        key = match.group("key")
        full = ".".join([part for _depth, part, _sequence in stack] + [key])
        value = (match.group("value") or "").strip().strip("\"'")
        value = _safe_value(key, value)
        yield ConfigOccurrence(format_name, full, value, path, number)
        if not value:
            stack.append((indent, key, sequence_item))


@dataclass(frozen=True)
class _YamlEvent:
    document: int
    line: int
    indent: int
    path: tuple[str, ...]
    value: str


def _yaml_events(text: str) -> list[_YamlEvent]:
    events: list[_YamlEvent] = []
    stack: list[tuple[int, str, bool]] = []
    document = 0
    block_scalar_indent: int | None = None
    for number, original in enumerate(text.splitlines(), start=1):
        indent = len(original) - len(original.lstrip(" \t"))
        if block_scalar_indent is not None:
            if not original.strip() or indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        line = _without_yaml_comment(original).rstrip()
        stripped = line.strip()
        if stripped in {"---", "..."}:
            document += 1
            stack.clear()
            continue
        if not stripped:
            continue
        match = re.match(
            r"^(?P<indent>\s*)(?:-\s*)?(?P<key>[A-Za-z0-9_.-]+):(?:\s*(?P<value>.*))?$",
            line,
        )
        if not match:
            continue
        indent = len(match.group("indent").replace("\t", "  "))
        sequence_item = line.lstrip().startswith("-")
        _trim_yaml_stack(stack, indent, sequence_item)
        key = match.group("key")
        value = (match.group("value") or "").strip().strip("\"'")
        path_parts = tuple(part for _depth, part, _sequence in stack) + (key,)
        events.append(_YamlEvent(document, number, indent, path_parts, value))
        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            block_scalar_indent = indent
        elif not value:
            stack.append((indent, key, sequence_item))
    return events


def _trim_yaml_stack(
    stack: list[tuple[int, str, bool]], indent: int, sequence_item: bool
) -> None:
    if not sequence_item:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        return
    while stack and (
        stack[-1][0] > indent or (stack[-1][0] == indent and stack[-1][2])
    ):
        stack.pop()


def _without_yaml_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if (
            character == "#"
            and quote is None
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index]
    return line


def _kubernetes_profiles(text: str, path: str):
    events = _yaml_events(text)
    by_document: dict[int, list[_YamlEvent]] = {}
    for event in events:
        by_document.setdefault(event.document, []).append(event)
    for document, document_events in sorted(by_document.items()):
        api_version = _yaml_scalar(document_events, ("apiVersion",))
        if not re.fullmatch(
            r"(?:[A-Za-z0-9.-]+/)?v[0-9]+(?:(?:alpha|beta)[0-9]+)?",
            api_version,
        ):
            continue
        kind = _yaml_scalar(document_events, ("kind",))
        name = _yaml_scalar(document_events, ("metadata", "name"))
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}:
            container_parents = {
                "Pod": {("spec", "containers"), ("spec", "initContainers")},
                "CronJob": {
                    ("spec", "jobTemplate", "spec", "template", "spec", "containers"),
                    (
                        "spec",
                        "jobTemplate",
                        "spec",
                        "template",
                        "spec",
                        "initContainers",
                    ),
                },
            }.get(
                kind,
                {
                    ("spec", "template", "spec", "containers"),
                    ("spec", "template", "spec", "initContainers"),
                },
            )
            starts = [
                event
                for event in document_events
                if event.path[:-1] in container_parents
                and event.path[-1] == "name"
                and event.value
            ]
            pod_security_path = next(iter(container_parents))[:-1] + (
                "securityContext",
                "runAsNonRoot",
            )
            pod_nonroot = any(
                event.path == pod_security_path and event.value.casefold() == "true"
                for event in document_events
            )
            for index, start in enumerate(starts):
                end_line = starts[index + 1].line if index + 1 < len(starts) else 10**9
                container_events = [
                    event
                    for event in document_events
                    if start.line <= event.line < end_line
                ]
                prefix = start.path[:-1]
                relevant = [
                    event
                    for event in container_events
                    if event.path[: len(prefix)] == prefix
                ]
                paths = {event.path[len(prefix) :] for event in relevant}
                values = {
                    event.path[len(prefix) :]: event.value.casefold()
                    for event in relevant
                }
                tokens = ["WORKLOAD_CONTAINER"]
                if values.get(("image",)):
                    tokens.append("IMAGE")
                for suffix, token in (
                    (("resources", "requests", "cpu"), "REQUEST_CPU"),
                    (("resources", "requests", "memory"), "REQUEST_MEMORY"),
                    (("resources", "limits", "cpu"), "LIMIT_CPU"),
                    (("resources", "limits", "memory"), "LIMIT_MEMORY"),
                ):
                    if values.get(suffix):
                        tokens.append(token)
                handlers = {"exec", "grpc", "httpGet", "tcpSocket"}
                if any(
                    len(parts) >= 2
                    and parts[0] == "readinessProbe"
                    and parts[1] in handlers
                    for parts in paths
                ):
                    tokens.append("READINESS_PROBE")
                if any(
                    len(parts) >= 2
                    and parts[0] == "livenessProbe"
                    and parts[1] in handlers
                    for parts in paths
                ):
                    tokens.append("LIVENESS_PROBE")
                if (
                    pod_nonroot
                    or values.get(("securityContext", "runAsNonRoot")) == "true"
                ):
                    tokens.append("RUN_AS_NON_ROOT")
                if (
                    values.get(("securityContext", "allowPrivilegeEscalation"))
                    == "false"
                ):
                    tokens.append("NO_PRIVILEGE_ESCALATION")
                if values.get(("securityContext", "readOnlyRootFilesystem")) == "true":
                    tokens.append("READ_ONLY_ROOT_FILESYSTEM")
                component = (
                    f"document:{document}/{kind}:{name or document}"
                    f"/container:{start.value}@line:{start.line}"
                )
                yield ConfigOccurrence(
                    "KUBERNETES",
                    "KUBERNETES_CONTAINER_PROFILE",
                    " ".join(tokens),
                    path,
                    start.line,
                    scope=f"document:{document}",
                    component=component,
                )
        elif kind == "HorizontalPodAutoscaler":
            target = next(
                (
                    event.value
                    for event in document_events
                    if event.path[-2:] == ("scaleTargetRef", "name") and event.value
                ),
                "",
            )
            tokens = ["HPA"]
            if any(event.path[-1:] == ("minReplicas",) for event in document_events):
                tokens.append("MIN_REPLICAS")
            if any(event.path[-1:] == ("maxReplicas",) for event in document_events):
                tokens.append("MAX_REPLICAS")
            if any("metrics" in event.path for event in document_events):
                tokens.append("METRICS")
            yield ConfigOccurrence(
                "KUBERNETES",
                "KUBERNETES_POLICY_PROFILE",
                " ".join(tokens),
                path,
                document_events[0].line,
                scope=f"document:{document}",
                component=f"workload:{target}" if target else "",
            )
        elif kind == "PodDisruptionBudget":
            tokens = ["PDB"]
            if any(
                event.path[-1:] in {("minAvailable",), ("maxUnavailable",)}
                for event in document_events
            ):
                tokens.append("AVAILABILITY_BUDGET")
            if any("selector" in event.path for event in document_events):
                tokens.append("SELECTOR")
            yield ConfigOccurrence(
                "KUBERNETES",
                "KUBERNETES_POLICY_PROFILE",
                " ".join(tokens),
                path,
                document_events[0].line,
                scope=f"document:{document}",
                component=f"policy:{name or document}",
            )


def _yaml_scalar(events: list[_YamlEvent], path: tuple[str, ...]) -> str:
    return next((event.value for event in events if event.path == path), "")


def _terraform(text: str, path: str):
    # Keep quoted provider names, but exclude comments and heredoc examples.
    # Blanking instead of deleting preserves the source line in each Fact.
    text = _masked_terraform(text)
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        block = re.match(
            r'(provider|resource|data|module)\s+"([^"]+)"(?:\s+"([^"]+)")?', stripped
        )
        if block:
            value = ":".join(part for part in block.groups()[1:] if part)
            yield ConfigOccurrence("TERRAFORM", block.group(1), value, path, number)
            continue
        pair = re.match(r"([A-Za-z0-9_.-]+)\s*=\s*(.+)", stripped)
        if pair:
            yield ConfigOccurrence(
                "TERRAFORM",
                pair.group(1),
                _safe_value(pair.group(1), pair.group(2).strip()),
                path,
                number,
            )
    yield from _terraform_profiles(text, path)


def _masked_terraform(text: str) -> str:
    text = re.sub(
        r"<<-?([A-Za-z_][A-Za-z0-9_]*)[^\n]*\n[\s\S]*?^\s*\1\s*$",
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r'("(?:\\.|[^"\\])*")|(/\*[\s\S]*?\*/|//[^\n]*|\#[^\n]*)',
        lambda match: match.group(1) or re.sub(r"[^\n]", " ", match.group()),
        text,
    )
    return text


_CLOUD_RESOURCE_TYPES = {
    "aws": {
        "network": {"aws_vpc"},
        "managed": {
            "aws_db_instance",
            "aws_eks_cluster",
            "aws_elasticache_cluster",
            "aws_elasticache_replication_group",
            "aws_msk_cluster",
            "aws_s3_bucket",
        },
        "iam": {"aws_iam_policy", "aws_iam_role_policy"},
    },
    "azure": {
        "network": {"azurerm_virtual_network"},
        "managed": {
            "azurerm_kubernetes_cluster",
            "azurerm_mysql_flexible_server",
            "azurerm_postgresql_flexible_server",
            "azurerm_redis_cache",
            "azurerm_storage_account",
        },
        "iam": {"azurerm_role_definition"},
    },
    "gcp": {
        "network": {"google_compute_network"},
        "managed": {
            "google_container_cluster",
            "google_redis_instance",
            "google_sql_database_instance",
            "google_storage_bucket",
        },
        "iam": {
            "google_organization_iam_custom_role",
            "google_project_iam_custom_role",
        },
    },
}


def _terraform_profiles(text: str, path: str):
    resources = [
        resource
        for resource in _terraform_resource_blocks(text)
        if not _terraform_literal_count_zero(resource[2])
    ]
    cloud_tokens: dict[str, set[str]] = {}
    first_line: dict[str, int] = {}
    components = {
        f"{resource_type}.{name}": (resource_type, body)
        for resource_type, name, body, _line in resources
    }
    l3_eligible = {
        component
        for component, (_resource_type, body) in components.items()
        if _terraform_l3_eligible(body)
    }
    references = {
        component: _terraform_references(body)
        for component, (_resource_type, body) in components.items()
    }
    graph = {
        component: {target for target in targets if target in l3_eligible}
        for component, targets in references.items()
        if component in l3_eligible
    }
    for resource_type, name, body, line in resources:
        cloud = next(
            (
                candidate
                for candidate, groups in _CLOUD_RESOURCE_TYPES.items()
                if any(resource_type in values for values in groups.values())
            ),
            None,
        )
        if cloud is None:
            continue
        tokens = ["DECLARED_RESOURCE"]
        groups = _CLOUD_RESOURCE_TYPES[cloud]
        if resource_type in groups["network"]:
            tokens.append("NETWORK")
        if resource_type in groups["managed"]:
            tokens.append("MANAGED_SERVICE")
        if resource_type in groups["iam"]:
            tokens.append("IAM_POLICY")
            if _least_privilege_policy(cloud, body):
                tokens.append("IAM_LEAST_PRIVILEGE")
        cloud_tokens.setdefault(cloud, set()).update(tokens)
        first_line.setdefault(cloud, line)
        yield ConfigOccurrence(
            "TERRAFORM",
            "TERRAFORM_RESOURCE_PROFILE",
            " ".join(tokens),
            path,
            line,
            scope=cloud,
            component=f"{resource_type}.{name}",
        )
    for cloud, groups in _CLOUD_RESOURCE_TYPES.items():
        network = {
            component
            for component, (resource_type, _body) in components.items()
            if resource_type in groups["network"] and component in l3_eligible
        }
        managed = {
            component
            for component, (resource_type, _body) in components.items()
            if resource_type in groups["managed"] and component in l3_eligible
        }
        iam = {
            component
            for component, (resource_type, body) in components.items()
            if resource_type in groups["iam"]
            and component in l3_eligible
            and _least_privilege_policy(cloud, body)
        }
        if cloud not in cloud_tokens:
            continue
        if _component_sets_connected(graph, managed, network):
            cloud_tokens[cloud].add("MANAGED_NETWORK_LINK")
        if _component_sets_directly_connected(graph, iam, managed):
            cloud_tokens[cloud].add("IAM_MANAGED_LINK")
    for cloud, tokens in sorted(cloud_tokens.items()):
        yield ConfigOccurrence(
            "TERRAFORM",
            "TERRAFORM_CLOUD_PROFILE",
            " ".join(sorted(tokens)),
            path,
            first_line[cloud],
            scope=cloud,
            component=f"cloud:{cloud}",
        )


def _component_sets_connected(
    graph: dict[str, set[str]], sources: set[str], targets: set[str]
) -> bool:
    if not sources or not targets:
        return False
    pending = list(sources)
    visited = set(sources)
    while pending:
        current = pending.pop()
        if current in targets:
            return True
        for neighbor in graph.get(current, ()):
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    return False


def _component_sets_directly_connected(
    graph: dict[str, set[str]], sources: set[str], targets: set[str]
) -> bool:
    return bool(sources and targets) and any(
        graph.get(source, set()) & targets for source in sources
    )


def _terraform_references(body: str) -> set[str]:
    """Return executable resource references, including template interpolation.

    Plain quoted text is descriptive data, not a graph edge. Terraform `${...}`
    expressions inside quoted templates remain executable and are retained.
    """

    def mask_plain_string(match: re.Match[str]) -> str:
        value = match.group()
        masked = [" " if character != "\n" else "\n" for character in value]
        for interpolation in re.finditer(r"\$\{[^{}]*\}", value):
            masked[interpolation.start() : interpolation.end()] = interpolation.group()
        return "".join(masked)

    expressions = re.sub(r'"(?:\\.|[^"\\])*"', mask_plain_string, body)
    return set(
        re.findall(
            r"\b(?:aws|azurerm|google)_[A-Za-z0-9_]+\.[A-Za-z0-9_-]+\b",
            expressions,
        )
    )


def _terraform_literal_count_zero(body: str) -> bool:
    expressions = re.sub(
        r'"(?:\\.|[^"\\])*"',
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        body,
    )
    return bool(re.search(r"(?m)(?:^|\{|;)\s*count\s*=\s*0(?:\s|$)", expressions))


def _terraform_l3_eligible(body: str) -> bool:
    expressions = re.sub(
        r'"(?:\\.|[^"\\])*"',
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        body,
    )
    assignments = list(
        re.finditer(
            r"(?m)(?:^|\{|;)\s*(count|for_each)\s*=\s*([^\n}]*)",
            expressions,
        )
    )
    if not assignments:
        return True
    return all(
        match.group(1) == "count"
        and bool(re.fullmatch(r"[1-9][0-9]*", match.group(2).strip()))
        for match in assignments
    )


def _terraform_resource_blocks(text: str) -> list[tuple[str, str, str, int]]:
    starts = list(re.finditer(r'(?m)^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text))
    blocks = []
    for match in starts:
        depth = 0
        quote = None
        escaped = False
        end = None
        for index in range(match.end() - 1, len(text)):
            character = text[index]
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote is not None:
                escaped = True
                continue
            if character == '"':
                quote = None if quote == '"' else '"'
                continue
            if quote is not None:
                continue
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            continue
        blocks.append(
            (
                match.group(1),
                match.group(2),
                text[match.start() : end],
                text.count("\n", 0, match.start()) + 1,
            )
        )
    return blocks


def _least_privilege_policy(cloud: str, body: str) -> bool:
    lowered = body.casefold()
    if cloud == "aws":
        return bool(
            _statically_narrow_literal_assignments(lowered, "actions?")
            and _statically_narrow_resource_assignments(lowered, "resources?")
        )
    if cloud == "azure":
        return bool(
            _statically_narrow_literal_assignments(lowered, "actions")
            and _statically_narrow_resource_assignments(lowered, "assignable_scopes")
        )
    return bool(
        _statically_narrow_literal_assignments(lowered, "permissions")
        and not _assignment_contains_wildcard(lowered, "permissions")
    )


def _nonempty_assignment(body: str, key_pattern: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:{key_pattern})\s*=\s*\[(?=\s*[^\]\s])",
            body,
            flags=re.DOTALL,
        )
    )


def _assignment_contains_wildcard(body: str, key_pattern: str) -> bool:
    return any(
        "*" in match.group(1)
        for match in re.finditer(
            rf"\b(?:{key_pattern})\s*=\s*\[([^]]*)\]",
            body,
            flags=re.DOTALL,
        )
    )


def _statically_narrow_literal_assignments(body: str, key_pattern: str) -> bool:
    """Accept action lists only when every value is a literal, non-wildcard string.

    Terraform variables, expressions, and interpolated templates require an
    evaluator to establish their effective permissions. The scanner deliberately
    does not run one, so those forms cannot support a least-privilege claim.
    """
    assignments = list(re.finditer(rf"\b(?:{key_pattern})\s*=", body))
    if not assignments:
        return False
    literal = re.compile(r'"((?:\\.|[^"\\])*)"')
    for assignment in assignments:
        array = re.match(r"\s*\[([^]]*)\]", body[assignment.end() :], re.DOTALL)
        if array is None:
            return False
        values = literal.findall(array.group(1))
        remainder = literal.sub("", array.group(1)).strip(" \t\r\n,")
        if (
            not values
            or remainder
            or any(
                not value.strip()
                or "\\" in value
                or "*" in value
                or "?" in value
                or "${" in value
                or "%{" in value
                for value in values
            )
        ):
            return False
    return True


def _statically_narrow_resource_assignments(body: str, key_pattern: str) -> bool:
    """Accept literal non-wildcard targets or concrete resource attributes."""
    assignments = list(re.finditer(rf"\b(?:{key_pattern})\s*=", body))
    if not assignments:
        return False
    literal = re.compile(r'"((?:\\.|[^"\\])*)"')
    reference = re.compile(
        r"(?:\$\{)?(?:aws|azurerm|google)_[a-z0-9_]+\.[a-z0-9_-]+\.[a-z0-9_-]+(?:\})?"
    )
    interpolated_reference = re.compile(
        r"\$\{(?:aws|azurerm|google)_[a-z0-9_]+\.[a-z0-9_-]+\.[a-z0-9_-]+\}"
    )
    for assignment in assignments:
        array = re.match(r"\s*\[([^]]*)\]", body[assignment.end() :], re.DOTALL)
        if array is None:
            return False
        value = array.group(1)
        literals = literal.findall(value)
        remainder = literal.sub("", value)
        remainder = reference.sub("", remainder).strip(" \t\r\n,")
        if remainder or not (literals or reference.search(value)):
            return False
        if any(
            not item.strip()
            or "\\" in item
            or "*" in item
            or "?" in item
            or "%{" in item
            or ("${" in item and not interpolated_reference.fullmatch(item))
            for item in literals
        ):
            return False
    return True


def _properties(text: str, path: str):
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        match = re.match(r"([^:=\s]+)\s*[:=]\s*(.*)", stripped)
        if match:
            yield ConfigOccurrence(
                "PROPERTIES",
                match.group(1),
                _safe_value(match.group(1), match.group(2)),
                path,
                number,
            )


def _json_config(text: str, path: str):
    document = json.loads(text)
    for key, value in _flatten_json(document):
        needle = f'"{key.rsplit(".", 1)[-1]}"'
        offset = text.find(needle)
        line = text.count("\n", 0, offset) + 1 if offset >= 0 else 1
        yield ConfigOccurrence("JSON", key, value, path, line)


def _flatten_json(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            full = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_json(child, full)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten_json(child, f"{prefix}.{index}")
    else:
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        yield prefix, _safe_value(prefix, rendered)


def _properties_or_xml(text: str, path: str, format_name: str):
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        pair = re.match(r"([^:=\s]+)\s*[:=]\s*(.*)", stripped)
        if pair:
            yield ConfigOccurrence(
                format_name,
                pair.group(1),
                _safe_value(pair.group(1), pair.group(2)),
                path,
                number,
            )
        for match in re.finditer(r"<([A-Za-z0-9_.-]+)>([^<]*)</\1>", stripped):
            yield ConfigOccurrence(
                format_name,
                match.group(1),
                _safe_value(match.group(1), match.group(2).strip()),
                path,
                number,
            )


def _is_test_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    parts = set(lowered.split("/")[:-1])
    markers = {"test", "tests", "testing", "spec", "specs", "fixtures"}
    filename_parts = set(re.split(r"[._-]", lowered.rsplit("/", 1)[-1]))
    return bool(parts & markers or filename_parts & markers)


def _safe_value(key: str, value: str) -> str:
    lowered = key.lower()
    if any(
        token in lowered
        for token in (
            "password",
            "passwd",
            "secret",
            "token",
            "credential",
            "private_key",
            "access_key",
        )
    ):
        return "<redacted>"
    return value[:300]
