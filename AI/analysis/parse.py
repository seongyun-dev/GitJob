"""Walk a checked-out repository and read its imports with tree-sitter.

Input is the directory `clone.py` produced; output is a list of occurrences,
each naming a module, a file and a line. Nothing is written to a database here:
turning occurrences into technologies is the registry's job, and Evidence rows
are a later stage.

### Why this bounds everything it touches

The repository is arbitrary content fetched from the internet. A single
generated file can be tens of megabytes, a `node_modules` that survived a
`.gitignore` mistake can hold a hundred thousand files, and a minified bundle is
one line long and parses to a tree far larger than the text. Each of those has a
limit here, and reaching one is recorded rather than raised: a repository that
is partly unreadable still yields useful evidence from the rest.

### Parsers are reused, grammars are loaded once

`Language` and `Parser` construction is not free, and a repository has thousands
of files of a handful of types. They are built on first use per language and
kept for the life of the object.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from analysis.languages import LANGUAGES, LanguageSpec, spec_for_path
from analysis.structure import (
    SyntaxOccurrence,
    build_binding_context,
    component_for_node,
    extract_syntax,
    function_for_node,
    resolve_call_binding,
    resolve_imported_symbol,
)

__all__ = [
    "EXCLUDED_DIRECTORIES",
    "AnnotationOccurrence",
    "CallOccurrence",
    "ImportOccurrence",
    "ParseReport",
    "RepositoryParser",
    "SourceFileOccurrence",
    "SyntaxOccurrence",
    "verify_grammars",
    "walk_files",
]

log = logging.getLogger("analysis.parse")

#: Directories that hold dependencies or build output. Their imports belong to
#: someone else's code, and counting them would report every transitive package
#: as something the author used.
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".gradle",
        ".idea",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "bin",
        "bower_components",
        "build",
        "dist",
        "generated",
        "library",
        "node_modules",
        "obj",
        "out",
        "target",
        "third_party",
        "vendor",
        "venv",
    }
)

#: Bundled or minified output. One line, machine written, and its imports are
#: whatever the bundler inlined rather than what anyone wrote.
EXCLUDED_SUFFIXES = (
    ".min.css",
    ".min.js",
    ".min.ts",
    ".bundle.js",
    ".d.ts",
)

_SOURCE_LANGUAGES = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".php": "php",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
}

_TEST_PARTS = frozenset({"test", "tests", "testing", "spec", "specs", "__tests__"})


def _analysis_language(language: str) -> str:
    """Canonical language exposed to rules while parser grammars stay distinct."""

    return "typescript" if language == "tsx" else language


@dataclass(frozen=True)
class ImportOccurrence:
    """One import, and where it was written.

    `file` and `line` are the point of this whole module: Evidence has to link
    to a permalink, and an aggregate count cannot.
    """

    module: str
    language: str
    ecosystem: str
    file: str
    line: int
    bindings: tuple[str, ...] = ()


#: A receiver longer than this is an expression, not a name. `a.b().c[0].d`
#: says nothing about which library `d` belongs to, and keeping it would make
#: every call site its own value.
_MAX_RECEIVER = 60
_SIMPLE_RECEIVER = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$"
)


@dataclass(frozen=True)
class CallOccurrence:
    """One call, as written.

    `callee` is what the source says -- `SpringApplication.run`, `useState`,
    `pd.read_csv` -- and `method` is its last segment. Neither is resolved: a
    parser cannot know that `kafkaTemplate` is a `KafkaTemplate`, so a rule that
    needs that certainty has to name a method distinctive enough not to need it.
    """

    callee: str
    method: str
    receiver: str | None
    language: str
    ecosystem: str
    file: str
    line: int
    #: Imported local names that were rebound before this call, or shadowed by
    #: an enclosing parameter. The Judge uses this to avoid lending the
    #: original import's identity to a local object with the same name.
    shadowed_bindings: tuple[str, ...] = ()
    #: Imported local symbol that created or typed this receiver. Empty when
    #: control flow, reassignment or shadowing makes the identity ambiguous.
    resolved_binding: str | None = None
    #: Stable containing declaration used to prevent cross-class/function sums.
    component: str | None = None
    #: Nearest lexical callable. Unlike COMPONENT, methods of one class differ.
    function: str | None = None


@dataclass(frozen=True)
class SourceFileOccurrence:
    """One authored source file, including languages without a parser grammar."""

    language: str
    extension: str
    sloc: int
    is_test: bool
    file: str
    line: int = 1


@dataclass(frozen=True)
class AnnotationOccurrence:
    """A Java/C#/TypeScript annotation or Python decorator as written."""

    name: str
    language: str
    file: str
    line: int
    resolved_module: str | None = None
    component: str | None = None
    function: str | None = None


