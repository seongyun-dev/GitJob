"""Per-language import extraction rules for tree-sitter.

### Why tree-sitter and not the regexes already in `github/public_analysis.py`

That module extracts imports too, and it works, but it pays for it: it masks
JavaScript strings, comments and template literals by hand before matching, and
it has a dedicated scanner for Java text blocks. Every one of those is a grammar
rule re-implemented in a regex. A parser already knows where a comment ends, so
`import` inside a string or a commented-out block never reaches these queries.

The other reason is position. Evidence has to name a file and a line
(`docs/be/README.md` section 8), and a parse tree carries that for free.

### The queries are deliberately narrow

They capture the *module path*, not the whole statement. What matters later is
matching `org.springframework.boot` against the technology registry's
`IMPORT_PATH` mappings, so anything else in the statement is noise.

Relative imports are left out on purpose. `from .models import X` and
`import './styles.css'` point inside the repository being analyzed; they say
nothing about which technologies it uses.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LANGUAGES", "LanguageSpec", "spec_for_path"]


@dataclass(frozen=True)
class LanguageSpec:
    """One grammar, the files it claims, and how to read imports out of it."""

    name: str
    #: Matches `ImportEcosystem` in docs/data/contracts/technology-registry-v1.schema.json,
    #: so occurrences can be handed to the registry without a second lookup table.
    ecosystem: str
    extensions: tuple[str, ...]
    query: str
    #: Set when a pattern matches more calls than it should. `require` shares its
    #: shape with every other one-string-argument call, so the callee is captured
    #: and compared instead of trusted.
    guard_capture: str | None = None
    guard_values: tuple[str, ...] = ()
    #: Captures `@method` (the name being called) and optionally `@recv` (what it
    #: is called on). Empty for a language whose calls are not extracted yet.
    call_query: str = ""
    #: Captures the semantic name of an annotation/decorator. The parse tree,
    #: rather than a regex, keeps comment and string contents out.
    annotation_query: str = ""


#: Why calls are captured as written rather than resolved.
#:
#: `kafkaTemplate.send(...)` only means Kafka if `kafkaTemplate` is a
#: `KafkaTemplate`, and knowing that needs type resolution -- a compiler, not a
#: parser. What a parser can give is the text: the method name, and the
#: expression it was called on.
#:
#: That is enough when the method name is itself distinctive. `useState`,
#: `opsForValue`, `read_csv`, `backward`, `assertThrows` belong to one library
#: each. It is not enough for `send`, `get` or `run`, so rules that want those
#: have to qualify them -- `SpringApplication.run` -- and accept that a variable
#: named differently is missed. Missing a signal is the acceptable error here;
#: claiming a level the code does not support is not.
_PYTHON = LanguageSpec(
    name="python",
    ecosystem="PYTHON",
    extensions=(".py", ".pyi"),
    # `import a.b` and `from a.b import c` both land on dotted_name; the aliased
    # form nests it one level deeper. `from . import x` uses relative_import,
    # which none of these patterns reach.
    query="""
    (import_statement name: (dotted_name) @m)
    (import_statement name: (aliased_import name: (dotted_name) @m))
    (import_from_statement module_name: (dotted_name) @m)
    """,
    # `read_csv(...)` and `pd.read_csv(...)`. Capturing `@recv` as written is how
    # `np.array` stays distinguishable from a local function named `array`.
    call_query="""
    (call function: (identifier) @method)
    (call function: (attribute object: (_) @recv attribute: (identifier) @method))
    """,
    annotation_query="""
    (decorator (identifier) @ann)
    (decorator (call function: (identifier) @ann))
    """,
)

_JAVA = LanguageSpec(
    name="java",
    ecosystem="JAVA",
    extensions=(".java",),
    # Covers `import a.b.C;`, `import static a.b.C.d;` and `import a.b.*;`.
    # The bare identifier case is a default-package import, which is rare but
    # cheap to accept.
    query="""
    (import_declaration [(scoped_identifier) (identifier)] @m)
    """,
    # An unqualified `foo()` inside a class is still a method_invocation, just
    # without an object; the second pattern keeps those.
    call_query="""
    (method_invocation object: (_) @recv name: (identifier) @method)
    (method_invocation !object name: (identifier) @method)
    """,
    annotation_query="""
    (marker_annotation name: (identifier) @ann)
    (annotation name: (identifier) @ann)
    """,
)

_JAVASCRIPT_CALLS = """
(call_expression function: (identifier) @method)
(call_expression function: (member_expression object: (_) @recv property: (property_identifier) @method))
"""


_JAVASCRIPT_QUERY = """
(import_statement source: (string (string_fragment) @m))
(export_statement source: (string (string_fragment) @m))
(call_expression function: (identifier) @fn arguments: (arguments (string (string_fragment) @m)))
(call_expression function: (import) arguments: (arguments (string (string_fragment) @m)))
"""

_TYPESCRIPT_QUERY = (
    _JAVASCRIPT_QUERY
    + """
