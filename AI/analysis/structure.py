"""Conservative structural and receiver-binding facts from parsed source trees."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from operator import attrgetter

__all__ = [
    "BindingContext",
    "SyntaxOccurrence",
    "build_binding_context",
    "component_for_node",
    "extract_syntax",
    "function_for_node",
    "resolve_call_binding",
    "resolve_imported_symbol",
]


_SIMPLE_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_SIMPLE_PATH = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")
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
        "method_declaration",
        "constructor_declaration",
        "local_function_statement",
        "lambda_expression",
        "anonymous_method_expression",
    }
)
_TYPE_NODES = frozenset(
    {
        "class_definition",
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "record_declaration",
        "enum_declaration",
    }
)
_TYPE_ALIAS_NODES = frozenset({"type_alias_declaration"})
_CONDITIONAL_NODES = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "switch_statement",
        "switch_expression",
        "match_statement",
        "try_statement",
        "try_with_resources_statement",
        "catch_clause",
        "finally_clause",
        "conditional_expression",
    }
)


@dataclass(frozen=True)
class SyntaxOccurrence:
    """One grammar-backed source structure with an optional imported identity."""

    kind: str
    name: str
    language: str
    file: str
    line: int
    resolved_module: str | None = None
    component: str | None = None
    #: Nearest lexical callable. Kept separate because COMPONENT deliberately
    #: spans all methods in a class for framework-level composition rules.
    function: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8", "replace").strip()


def _name(node) -> str:
    named = node.child_by_field_name("name")
    return _text(named) if named is not None else ""


def _descendants(node, *, include_self: bool = False):
    stack = [node] if include_self else list(reversed(node.named_children))
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _inside_error(node) -> bool:
    current = node
    while current is not None:
        if current.is_error or current.is_missing or current.type == "ERROR":
            return True
        current = current.parent
    return False


def _root_name(value: str) -> str | None:
    cleaned = value.strip()
    if not cleaned or not _SIMPLE_PATH.fullmatch(cleaned):
        return None
    return cleaned.split(".", 1)[0]


def _component_id(prefix: str, node) -> str:
    name = _name(node)
    location = f"{node.start_point[0] + 1}:{node.start_point[1] + 1}"
    if name:
        return f"{prefix}:{name}@{location}"
    return f"unknown:{node.type}@{location}"


def component_for_node(node) -> str | None:
    """Return the nearest type or outer named-function scope for one AST node."""

    current = node
    outer_functions = []
    while current is not None:
        if current.type == "decorated_definition":
            definition = current.child_by_field_name("definition")
            if definition is not None:
                if definition.type in _TYPE_NODES:
                    return _component_id("class", definition)
                if definition.type in _FUNCTION_NODES:
                    outer_functions.append(definition)
        if current.type == "export_statement":
            declaration = current.child_by_field_name("declaration")
            if declaration is not None:
                if declaration.type in _TYPE_NODES:
                    return _component_id("class", declaration)
                if declaration.type in _TYPE_ALIAS_NODES:
                    return _component_id("type", declaration)
                if declaration.type in _FUNCTION_NODES:
                    outer_functions.append(declaration)
        if current.type in _TYPE_NODES:
            prefix = (
                "class"
                if current.type
                in {
                    "class_definition",
                    "class_declaration",
                }
                else "type"
            )
            return _component_id(prefix, current)
        if current.type in _TYPE_ALIAS_NODES:
            return _component_id("type", current)
        if current.type in _FUNCTION_NODES:
            outer_functions.append(current)
        current = current.parent
    if outer_functions:
        return _component_id("function", outer_functions[-1])
    return "module"


def _function_id(node) -> str:
    name = _name(node) or node.type
    location = f"{node.start_point[0] + 1}:{node.start_point[1] + 1}"
    return f"function:{name}@{location}"


def function_for_node(node) -> str | None:
    """Return the nearest callable without crossing a containing type boundary."""

    current = node
    while current is not None:
        if current.type == "decorated_definition":
            definition = current.child_by_field_name("definition")
            if definition is not None and definition.type in _FUNCTION_NODES:
                return _function_id(definition)
            if definition is not None and definition.type in _TYPE_NODES:
                return None
        if current.type == "export_statement":
            declaration = current.child_by_field_name("declaration")
            if declaration is not None and declaration.type in _FUNCTION_NODES:
                return _function_id(declaration)
            if declaration is not None and declaration.type in _TYPE_NODES:
                return None
        if current.type in _FUNCTION_NODES:
            return _function_id(current)
        if current.type in _TYPE_NODES:
            return None
        current = current.parent
    return None


def _module_index(
    imports: Iterable[object], *, before_line: int | None = None
) -> dict[str, str]:
    found: dict[str, set[str]] = {}
    for occurrence in imports:
        if before_line is not None and occurrence.line > before_line:
            continue
        for binding in occurrence.bindings:
            found.setdefault(binding, set()).add(occurrence.module)
    return {
        binding: next(iter(modules))
        for binding, modules in found.items()
        if len(modules) == 1
    }


def _local_declarations(
    root,
    language: str,
    *,
    before_byte: int,
    imported_lines: dict[str, set[int]],
) -> set[str]:
    declarations = set()
    named_types = {
        "class_definition",
        "class_declaration",
        "interface_declaration",
        "annotation_type_declaration",
        "enum_declaration",
        "record_declaration",
        "struct_declaration",
        "type_alias_declaration",
    }
    named_values = {
        "function_definition",
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
    }
    for node in _descendants(root):
        if node.start_byte >= before_byte or _inside_error(node):
            continue
        if node.type in named_types | named_values:
            value = _name(node)
            if value and node.start_point[0] + 1 not in imported_lines.get(
                value, set()
            ):
                declarations.add(value)
        elif node.type in {"assignment", "variable_declarator"} and language in {
            "python",
            "javascript",
            "typescript",
            "tsx",
        }:
            field = "left" if node.type == "assignment" else "name"
            target = node.child_by_field_name(field)
            if target is not None and target.type == "identifier":
                value = _text(target)
                if node.start_point[0] + 1 not in imported_lines.get(value, set()):
                    declarations.add(value)
    return declarations


def resolve_imported_symbol(
    root,
    language: str,
    name: str,
    imports: Iterable[object],
    *,
    before_byte: int,
    before_line: int,
) -> str | None:
    """Resolve one source symbol only when one import owns it unambiguously."""

    binding = _root_name(name)
    visible_imports = tuple(
        occurrence for occurrence in imports if occurrence.line <= before_line
    )
    imported_lines: dict[str, set[int]] = {}
    for occurrence in visible_imports:
        for imported in occurrence.bindings:
            imported_lines.setdefault(imported, set()).add(occurrence.line)
    if not binding or binding in _local_declarations(
        root,
        language,
        before_byte=before_byte,
        imported_lines=imported_lines,
    ):
        return None
    resolved = _module_index(visible_imports).get(binding)
    if resolved:
        return resolved
    if language in {"java", "csharp"} and "." in name and _SIMPLE_PATH.fullmatch(name):
        return name
    return None


def extract_syntax(root, language: str, file: str, imports: Iterable[object]):
    """Return stable semantic nodes; never infer a technology from a name."""

    found: dict[tuple[str, str, int], SyntaxOccurrence] = {}

    def emit(kind: str, name: str, node, *, identity: str | None = None) -> None:
        value = name.strip()
        if not value or len(value) > 120 or _inside_error(node):
            return
        occurrence = SyntaxOccurrence(
            kind=kind,
            name=value,
            language=language,
            file=file,
            line=node.start_point[0] + 1,
            resolved_module=resolve_imported_symbol(
                root,
                language,
                identity or value,
                imports,
                before_byte=node.start_byte,
                before_line=node.start_point[0] + 1,
            ),
            component=component_for_node(node),
            function=function_for_node(node),
        )
        found.setdefault((kind, value, occurrence.line), occurrence)

    for node in _descendants(root):
        if _inside_error(node):
            continue
        kind = node.type
        text = _text(node)

        if language == "python":
            if kind == "class_definition":
                emit("CLASS_DECLARATION", _name(node), node)
                supers = node.child_by_field_name("superclasses")
                if supers is not None:
                    for base in supers.named_children:
                        value = _text(base)
                        if _SIMPLE_PATH.fullmatch(value):
                            emit("CLASS_EXTENDS", value, base)
            elif kind == "function_definition":
                emit(
                    "ASYNC_FUNCTION_DECLARATION"
                    if text.startswith("async ")
                    else "FUNCTION_DECLARATION",
                    _name(node),
                    node,
                )
            elif kind == "decorated_definition":
                definition = node.child_by_field_name("definition")
                if definition is not None:
                    emit("DECORATED_DEFINITION", _name(definition), node)
            elif kind == "with_statement":
                emit(
                    "ASYNC_WITH_STATEMENT"
                    if text.startswith("async ")
                    else "WITH_STATEMENT",
                    "with",
                    node,
                )
            elif kind == "for_statement" and text.startswith("async "):
                emit("ASYNC_FOR_STATEMENT", "for", node)
            elif kind.endswith("_comprehension"):
                emit("COMPREHENSION", kind.removesuffix("_comprehension"), node)
            elif kind == "try_statement":
                emit("TRY_STATEMENT", "try", node)
                if any(child.type == "finally_clause" for child in node.named_children):
                    emit("TRY_FINALLY", "finally", node)
            elif kind in {"yield", "yield_expression"}:
                emit("YIELD_EXPRESSION", "yield", node)

        elif language == "java":
            if kind == "class_declaration":
                emit("CLASS_DECLARATION", _name(node), node)
                superclass = node.child_by_field_name("superclass")
                if superclass is not None:
                    for base in _descendants(superclass):
                        if base.type in {"type_identifier", "scoped_type_identifier"}:
                            emit("CLASS_EXTENDS", _text(base), base)
                            break
            elif kind == "interface_declaration":
                emit("INTERFACE_DECLARATION", _name(node), node)
            elif kind in {"super_interfaces", "extends_interfaces"}:
                for base in _descendants(node):
                    if base.type in {"type_identifier", "scoped_type_identifier"}:
                        emit("IMPLEMENTS_TYPE", _text(base), base)
            elif kind in {"method_declaration", "constructor_declaration"}:
                emit("METHOD_DECLARATION", _name(node), node)
            if (
                kind
                in {
                    "class_declaration",
                    "interface_declaration",
                    "method_declaration",
                    "constructor_declaration",
                }
                and node.child_by_field_name("type_parameters") is not None
            ):
                emit("GENERIC_DECLARATION", _name(node), node)
            elif kind == "lambda_expression":
                emit("LAMBDA_EXPRESSION", "lambda", node)
            elif kind == "try_with_resources_statement":
                emit("TRY_WITH_RESOURCES", "try", node)
            elif kind == "try_statement":
                emit("TRY_STATEMENT", "try", node)
                if any(child.type == "finally_clause" for child in node.named_children):
                    emit("TRY_FINALLY", "finally", node)

        elif language in {"javascript", "typescript", "tsx"}:
            if kind == "class_declaration":
                emit("CLASS_DECLARATION", _name(node), node)
                heritage = next(
                    (
                        child
                        for child in node.named_children
                        if child.type == "class_heritage"
                    ),
                    None,
                )
                if heritage is not None:
                    for clause in heritage.named_children:
                        if clause.type not in {"extends_clause", "implements_clause"}:
                            continue
                        for base in clause.named_children:
                            emit(
                                "CLASS_EXTENDS"
                                if clause.type == "extends_clause"
                                else "IMPLEMENTS_TYPE",
                                _text(base),
                                base,
                            )
            elif kind == "interface_declaration":
                emit("INTERFACE_DECLARATION", _name(node), node)
                for clause in node.named_children:
                    if clause.type == "extends_type_clause":
                        for base in clause.named_children:
                            emit("INTERFACE_EXTENDS", _text(base), base)
            elif kind == "type_alias_declaration":
                emit("TYPE_ALIAS_DECLARATION", _name(node), node)
            elif kind in {"conditional_type", "mapped_type_clause", "infer_type"}:
                owner = node.parent
                while owner is not None and owner.type not in {
                    "type_alias_declaration",
                    "interface_declaration",
                }:
                    owner = owner.parent
                emit(
                    {
                        "conditional_type": "CONDITIONAL_TYPE",
                        "mapped_type_clause": "MAPPED_TYPE",
                        "infer_type": "INFER_TYPE",
                    }[kind],
                    _name(owner) if owner is not None else kind,
                    node,
                )
            elif kind in {
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            }:
                if kind == "generator_function_declaration":
                    declaration_kind = (
                        "ASYNC_GENERATOR_FUNCTION_DECLARATION"
                        if text.startswith("async ")
                        else "GENERATOR_FUNCTION_DECLARATION"
                    )
                else:
                    declaration_kind = (
                        "ASYNC_FUNCTION_DECLARATION"
                        if text.startswith("async ")
                        else "FUNCTION_DECLARATION"
                    )
                emit(declaration_kind, _name(node), node)
            elif kind == "export_statement":
                declaration = node.child_by_field_name("declaration")
                if declaration is not None and declaration.type in {
                    "function_declaration",
                    "generator_function_declaration",
                }:
                    emit("EXPORTED_FUNCTION", _name(declaration), declaration)
                elif declaration is not None and declaration.type in {
                    "lexical_declaration",
                    "variable_declaration",
                }:
                    for item in declaration.named_children:
                        if item.type == "variable_declarator":
                            emit("EXPORTED_BINDING", _name(item), item)
            elif kind in {"jsx_element", "jsx_self_closing_element"}:
                opening = (
                    node.child_by_field_name("open_tag")
                    if kind == "jsx_element"
                    else node
                )
                name = opening and opening.child_by_field_name("name")
                if name is not None:
                    emit("JSX_ELEMENT", _text(name), name)
            elif kind == "await_expression":
                emit("AWAIT_EXPRESSION", "await", node)
            elif kind == "for_in_statement" and text.startswith("for await "):
                emit("FOR_AWAIT_STATEMENT", "for", node)
            elif kind in {"yield_expression", "yield"}:
                emit("YIELD_EXPRESSION", "yield", node)
            elif kind == "try_statement":
                emit("TRY_STATEMENT", "try", node)
                if any(child.type == "finally_clause" for child in node.named_children):
                    emit("TRY_FINALLY", "finally", node)
            elif kind == "arrow_function":
                emit("LAMBDA_EXPRESSION", "lambda", node)

            if (
                kind
                in {
                    "class_declaration",
                    "interface_declaration",
                    "type_alias_declaration",
                    "function_declaration",
                    "generator_function_declaration",
                    "method_definition",
                    "arrow_function",
                }
                and node.child_by_field_name("type_parameters") is not None
            ):
                emit("GENERIC_DECLARATION", _name(node) or "anonymous", node)

        elif language == "csharp":
            if kind == "class_declaration":
                emit("CLASS_DECLARATION", _name(node), node)
                base_list = next(
                    (
                        child
                        for child in node.named_children
                        if child.type == "base_list"
                    ),
                    None,
                )
                if base_list is not None:
                    for base in base_list.named_children:
                        emit("BASE_TYPE", _text(base), base)
            elif kind == "interface_declaration":
                emit("INTERFACE_DECLARATION", _name(node), node)
            elif kind in {"method_declaration", "constructor_declaration"}:
                emit(
                    "ASYNC_METHOD_DECLARATION"
                    if any(_text(child) == "async" for child in node.named_children)
                    else "METHOD_DECLARATION",
                    _name(node),
                    node,
                )
            elif kind == "query_expression":
                emit("QUERY_EXPRESSION", "query", node)
            elif kind == "await_expression":
                emit("AWAIT_EXPRESSION", "await", node)
            elif kind == "foreach_statement" and text.startswith("await "):
                emit("AWAIT_FOREACH_STATEMENT", "foreach", node)
            elif kind == "local_declaration_statement" and text.startswith(
                "await using "
            ):
                emit("AWAIT_USING_DECLARATION", "using", node)
            elif kind == "using_statement" and text.startswith("await using"):
                emit("AWAIT_USING_STATEMENT", "using", node)
            elif kind == "yield_statement":
                emit("YIELD_STATEMENT", "yield", node)
            elif kind in {"lambda_expression", "anonymous_method_expression"}:
                emit("LAMBDA_EXPRESSION", "lambda", node)
            elif kind == "try_statement":
                emit("TRY_STATEMENT", "try", node)
                if any(child.type == "finally_clause" for child in node.named_children):
                    emit("TRY_FINALLY", "finally", node)

            if (
                kind
                in {
                    "class_declaration",
                    "interface_declaration",
                    "method_declaration",
                }
                and node.child_by_field_name("type_parameters") is not None
            ):
                emit("GENERIC_DECLARATION", _name(node), node)

    return tuple(
        sorted(
            found.values(),
            key=lambda item: (item.file, item.line, item.kind, item.name),
        )
    )


def _scope_chain(node):
    found = []
    current = node.parent
    while current is not None:
        if current.type in _FUNCTION_NODES | _TYPE_NODES or current.parent is None:
            found.append(current)
        current = current.parent
    return tuple(found)


def _scope_key(node) -> tuple[str, int, int]:
    return node.type, node.start_byte, node.end_byte


def _parameter_names(function) -> set[str]:
    parameters = function.child_by_field_name("parameters")
    if parameters is None:
        return set()
    found = set()
    for node in _descendants(parameters, include_self=True):
        if node.type.endswith("parameter"):
            name = node.child_by_field_name("name")
            if name is not None and _SIMPLE_NAME.fullmatch(_text(name)):
                found.add(_text(name))
    if not found:
        found.update(
            _text(node)
            for node in parameters.named_children
            if node.type == "identifier" and _SIMPLE_NAME.fullmatch(_text(node))
        )
    return found


def _expression_root(node) -> str | None:
    if node is None:
        return None
    if node.type in {"identifier", "type_identifier"}:
        return _text(node)
    for field in ("function", "constructor", "object", "expression", "type"):
        child = node.child_by_field_name(field)
        if child is not None:
            root = _expression_root(child)
            if root:
                return root
    if node.type in {"generic_type", "scoped_type_identifier", "qualified_name"}:
        for child in node.named_children:
            root = _expression_root(child)
            if root:
                return root
    return None


def _write(node):
    if node.type in {"assignment", "augmented_assignment", "named_expression"}:
        left = node.child_by_field_name("left")
        if left is None or left.type != "identifier":
            return None
        right = node.child_by_field_name("right")
        return _text(left), _expression_root(right)
    if node.type in {"assignment_expression", "augmented_assignment_expression"}:
        left = node.child_by_field_name("left")
        if left is None or left.type != "identifier":
            return None
        return _text(left), _expression_root(node.child_by_field_name("right"))
    if node.type != "variable_declarator":
        return None
    name = node.child_by_field_name("name")
    if name is None or name.type != "identifier":
        return None
    declaration = node.parent
    declared_type = declaration and declaration.child_by_field_name("type")
    root = _expression_root(declared_type)
    return _text(name), root or _expression_root(node.child_by_field_name("value"))


@dataclass(frozen=True)
class _BindingWrite:
    position: int
    line: int
    source: str | None
    conditional: bool


@dataclass(frozen=True)
class BindingContext:
    """One file's immutable lexical binding index."""

    imports_by_name: dict[str, tuple[tuple[int, str], ...]]
    parameters_by_scope: dict[tuple[str, int, int], frozenset[str]]
    writes_by_scope_name: dict[
        tuple[tuple[str, int, int], str], tuple[_BindingWrite, ...]
    ]

    def visible_imports(self, line: int) -> dict[str, str]:
        found = {}
        for name, entries in self.imports_by_name.items():
            modules = {module for import_line, module in entries if import_line <= line}
            if len(modules) == 1:
                found[name] = next(iter(modules))
        return found

    def import_lines(self, name: str, line: int) -> set[int]:
        return {
            import_line
            for import_line, _module in self.imports_by_name.get(name, ())
            if import_line <= line
        }

    def writes_before(
        self, scope, name: str, position: int
    ) -> tuple[_BindingWrite, ...]:
        writes = self.writes_by_scope_name.get((_scope_key(scope), name), ())
        boundary = bisect_left(writes, position, key=attrgetter("position"))
        return writes[:boundary]