@dataclass(frozen=True)
class ParseReport:
    """What the walk found, and what it could not read."""

    occurrences: tuple[ImportOccurrence, ...]
    files_parsed: int
    files_skipped: int
    bytes_parsed: int
    #: Calls, for the rules that ask what the code does rather than what it
    #: imports. Defaulted so every existing construction stays valid.
    calls: tuple[CallOccurrence, ...] = ()
    sources: tuple[SourceFileOccurrence, ...] = ()
    annotations: tuple[AnnotationOccurrence, ...] = ()
    syntax: tuple[SyntaxOccurrence, ...] = ()
    #: Reason -> count. Kept as a summary because per-file reasons on a large
    #: repository are noise, and the counts are what tell an operator whether a
    #: limit is set wrong.
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def modules(self) -> tuple[str, ...]:
        """Distinct module paths, in first-seen order."""
        seen: dict[str, None] = {}
        for occurrence in self.occurrences:
            seen.setdefault(occurrence.module, None)
        return tuple(seen)

    def by_language(self) -> dict[str, int]:
        return dict(Counter(item.language for item in self.occurrences))


@dataclass
class RepositoryParser:
    """Parses one checked-out tree. Not thread safe: parsers are cached."""

    max_file_bytes: int = 1024 * 1024
    max_files: int = 50_000
    max_occurrences: int = 200_000
    #: Calls are far more numerous than imports; petclinic has roughly ten
    #: times as many. The rules that read them match distinctive names, so a
    #: truncated tail costs little compared with an unbounded message.
    max_calls: int = 200_000
    max_syntax: int = 200_000
    _parsers: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _queries: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _call_queries: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )
    _annotation_queries: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )

    def parse_repository(self, root: Path) -> ParseReport:
        occurrences: list[ImportOccurrence] = []
        calls: list[CallOccurrence] = []
        sources: list[SourceFileOccurrence] = []
        annotations: list[AnnotationOccurrence] = []
        syntax: list[SyntaxOccurrence] = []
        skipped: Counter[str] = Counter()
        files_parsed = 0
        bytes_parsed = 0
        seen_files = 0

        for path in walk_files(root):
            seen_files += 1
            if seen_files > self.max_files:
                skipped["file_limit"] += 1
                continue

            relative = path.relative_to(root).as_posix()
            lowered = relative.lower()
            if lowered.endswith(EXCLUDED_SUFFIXES):
                skipped["generated_or_minified"] += 1
                continue
            spec = spec_for_path(relative)
            source_language, source_extension = _source_language(path)

            try:
                size = path.stat().st_size
            except OSError:
                skipped["unreadable"] += 1
                continue
            if size > self.max_file_bytes:
                skipped["too_large"] += 1
                continue

            try:
                source = path.read_bytes()
            except OSError:
                skipped["unreadable"] += 1
                continue
            if b"\x00" in source[:8192]:
                # A source extension on binary content. Feeding it to a parser
                # produces a tree of errors, slowly.
                skipped["binary"] += 1
                continue

            if source_language is not None:
                text = source.decode("utf-8", "replace")
                sloc = _sloc(text, source_language)
                if sloc:
                    sources.append(
                        SourceFileOccurrence(
                            language=source_language,
                            extension=source_extension,
                            sloc=sloc,
                            is_test=_is_test_path(relative),
                            file=relative,
                        )
                    )

            if spec is None:
                skipped["unsupported_language"] += 1
                continue

            try:
                tree = self._parser_for(spec).parse(source)
                found = self._parse_file(spec, relative, tree)
                called = self._parse_calls(spec, relative, found, tree)
                annotated = self._parse_annotations(spec, relative, found, tree)
                structured = self._parse_syntax(spec, relative, found, tree)
            except Exception as error:  # noqa: BLE001 - one bad file is not a failed repository
                log.debug("could not parse %s: %s", relative, error)
                skipped["parse_error"] += 1
                continue

            files_parsed += 1
            bytes_parsed += size
            annotations.extend(annotated)
            for item in structured:
                if len(syntax) >= self.max_syntax:
                    skipped["syntax_limit"] += 1
                    break
                syntax.append(item)
            for occurrence in found:
                if len(occurrences) >= self.max_occurrences:
                    skipped["occurrence_limit"] += 1
                    break
                occurrences.append(occurrence)
            for call in called:
                # A separate budget. Calls outnumber imports by an order of
                # magnitude, and letting them share one would mean a large file
                # of calls silently costs the imports of every later file.
                if len(calls) >= self.max_calls:
                    skipped["call_limit"] += 1
                    break
                calls.append(call)

        return ParseReport(
            occurrences=tuple(occurrences),
            files_parsed=files_parsed,
            # occurrence_limit is raised by a file that parsed successfully, so counting
            # it here would report the same file as both parsed and skipped.
            files_skipped=sum(
                count
                for reason, count in skipped.items()
                if reason not in {"occurrence_limit", "call_limit", "syntax_limit"}
            ),
            bytes_parsed=bytes_parsed,
            calls=tuple(calls),
            sources=tuple(sources),
            annotations=tuple(annotations),
            syntax=tuple(syntax),
            skipped_reasons=dict(skipped),
        )

    def _parse_file(
        self, spec: LanguageSpec, relative: str, tree
    ) -> list[ImportOccurrence]:
        from tree_sitter import QueryCursor

        query = self._query_for(spec)

        found: list[ImportOccurrence] = []
        # matches(), not captures(): a pattern that captures both the callee and
        # the argument needs them paired, and captures() flattens that away.
        for _pattern, captures in QueryCursor(query).matches(tree.root_node):
            if spec.guard_capture and spec.guard_capture in captures:
                names = {
                    node.text.decode("utf-8", "replace")
                    for node in captures[spec.guard_capture]
                }
                if not names & set(spec.guard_values):
                    continue
            for node in captures.get("m", ()):
                module = node.text.decode("utf-8", "replace").strip()
                if not module or module.startswith("."):
                    # Relative specifiers point inside this repository.
                    continue
                found.append(
                    ImportOccurrence(
                        module=module,
                        language=_analysis_language(spec.name),
                        ecosystem=spec.ecosystem,
                        file=relative,
                        # tree-sitter rows are 0-based; editors and permalinks
                        # are not.
                        line=node.start_point[0] + 1,
                        bindings=_import_bindings(spec.name, module, node),
                    )
                )
        return found

    def _parse_calls(
        self,
        spec: LanguageSpec,
        relative: str,
        imports: list[ImportOccurrence],
        tree,
    ) -> list[CallOccurrence]:
        """Method calls plus conservative source-bound receiver identity."""
        if not spec.call_query:
            return []
        from tree_sitter import QueryCursor

        query = self._call_query_for(spec)
        binding_context = build_binding_context(tree.root_node, imports)
        binding_definitions, root_scope = _binding_definitions(
            spec.name, tree.root_node
        )

        found: list[CallOccurrence] = []
        # matches(), not captures(): the receiver and the method name have to
        # stay paired, and captures() flattens that away.
        for _pattern, captures in QueryCursor(query).matches(tree.root_node):
            names = captures.get("method", ())
            if not names:
                continue
            node = names[0]
            method = node.text.decode("utf-8", "replace").strip()
            if not method:
                continue
            receiver_nodes = captures.get("recv", ())
            receiver = _receiver_text(receiver_nodes)
            shadowed_bindings = _shadowed_import_bindings(
                spec.name,
                node,
                receiver,
                method,
                imports,
                binding_definitions,
                root_scope,
            )
            resolved_binding = resolve_call_binding(
                tree.root_node,
                node,
                receiver,
                receiver_nodes[0] if receiver_nodes else None,
                method,
                imports,
                shadowed_bindings,
                binding_context,
            )
            found.append(
                CallOccurrence(
                    callee=f"{receiver}.{method}" if receiver else method,
                    method=method,
                    receiver=receiver,
                    language=_analysis_language(spec.name),
                    ecosystem=spec.ecosystem,
                    file=relative,
                    line=node.start_point[0] + 1,
                    shadowed_bindings=shadowed_bindings,
                    resolved_binding=resolved_binding,
                    component=component_for_node(node),
                    function=function_for_node(node),
                )
            )
        if spec.name == "csharp":
            stack = list(reversed(tree.root_node.named_children))
            while stack:
                invocation = stack.pop()
                stack.extend(reversed(invocation.named_children))
                if invocation.type != "invocation_expression":
                    continue
                function = invocation.child_by_field_name("function")
                if function is None:
                    continue
                receiver_node = None
                generic = function
                if function.type == "member_access_expression":
                    generic = function.child_by_field_name("name")
                    receiver_node = function.child_by_field_name("expression")
                if generic is None or generic.type != "generic_name":
                    continue
                node = next(
                    (
                        child
                        for child in generic.named_children
                        if child.type == "identifier"
                    ),
                    None,
                )
                if node is None:
                    continue
                method = _node_text(node)
                receiver_nodes = (receiver_node,) if receiver_node is not None else ()
                receiver = _receiver_text(receiver_nodes)
                shadowed_bindings = _shadowed_import_bindings(
                    spec.name,
                    node,
                    receiver,
                    method,
                    imports,
                    binding_definitions,
                    root_scope,
                )
                found.append(
                    CallOccurrence(
                        callee=f"{receiver}.{method}" if receiver else method,
                        method=method,
                        receiver=receiver,
                        language=_analysis_language(spec.name),
                        ecosystem=spec.ecosystem,
                        file=relative,
                        line=node.start_point[0] + 1,
                        shadowed_bindings=shadowed_bindings,
                        resolved_binding=resolve_call_binding(
                            tree.root_node,
                            node,
                            receiver,
                            receiver_node,
                            method,
                            imports,
                            shadowed_bindings,
                            binding_context,
                        ),
                        component=component_for_node(node),
                        function=function_for_node(node),
                    )
                )
        return found

    def _parse_syntax(
        self,
        spec: LanguageSpec,
        relative: str,
        imports: list[ImportOccurrence],
        tree,
    ) -> tuple[SyntaxOccurrence, ...]:
        return extract_syntax(
            tree.root_node, _analysis_language(spec.name), relative, imports
        )

    def _call_query_for(self, spec: LanguageSpec):
        cached = self._call_queries.get(spec.name)
        if cached is None:
            from tree_sitter import Query

            cached = Query(_grammar(spec.name), spec.call_query)
            self._call_queries[spec.name] = cached
        return cached

    def _parse_annotations(
        self,
        spec: LanguageSpec,
        relative: str,
        imports: list[ImportOccurrence],
        tree,
    ) -> list[AnnotationOccurrence]:
        if not spec.annotation_query:
            return []
        from tree_sitter import QueryCursor

        query = self._annotation_query_for(spec)
        found: list[AnnotationOccurrence] = []
        for node in QueryCursor(query).captures(tree.root_node).get("ann", ()):
            name = node.text.decode("utf-8", "replace").strip()
            if name:
                found.append(
                    AnnotationOccurrence(
                        name.rsplit(".", 1)[-1],
                        _analysis_language(spec.name),
                        relative,
                        node.start_point[0] + 1,
                        resolve_imported_symbol(
                            tree.root_node,
                            spec.name,
                            name,
                            imports,
                            before_byte=node.start_byte,
                            before_line=node.start_point[0] + 1,
                        ),
                        component_for_node(node),
                        function_for_node(node),
                    )
                )
        return found

    def _annotation_query_for(self, spec: LanguageSpec):
        cached = self._annotation_queries.get(spec.name)
        if cached is None:
            from tree_sitter import Query

            cached = Query(_grammar(spec.name), spec.annotation_query)
            self._annotation_queries[spec.name] = cached
        return cached

    def _parser_for(self, spec: LanguageSpec):
        cached = self._parsers.get(spec.name)
        if cached is None:
            from tree_sitter import Parser

            cached = Parser(_grammar(spec.name))
            self._parsers[spec.name] = cached
        return cached

    def _query_for(self, spec: LanguageSpec):
        cached = self._queries.get(spec.name)
        if cached is None:
            from tree_sitter import Query

            cached = Query(_grammar(spec.name), spec.query)
            self._queries[spec.name] = cached
        return cached


