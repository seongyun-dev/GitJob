"""Import extraction against real grammars.

tree-sitter is used for real. The reason to prefer it over the regexes in
`github/public_analysis.py` is precisely that it knows where a comment or a
string ends, and a mocked parser would assert nothing about that.
"""

from __future__ import annotations

import pytest

from analysis.parse import RepositoryParser

pytest.importorskip("tree_sitter", reason="tree-sitter wheels are not installed")


def repo(tmp_path, files: dict[str, str]):
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def modules(report, language: str | None = None) -> set[str]:
    return {
        item.module
        for item in report.occurrences
        if language is None or item.language == language
    }


def test_reads_python_imports_including_aliases_and_from_forms(tmp_path):
    root = repo(
        tmp_path,
        {
            "app.py": (
                "import os\n"
                "import kafka.admin as admin\n"
                "from fastapi import FastAPI\n"
                "from sqlalchemy.orm import Session\n"
            )
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"os", "kafka.admin", "fastapi", "sqlalchemy.orm"}


def test_relative_python_imports_are_not_technologies(tmp_path):
    # `from .models import X` points inside the repository being analyzed.
    root = repo(
        tmp_path,
        {"pkg/a.py": "from . import sibling\nfrom .models import X\nimport redis\n"},
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"redis"}


def test_reads_java_imports_including_static_and_wildcard(tmp_path):
    root = repo(
        tmp_path,
        {
            "Main.java": (
                "package com.example;\n"
                "import org.springframework.boot.SpringApplication;\n"
                "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
                "import org.apache.kafka.clients.producer.*;\n"
            )
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {
        "org.springframework.boot.SpringApplication",
        "org.junit.jupiter.api.Assertions.assertEquals",
        "org.apache.kafka.clients.producer",
    }


def test_java_import_inside_a_text_block_is_not_an_import(tmp_path):
    # The regex extractor needed a dedicated text-block scanner for this.
    root = repo(
        tmp_path,
        {
            "Doc.java": (
                "package p;\n"
                "import real.Thing;\n"
                "class Doc {\n"
                '  String sample = """\n'
                "      import fake.NotAnImport;\n"
                '      """;\n'
                "}\n"
            )
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"real.Thing"}


def test_commented_out_imports_are_not_counted(tmp_path):
    root = repo(
        tmp_path,
        {
            "a.py": "# import commented_out\nimport real_one\n",
            "B.java": "package p;\n// import fake.Commented;\nimport real.Two;\n",
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"real_one", "real.Two"}


def test_reads_javascript_static_dynamic_and_require(tmp_path):
    root = repo(
        tmp_path,
        {
            "index.js": (
                "import React from 'react';\n"
                "const fs = require('node:fs');\n"
                "export * from './local';\n"
                "export {a} from '@scope/pkg';\n"
                "const lazy = await import('chart.js');\n"
            )
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"react", "node:fs", "@scope/pkg", "chart.js"}


def test_a_one_string_argument_call_is_not_a_require(tmp_path):
    # require() shares its shape with t('key'), describe('x') and friends, so
    # the callee is checked rather than the shape.
    root = repo(
        tmp_path,
        {
            "i18n.js": "t('welcome.title');\ndescribe('suite', () => {});\nrequire('real');\n"
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"real"}


def test_javascript_import_inside_a_string_is_not_an_import(tmp_path):
    root = repo(
        tmp_path,
        {
            "s.js": (
                "const snippet = \"import evil from 'not-real'\";\n"
                "const tpl = `import alsoEvil from 'nope'`;\n"
                "import real from 'actually-real';\n"
            )
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"actually-real"}


def test_typescript_and_tsx_share_the_javascript_ecosystem(tmp_path):
    root = repo(
        tmp_path,
        {
            "a.ts": "import type {A} from 'zod';\n",
            "b.tsx": "import {useState} from 'react';\n",
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"zod", "react"}
    assert {item.ecosystem for item in report.occurrences} == {"JAVASCRIPT"}


def test_typescript_import_equals_collects_the_required_module(tmp_path):
    root = repo(tmp_path, {"app.ts": "import express = require('express');\n"})

    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"express"}


def test_reads_csharp_using_directives(tmp_path):
    root = repo(
        tmp_path,
        {
            "P.cs": "using System.Text.Json;\nglobal using Microsoft.Extensions.Logging;\n"
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"System.Text.Json", "Microsoft.Extensions.Logging"}
    assert {item.ecosystem for item in report.occurrences} == {"DOTNET"}


def test_csharp_using_alias_collects_only_the_target_namespace(tmp_path):
    root = repo(
        tmp_path,
        {
            "Aliases.cs": (
                "using Db = Company.Storage;\n"
                "using Single = Storage;\n"
                "using System;\n"
                "using static Company.Tools.Factory;\n"
                "global using Microsoft.Extensions.Logging;\n"
            )
        },
    )

    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {
        "Company.Storage",
        "Storage",
        "System",
        "Company.Tools.Factory",
        "Microsoft.Extensions.Logging",
    }


def test_every_occurrence_carries_a_file_and_a_one_based_line(tmp_path):
    # Evidence links to a permalink; an aggregate count cannot.
    root = repo(tmp_path, {"src/app.py": "import first\n\nimport second\n"})
    report = RepositoryParser().parse_repository(root)

    located = {(item.module, item.file, item.line) for item in report.occurrences}
    assert located == {("first", "src/app.py", 1), ("second", "src/app.py", 3)}


def test_dependency_and_build_directories_are_not_the_authors_code(tmp_path):
    root = repo(
        tmp_path,
        {
            "app.py": "import mine\n",
            "node_modules/dep/index.js": "import theirs from 'transitive';\n",
            "target/generated/G.java": "package p;\nimport generated.Thing;\n",
            "build/out.py": "import built\n",
            ".venv/lib/x.py": "import vendored\n",
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"mine"}


def test_minified_bundles_are_skipped(tmp_path):
    root = repo(
        tmp_path,
        {
            "app.min.js": "import a from 'bundled';\n",
            "app.js": "import b from 'written';\n",
        },
    )
    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"written"}
    assert report.skipped_reasons.get("generated_or_minified") == 1


def test_an_oversized_file_is_skipped_not_fatal(tmp_path):
    root = repo(
        tmp_path,
        {"huge.py": "import x\n" + "# padding\n" * 5000, "small.py": "import kept\n"},
    )
    parser = RepositoryParser(max_file_bytes=200)

    report = parser.parse_repository(root)

    assert modules(report) == {"kept"}
    assert report.skipped_reasons.get("too_large") == 1


def test_binary_content_with_a_source_extension_is_skipped(tmp_path):
    root = tmp_path
    (root / "real.py").write_text("import kept\n", encoding="utf-8")
    (root / "fake.py").write_bytes(b"\x7fELF\x00\x00\x00\x00binary")

    report = RepositoryParser().parse_repository(root)

    assert modules(report) == {"kept"}
    assert report.skipped_reasons.get("binary") == 1


def test_a_syntax_error_in_one_file_does_not_lose_the_others(tmp_path):
    # tree-sitter recovers from errors, so this should still yield what it can
    # and must never abort the repository.
    root = repo(
        tmp_path,
        {"broken.py": "import valid\ndef (((\n", "fine.py": "import other\n"},
    )
    report = RepositoryParser().parse_repository(root)

    assert "other" in modules(report)
    assert report.files_parsed == 2


def test_report_summarises_what_it_read(tmp_path):
    root = repo(
        tmp_path,
        {"a.py": "import x\nimport x\n", "B.java": "package p;\nimport y.Z;\n"},
    )
    report = RepositoryParser().parse_repository(root)

    assert report.files_parsed == 2
    assert report.by_language() == {"python": 2, "java": 1}
    # Duplicates are kept as occurrences (each has its own line) but collapse
    # in `modules`.
    assert report.modules == ("x", "y.Z")


def test_an_empty_repository_is_not_an_error(tmp_path):
    report = RepositoryParser().parse_repository(tmp_path)

    assert report.occurrences == ()
    assert report.files_parsed == 0


def test_missing_grammars_are_a_startup_failure_not_a_silent_skip(monkeypatch, tmp_path):
    # A per-file catch turns an absent wheel into "every file is a parse_error", which
    # reports the same numbers as a repository with nothing to parse.
    from analysis import parse as parse_module

    monkeypatch.setattr(
        parse_module, "_grammar", lambda name: (_ for _ in ()).throw(ImportError(name))
    )
    with pytest.raises(ImportError):
        parse_module.verify_grammars()


def test_all_registered_grammars_load(tmp_path):
    from analysis.parse import verify_grammars

    verify_grammars()


def test_a_file_over_the_occurrence_limit_is_not_counted_as_skipped(tmp_path):
    # It parsed successfully; counting it in files_skipped reports one file as both.
    root = repo(tmp_path, {"a.py": "import one\nimport two\nimport three\n"})
    parser = RepositoryParser()
    parser.max_occurrences = 1

    report = parser.parse_repository(root)

    assert report.files_parsed == 1
    assert report.files_skipped == 0
    assert report.skipped_reasons.get("occurrence_limit", 0) > 0


# -- calls ------------------------------------------------------------------


def write(tmp_path, name: str, *lines: str) -> None:
    (tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_qualified_call_keeps_both_the_receiver_and_the_method(tmp_path):
    # SpringApplication.run needs the receiver: `run` alone is in every codebase.
    write(tmp_path, "App.java", "class App { void go() { SpringApplication.run(App.class); } }")

    call = next(c for c in RepositoryParser().parse_repository(tmp_path).calls
                if c.method == "run")

    assert (call.callee, call.receiver) == ("SpringApplication.run", "SpringApplication")


def test_an_unqualified_call_has_no_receiver(tmp_path):
    # useState() is distinctive on its own, which is why hook rules can use the
    # bare method name.
    write(tmp_path, "a.jsx", "const [a, b] = useState(0);")

    call = next(c for c in RepositoryParser().parse_repository(tmp_path).calls
                if c.method == "useState")

    assert (call.callee, call.receiver) == ("useState", None)


def test_a_receiver_that_is_an_expression_is_dropped(tmp_path):
    # `items[0].parent().save()` says nothing about which library `save` belongs
    # to. Keeping it would make every call site its own value and match nothing.
    write(tmp_path, "a.py", "items[0].parent().save()")

    call = next(c for c in RepositoryParser().parse_repository(tmp_path).calls
                if c.method == "save")

    assert call.receiver is None
    assert call.callee == "save"


def test_a_dotted_receiver_survives(tmp_path):
    write(tmp_path, "a.py", "import pandas as pd", "d = pd.read_csv(p)")

    call = next(c for c in RepositoryParser().parse_repository(tmp_path).calls
                if c.method == "read_csv")

    assert call.callee == "pd.read_csv"


def test_calls_carry_their_position(tmp_path):
    # L2 evidence links to the line, same as an import.
    write(tmp_path, "a.py", "x = 1", "y = 2", "z = helper()")

    call = next(c for c in RepositoryParser().parse_repository(tmp_path).calls
                if c.method == "helper")

    assert call.line == 3


def test_a_call_inside_a_comment_is_not_a_call(tmp_path):
    # The reason for a parser rather than a regex, restated for calls.
    write(tmp_path, "a.py", "# useState()", "x = 1")

    assert RepositoryParser().parse_repository(tmp_path).calls == ()


def test_the_call_budget_is_separate_from_the_import_budget(tmp_path):
    # Calls outnumber imports several times over. Sharing one budget would mean
    # a call-heavy file silently costs the imports of every later file.
    write(tmp_path, "a.py", "import os", *[f"f{n}()" for n in range(20)])

    report = RepositoryParser(max_calls=5).parse_repository(tmp_path)

    assert len(report.calls) == 5
    assert report.skipped_reasons["call_limit"] == 1
    assert len(report.occurrences) == 1  # the import is untouched
    assert report.files_skipped == 0  # a truncated tail is not a skipped file