def build_binding_context(root, imports: Iterable[object]) -> BindingContext:
    """Index parameters and writes once for all calls in one parsed file."""

    imports_by_name: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for occurrence in imports:
        for binding in occurrence.bindings:
            imports_by_name[binding].append((occurrence.line, occurrence.module))

    parameters_by_scope: dict[tuple[str, int, int], frozenset[str]] = {}
    writes_by_scope_name: dict[
        tuple[tuple[str, int, int], str], list[_BindingWrite]
    ] = defaultdict(list)

    def index_scope(scope) -> None:
        scope_key = _scope_key(scope)
        parameters_by_scope[scope_key] = frozenset(
            _parameter_names(scope) if scope.type in _FUNCTION_NODES else ()
        )
        stack = [(child, False) for child in reversed(scope.named_children)]
        while stack:
            node, inherited_conditional = stack.pop()
            if node.type in _FUNCTION_NODES | _TYPE_NODES:
                index_scope(node)
                continue
            conditional = inherited_conditional or node.type in _CONDITIONAL_NODES
            write = _write(node)
            if write is not None:
                target, source = write
                writes_by_scope_name[(scope_key, target)].append(
                    _BindingWrite(
                        position=node.start_byte,
                        line=node.start_point[0] + 1,
                        source=source,
                        conditional=inherited_conditional,
                    )
                )
            stack.extend(
                (child, conditional) for child in reversed(node.named_children)
            )

    index_scope(root)
    return BindingContext(
        imports_by_name={
            name: tuple(sorted(entries)) for name, entries in imports_by_name.items()
        },
        parameters_by_scope=parameters_by_scope,
        writes_by_scope_name={
            key: tuple(sorted(writes, key=attrgetter("position")))
            for key, writes in writes_by_scope_name.items()
        },
    )