def _receiver_text(nodes) -> str | None:
    """The receiver, but only when it is a plain name or dotted chain.

    `a.b().c[0].d` is an expression, not an identity. Keeping it would make
    every call site its own value and match nothing, so it is dropped and the
    call falls back to its bare method name.
    """
    if not nodes:
        return None
    text = nodes[0].text.decode("utf-8", "replace").strip()
    if not text or len(text) > _MAX_RECEIVER or not _SIMPLE_RECEIVER.match(text):
        return None
    return text


def _import_bindings(language: str, module: str, module_node) -> tuple[str, ...]:
    if language == "python":
        statement = _ancestor(
            module_node, {"import_statement", "import_from_statement"}
        )
        if statement is not None and statement.type == "import_statement":
            item = module_node.parent
            if item is not None and item.type == "aliased_import":
                alias = item.child_by_field_name("alias")
                if alias is not None:
                    return (_node_text(alias),)
            return (module.split(".", 1)[0],)
        if statement is not None:
            found: list[str] = []
            for item in statement.children_by_field_name("name"):
                alias = item.child_by_field_name("alias")
                name = alias or item.child_by_field_name("name") or item
                value = _node_text(name)
                if value and value != "*":
                    found.append(value.split(".", 1)[0])
            return tuple(dict.fromkeys(found))
    if language in {"javascript", "typescript", "tsx"}:
        statement = _ancestor(module_node, {"import_statement"})
        if statement is not None:
            clause = next(
                (
                    child
                    for child in statement.named_children
                    if child.type in {"import_clause", "import_require_clause"}
                ),
                None,
            )
            return _javascript_import_bindings(clause)
        declarator = _ancestor(module_node, {"variable_declarator"})
        if declarator is not None:
            return _pattern_names(declarator.child_by_field_name("name"))
    if language in {"java", "csharp"} and not module.endswith(".*"):
        if language == "csharp":
            directive = _ancestor(module_node, {"using_directive"})
            alias = directive and directive.child_by_field_name("name")
            if alias is not None:
                return (_node_text(alias),)
        return (module.rsplit(".", 1)[-1],)
    return ()