(import_require_clause (string (string_fragment) @m))
"""
)

_JAVASCRIPT = LanguageSpec(
    name="javascript",
    ecosystem="JAVASCRIPT",
    extensions=(".js", ".jsx", ".mjs", ".cjs"),
    query=_JAVASCRIPT_QUERY,
    call_query=_JAVASCRIPT_CALLS,
    guard_capture="fn",
    guard_values=("require",),
    annotation_query="""
    (decorator (identifier) @ann)
    (decorator (call_expression function: (identifier) @ann))
    """,
)

# TypeScript is a separate grammar but the same package ecosystem: `import
# {x} from "react"` resolves through npm either way, so occurrences from both
# are looked up in the same registry mappings.
_TYPESCRIPT = LanguageSpec(
    name="typescript",
    ecosystem="JAVASCRIPT",
    extensions=(".ts", ".mts", ".cts"),
    query=_TYPESCRIPT_QUERY,
    call_query=_JAVASCRIPT_CALLS,
    guard_capture="fn",
    guard_values=("require",),
    annotation_query="""
    (decorator (identifier) @ann)
    (decorator (call_expression function: (identifier) @ann))
    """,
)

_TSX = LanguageSpec(
    name="tsx",
    ecosystem="JAVASCRIPT",
    extensions=(".tsx",),
    query=_TYPESCRIPT_QUERY,
    call_query=_JAVASCRIPT_CALLS,
    guard_capture="fn",
    guard_values=("require",),
    annotation_query="""
    (decorator (identifier) @ann)
    (decorator (call_expression function: (identifier) @ann))
    """,
)

_CSHARP = LanguageSpec(
    name="csharp",
    ecosystem="DOTNET",
    extensions=(".cs",),
    # Aliases put their local identifier in the `name` field, while their target
    # is the following qualified_name/identifier. Non-alias directives have no
    # `name` field, so the two patterns cannot capture a local alias as a module.
    query="""
    (using_directive
        name: (identifier)
        "="
        [(qualified_name) (identifier)] @m)
    (using_directive
        !name
        [(qualified_name) (identifier)] @m)
    """,
    call_query="""
    (invocation_expression function: (identifier) @method)
    (invocation_expression function: (member_access_expression
        expression: (_) @recv name: (identifier) @method))
    """,
    annotation_query="""
    (attribute name: (identifier) @ann)
    """,
)

LANGUAGES: tuple[LanguageSpec, ...] = (
    _PYTHON,
    _JAVA,
    _JAVASCRIPT,
    _TYPESCRIPT,
    _TSX,
    _CSHARP,
)

_BY_EXTENSION = {extension: spec for spec in LANGUAGES for extension in spec.extensions}


def spec_for_path(path: str) -> LanguageSpec | None:
    """Language for a file name, or `None` when nothing here parses it."""

    lowered = path.lower()
    for extension, spec in _BY_EXTENSION.items():
        if lowered.endswith(extension):
            return spec
    return None