def resolve_call_binding(
    root,
    call_node,
    receiver: str | None,
    receiver_node,
    method: str,
    imports: Iterable[object],
    shadowed_bindings: Iterable[str],
    context: BindingContext | None = None,
) -> str | None:
    """Trace one receiver to one import or return None on any ambiguity."""

    if context is None:
        context = build_binding_context(root, imports)
    call_line = call_node.start_point[0] + 1
    module_by_name = context.visible_imports(call_line)
    imported = set(module_by_name)
    shadowed = set(shadowed_bindings)
    direct = (
        _expression_root(receiver_node) or (receiver or "").split(".", 1)[0] or method
    )
    if direct in imported and direct not in shadowed:
        import_lines = context.import_lines(direct, call_line)
        for scope in _scope_chain(call_node):
            scope_key = _scope_key(scope)
            if direct in context.parameters_by_scope.get(scope_key, ()):
                return None
            if any(
                write.line not in import_lines
                for write in context.writes_before(scope, direct, call_node.start_byte)
            ):
                return None
        return direct
    if not receiver:
        return None
    target = receiver.split(".", 1)[0]
    if not _SIMPLE_NAME.fullmatch(target):
        return None

    writes: list[tuple[int, str, bool]] = []
    for scope in _scope_chain(call_node):
        scope_key = _scope_key(scope)
        if target in context.parameters_by_scope.get(scope_key, ()):
            return None
        for write in context.writes_before(scope, target, call_node.start_byte):
            source = write.source if write.source in imported else ""
            writes.append((write.position, source, write.conditional))
    unique = {
        (position, source, conditional) for position, source, conditional in writes
    }
    if len(unique) != 1:
        return None
    _, source, conditional = next(iter(unique))
    if conditional or not source:
        return None
    return source