def _ancestor(node, types: set[str]):
    current = node
    while current is not None and current.type not in types:
        current = current.parent
    return current


def _node_text(node) -> str:
    return node.text.decode("utf-8", "replace").strip()


def _javascript_import_bindings(clause) -> tuple[str, ...]:
    if clause is None:
        return ()
    if clause.type == "import_require_clause":
        identifier = next(
            (child for child in clause.named_children if child.type == "identifier"),
            None,
        )
        return (_node_text(identifier),) if identifier is not None else ()

    found: list[str] = []
    for child in clause.named_children:
        if child.type == "identifier":
            found.append(_node_text(child))
        elif child.type == "namespace_import":
            identifiers = [
                item for item in child.named_children if item.type == "identifier"
            ]
            if identifiers:
                found.append(_node_text(identifiers[-1]))
        elif child.type == "named_imports":
            for item in child.named_children:
                if item.type != "import_specifier":
                    continue
                binding = item.child_by_field_name("alias") or item.child_by_field_name(
                    "name"
                )
                if binding is not None:
                    found.append(_node_text(binding))
    return tuple(dict.fromkeys(found))


_FUNCTION_NODES = frozenset(
    {
        "function_definition",
        "lambda",
        "function_declaration",
        "function_expression",
        "generator_function_declaration",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)
_NAMED_DEFINITION_NODES = frozenset(
    {
        "function_definition",
        "class_definition",
        "function_declaration",
        "class_declaration",
    }
)
_ASSIGNMENT_NODES = {
    "assignment": "left",
    "augmented_assignment": "left",
    "named_expression": "left",
    "for_statement": "left",
    "variable_declarator": "name",
    "assignment_expression": "left",
}
_BINDING_PATTERN_NODES = frozenset(
    {
        "parameters",
        "formal_parameters",
        "default_parameter",
        "typed_parameter",
        "typed_default_parameter",
        "required_parameter",
        "optional_parameter",
        "rest_pattern",
        "list_splat",
        "dictionary_splat",
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "array_pattern",
        "object_pattern",
        "pair_pattern",
        "object_assignment_pattern",
    }
)


def _scope_key(node) -> tuple[str, int, int]:
    return node.type, node.start_byte, node.end_byte


def _pattern_names(node) -> tuple[str, ...]:
    if node is None:
        return ()
    if node.type == "identifier":
        return (_node_text(node),)
    selected = (
        node.child_by_field_name("pattern")
        or node.child_by_field_name("name")
        or node.child_by_field_name("left")
    )
    if selected is not None and selected is not node:
        return _pattern_names(selected)
    if node.type not in _BINDING_PATTERN_NODES:
        return ()
    found = [name for child in node.named_children for name in _pattern_names(child)]
    return tuple(dict.fromkeys(found))


def _binding_definitions(language: str, root):
    root_scope = _scope_key(root)
    if language not in {"python", "javascript", "typescript", "tsx"}:
        return {}, root_scope
    definitions: dict[str, list[tuple[int, tuple[str, int, int]]]] = {}

    def add(names: tuple[str, ...], line: int, scope) -> None:
        for name in names:
            definitions.setdefault(name, []).append((line, scope))

    stack = [(root, root_scope)]
    while stack:
        node, scope = stack.pop()
        child_scope = scope
        if node.type in _NAMED_DEFINITION_NODES:
            add(
                _pattern_names(node.child_by_field_name("name")),
                node.start_point[0] + 1,
                scope,
            )
        if node.type in _FUNCTION_NODES:
            child_scope = _scope_key(node)
            add(
                _pattern_names(node.child_by_field_name("parameters")),
                node.start_point[0] + 1,
                child_scope,
            )
        target_field = _ASSIGNMENT_NODES.get(node.type)
        if target_field is not None:
            add(
                _pattern_names(node.child_by_field_name(target_field)),
                node.start_point[0] + 1,
                scope,
            )
        stack.extend((child, child_scope) for child in reversed(node.named_children))
    return definitions, root_scope


def _call_scopes(node, root_scope) -> set[tuple[str, int, int]]:
    scopes = {root_scope}
    current = node.parent
    while current is not None:
        if current.type in _FUNCTION_NODES:
            scopes.add(_scope_key(current))
        current = current.parent
    return scopes


def _shadowed_import_bindings(
    language: str,
    call_node,
    receiver: str | None,
    method: str,
    imports: list[ImportOccurrence],
    definitions: dict[str, list[tuple[int, tuple[str, int, int]]]],
    root_scope,
) -> tuple[str, ...]:
    candidates = {method}
    if receiver:
        candidates.add(receiver.split(".", 1)[0])
    call_line = call_node.start_point[0] + 1
    scopes = _call_scopes(call_node, root_scope)
    shadowed: list[str] = []
    for name in sorted(candidates):
        import_lines = sorted(
            occurrence.line
            for occurrence in imports
            if name in occurrence.bindings and occurrence.line <= call_line
        )
        if not import_lines:
            continue
        latest_import = import_lines[-1]
        definition_lines = [
            line
            for line, scope in definitions.get(name, ())
            if scope in scopes
            and line not in import_lines
            and (line <= call_line or (language == "python" and scope != root_scope))
        ]
        if definition_lines and max(definition_lines) > latest_import:
            shadowed.append(name)
    return tuple(shadowed)


def _source_language(path: Path) -> tuple[str | None, str]:
    lowered = path.name.lower()
    for extension, language in _SOURCE_LANGUAGES.items():
        if lowered.endswith(extension):
            return language, extension
    return None, path.suffix.lower()


def _sloc(text: str, language: str) -> int:
    count = 0
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if in_block:
            if "*/" in stripped or "-->" in stripped:
                in_block = False
            continue
        if stripped.startswith(("/*", "<!--")):
            if not ("*/" in stripped[2:] or "-->" in stripped[4:]):
                in_block = True
            continue
        markers = (
            ("#",)
            if language == "python"
            else (("--",) if language == "sql" else ("//", "*"))
        )
        if stripped.startswith(markers):
            continue
        count += 1
    return count


def _is_test_path(relative: str) -> bool:
    parts = {part.lower() for part in Path(relative).parts[:-1]}
    stem = Path(relative).stem.lower()
    return (
        bool(parts & _TEST_PARTS)
        or stem.startswith("test_")
        or stem.endswith(("test", "spec"))
    )


def verify_grammars() -> None:
    """Load every grammar once, so a missing wheel is a startup failure.

    Without this, an absent grammar package raises ImportError inside `_parse_file`,
    which catches per file: every source file becomes `parse_error`, the run reports
    zero imports, and nothing looks broken. A repository that genuinely has no
    supported files produces the same numbers.
    """
    for spec in LANGUAGES:
        _grammar(spec.name)


def _grammar(name: str):
    """Load one grammar. Imported lazily so a checkout without the wheels still
    runs every code path that does not parse."""
    from tree_sitter import Language

    if name == "python":
        import tree_sitter_python as module

        return Language(module.language())
    if name == "java":
        import tree_sitter_java as module

        return Language(module.language())
    if name == "javascript":
        import tree_sitter_javascript as module

        return Language(module.language())
    if name in {"typescript", "tsx"}:
        import tree_sitter_typescript as module

        return Language(
            module.language_tsx() if name == "tsx" else module.language_typescript()
        )
    if name == "csharp":
        import tree_sitter_c_sharp as module

        return Language(module.language())
    raise ValueError(f"no grammar registered for {name}")


def walk_files(root: Path):
    """Depth-first over files, pruning excluded directories before descending."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            # Windows path ordering is case-insensitive while Linux ordering is
            # not. Evidence IDs must not change with the Worker host OS.
            entries = sorted(
                current.iterdir(), key=lambda entry: (entry.name.casefold(), entry.name)
            )
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                # A symlink can point outside the clone, or into it in a cycle.
                continue
            if entry.is_dir():
                if entry.name.lower() not in EXCLUDED_DIRECTORIES:
                    stack.append(entry)
            elif entry.is_file():
                yield entry
