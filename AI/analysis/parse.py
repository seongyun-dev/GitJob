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

__all__ = [
    "EXCLUDED_DIRECTORIES",
    "CallOccurrence",
    "ImportOccurrence",
    "ParseReport",
    "RepositoryParser",
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
        "node_modules",
        "obj",
        "out",
        "target",
        "vendor",
        "venv",
    }
)

#: Bundled or minified output. One line, machine written, and its imports are
#: whatever the bundler inlined rather than what anyone wrote.
EXCLUDED_SUFFIXES = (".min.js", ".min.ts", ".bundle.js", ".d.ts")


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


#: A receiver longer than this is an expression, not a name. `a.b().c[0].d`
#: says nothing about which library `d` belongs to, and keeping it would make
#: every call site its own value.
_MAX_RECEIVER = 60
_SIMPLE_RECEIVER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")


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
    _parsers: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _queries: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _call_queries: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )

    def parse_repository(self, root: Path) -> ParseReport:
        occurrences: list[ImportOccurrence] = []
        calls: list[CallOccurrence] = []
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
            spec = spec_for_path(relative)
            if spec is None:
                skipped["unsupported_language"] += 1
                continue
            if relative.lower().endswith(EXCLUDED_SUFFIXES):
                skipped["generated_or_minified"] += 1
                continue

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

            try:
                found = self._parse_file(spec, source, relative)
                called = self._parse_calls(spec, source, relative)
            except Exception as error:  # noqa: BLE001 - one bad file is not a failed repository
                log.debug("could not parse %s: %s", relative, error)
                skipped["parse_error"] += 1
                continue

            files_parsed += 1
            bytes_parsed += size
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
                if reason not in {"occurrence_limit", "call_limit"}
            ),
            bytes_parsed=bytes_parsed,
            calls=tuple(calls),
            skipped_reasons=dict(skipped),
        )

    def _parse_file(
        self, spec: LanguageSpec, source: bytes, relative: str
    ) -> list[ImportOccurrence]:
        from tree_sitter import QueryCursor

        parser = self._parser_for(spec)
        query = self._query_for(spec)
        tree = parser.parse(source)

        found: list[ImportOccurrence] = []
        # matches(), not captures(): a pattern that captures both the callee and
        # the argument needs them paired, and captures() flattens that away.
        for _pattern, captures in QueryCursor(query).matches(tree.root_node):
            if spec.guard_capture and spec.guard_capture in captures:
                names = {node.text.decode("utf-8", "replace") for node in captures[spec.guard_capture]}
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
                        language=spec.name,
                        ecosystem=spec.ecosystem,
                        file=relative,
                        # tree-sitter rows are 0-based; editors and permalinks
                        # are not.
                        line=node.start_point[0] + 1,
                    )
                )
        return found

    def _parse_calls(
        self, spec: LanguageSpec, source: bytes, relative: str
    ) -> list[CallOccurrence]:
        """Method and function calls, as written.

        Nothing here is resolved. `kafkaTemplate.send(...)` is recorded as
        `kafkaTemplate.send`, and whether that means Kafka is a question for the
        registry -- which answers it by naming methods distinctive enough that
        the receiver does not matter (`opsForValue`, `useState`, `read_csv`).
        """
        if not spec.call_query:
            return []
        from tree_sitter import QueryCursor

        parser = self._parser_for(spec)
        query = self._call_query_for(spec)
        tree = parser.parse(source)

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
            receiver = _receiver_text(captures.get("recv", ()))
            found.append(
                CallOccurrence(
                    callee=f"{receiver}.{method}" if receiver else method,
                    method=method,
                    receiver=receiver,
                    language=spec.name,
                    ecosystem=spec.ecosystem,
                    file=relative,
                    line=node.start_point[0] + 1,
                )
            )
        return found

    def _call_query_for(self, spec: LanguageSpec):
        cached = self._call_queries.get(spec.name)
        if cached is None:
            from tree_sitter import Query

            cached = Query(_grammar(spec.name), spec.call_query)
            self._call_queries[spec.name] = cached
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
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                # A symlink can point outside the clone, or into it in a cycle.
                continue
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIRECTORIES:
                    stack.append(entry)
            elif entry.is_file():
                yield entry
