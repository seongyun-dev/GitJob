from pathlib import Path

import pytest

import analysis.parse as parse_module
from analysis.judge import (
    Judge,
    facts_from_annotations,
    facts_from_calls,
    facts_from_imports,
    facts_from_syntax,
)
from analysis.parse import RepositoryParser
from analysis.rules import Clause, Mapping, Predicate, Rule, RuleSet


def parse_file(tmp_path: Path, path: str, content: str):
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return RepositoryParser().parse_repository(tmp_path)


def call(report, callee: str):
    return next(item for item in report.calls if item.callee == callee)


def test_python_factory_chain_resolves_an_imported_receiver(tmp_path):
    report = parse_file(
        tmp_path,
        "pipeline.py",
        """
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
spark.sql("select 1")
""",
    )

    assert call(report, "spark.sql").resolved_binding == "SparkSession"


@pytest.mark.parametrize(
    "body",
    [
        "model = tf.keras.Sequential()\nmodel = FakeModel()\nmodel.fit(data)\n",
        (
            "model = tf.keras.Sequential()\n"
            "if debug:\n"
            "    model = FakeModel()\n"
            "model.fit(data)\n"
        ),
        ("def train(model):\n    model.fit(data)\nmodel = tf.keras.Sequential()\n"),
    ],
)
def test_python_reassignment_branch_and_parameter_shadow_fail_closed(tmp_path, body):
    report = parse_file(tmp_path, "model.py", f"import tensorflow as tf\n{body}")

    assert call(report, "model.fit").resolved_binding is None


def test_java_typed_declaration_and_javascript_constructor_are_resolved(tmp_path):
    java = parse_file(
        tmp_path / "java",
        "Repository.java",
        """
import jakarta.persistence.EntityManager;
class Repository {
  void save(Entity entity) {
    EntityManager manager = provider.manager();
    manager.persist(entity);
  }
}
""",
    )
    javascript = parse_file(
        tmp_path / "js",
        "client.ts",
        """
import { MongoClient as Client } from "mongodb";
const client = new Client(uri);
client.db("app");
""",
    )

    assert call(java, "manager.persist").resolved_binding == "EntityManager"
    assert call(javascript, "client.db").resolved_binding == "Client"


def test_chained_java_static_calls_keep_the_imported_root(tmp_path):
    report = parse_file(
        tmp_path,
        "Async.java",
        """
import java.util.concurrent.CompletableFuture;
class Async {
  void run() {
    CompletableFuture.supplyAsync(this::load).thenApply(this::convert).exceptionally(this::fail);
  }
}
""",
    )

    assert call(report, "thenApply").resolved_binding == "CompletableFuture"
    assert call(report, "exceptionally").resolved_binding == "CompletableFuture"


def test_java_local_declaration_shadows_an_imported_static_receiver(tmp_path):
    report = parse_file(
        tmp_path,
        "Local.java",
        """
import java.util.concurrent.CompletableFuture;
class Local {
  void run() {
    Object CompletableFuture = localExecutor();
    CompletableFuture.runAsync(this::load);
  }
}
""",
    )

    assert call(report, "CompletableFuture.runAsync").resolved_binding is None


def test_unrelated_library_and_arbitrary_variable_name_do_not_resolve(tmp_path):
    report = parse_file(
        tmp_path,
        "false-positive.ts",
        """
import { KafkaProducer } from "kafkajs";
const producer = makeLocalQueue();
producer.send("local");
""",
    )

    assert call(report, "producer.send").resolved_binding is None


def test_csharp_generic_invocations_keep_the_method_without_type_arguments(tmp_path):
    report = parse_file(
        tmp_path,
        "Startup.cs",
        """
class Startup {
  void Configure() {
    builder.Services.AddScoped<IStore, Store>();
    AddHostedService<Worker>();
    player.GetComponent<Rigidbody>();
  }
}
""",
    )

    assert call(report, "builder.Services.AddScoped").method == "AddScoped"
    assert call(report, "AddHostedService").method == "AddHostedService"
    assert call(report, "player.GetComponent").method == "GetComponent"


def test_judge_adds_the_exact_import_module_to_a_resolved_api_call(tmp_path):
    report = parse_file(
        tmp_path,
        "Repository.java",
        """
import jakarta.persistence.EntityManager;
class Repository {
  void save(Entity entity) {
    EntityManager manager = provider.manager();
    manager.persist(entity);
  }
}
""",
    )
    rule = Rule(
        rule_id="jpa.depth.persist",
        tech_id="jpa",
        rule_type="L2",
        language=None,
        evaluation_scope="REPOSITORY",
        priority=1,
        clauses=(
            Clause(
                1,
                1,
                "persist",
                "REQUIRED",
                "API_CALL",
                1,
                (
                    Predicate("METHOD", "EXACT", None, ("persist",)),
                    Predicate(
                        "RESOLVED_MODULE",
                        "EXACT",
                        None,
                        ("jakarta.persistence.EntityManager",),
                    ),
                ),
            ),
        ),
    )
    rules = RuleSet(
        registry_version="depth-test",
        mappings=(
            Mapping(
                "jpa",
                "IMPORT_PATH",
                "JAVA",
                "jakarta.persistence.EntityManager",
                "EXACT",
            ),
        ),
        rules=(rule,),
    )

    verdict = Judge(rules).judge(
        facts_from_imports(report.occurrences) + facts_from_calls(report.calls)
    )

    assert verdict.verdicts[0].matched_rule_ids == ("jpa.depth.persist",)
    evidence = verdict.evidence[0].fact
    assert evidence.fields["RESOLVED_MODULE"] == "jakarta.persistence.EntityManager"
    assert evidence.fields["RESOLVED_LOCAL_NAME"] == "EntityManager"


def test_unmapped_standard_library_module_is_preserved_for_language_rules(tmp_path):
    report = parse_file(
        tmp_path,
        "tasks.py",
        """
import asyncio
task = asyncio.create_task(work())
task.cancel()
""",
    )
    rule = Rule(
        rule_id="python.depth.asyncio",
        tech_id="python",
        rule_type="L3",
        language=None,
        evaluation_scope="REPOSITORY",
        priority=1,
        clauses=(
            Clause(
                1,
                1,
                "cancel",
                "REQUIRED",
                "API_CALL",
                1,
                (
                    Predicate("METHOD", "EXACT", None, ("cancel",)),
                    Predicate("RESOLVED_MODULE", "EXACT", None, ("asyncio",)),
                ),
            ),
        ),
    )

    verdict = Judge(
        RuleSet(registry_version="depth-test", mappings=(), rules=(rule,))
    ).judge(facts_from_imports(report.occurrences) + facts_from_calls(report.calls))

    assert verdict.verdicts[0].matched_rule_ids == ("python.depth.asyncio",)
    assert verdict.evidence[0].fact.fields["RESOLVED_MODULE"] == "asyncio"


def test_annotation_resolution_requires_an_unshadowed_import(tmp_path):
    resolved = parse_file(
        tmp_path / "resolved",
        "Service.java",
        """
import org.springframework.transaction.annotation.Transactional;
@Transactional class Service {}
""",
    )
    shadowed = parse_file(
        tmp_path / "shadowed",
        "Service.java",
        """
import org.springframework.transaction.annotation.Transactional;
@interface Transactional {}
@Transactional class Service {}
""",
    )

    resolved_fact = facts_from_annotations(resolved.annotations)[0]
    assert (
        resolved_fact.fields["RESOLVED_MODULE"]
        == "org.springframework.transaction.annotation.Transactional"
    )
    assert all(item.resolved_module is None for item in shadowed.annotations)


def test_structural_facts_are_ast_nodes_with_stable_names(tmp_path):
    sources = {
        "App.java": """
class App<T> extends Base implements HealthIndicator {
  void run() { Runnable work = () -> call(); try { work.run(); } catch (Exception e) {} }
}
""",
        "model.py": """
@decorator
class Child(Base):
    async def stream(self):
        try:
            async with source():
                yield [x for x in values]
        except Error:
            return
""",
        "route.tsx": """
import React, { Suspense } from "react";
export interface Props<T> extends Base { value: T }
export type Item<T> = T[];
type Result<T> = T extends Promise<infer U> ? U : never;
type Flags<T> = { [K in keyof T]: boolean };
export const revalidate = 60;
export async function GET() { await load(); return <Suspense />; }
export async function* stream(source) {
  try { for await (const chunk of source) { yield await transform(chunk); } }
  finally { await source.close(); }
}
class ErrorBoundary extends React.Component {}
try { GET(); } catch (error) {}
""",
        "Query.cs": """
class Query<T> : Base, IFoo {
  public async Task Run() {
    await Work();
    var rows = from x in values where x.Ok select x;
    yield return rows;
  }
  public async IAsyncEnumerable<T> Read(
    IAsyncEnumerable<T> source, IAsyncDisposable resource
  ) {
    await using (resource) {
      await foreach (var item in source) { yield return item; }
    }
  }
}
interface IFoo {}
""",
    }
    for path, content in sources.items():
        target = tmp_path / path
        target.write_text(content, encoding="utf-8")

    report = RepositoryParser().parse_repository(tmp_path)
    observed = {(item.kind, item.name) for item in report.syntax}

    assert {
        ("CLASS_EXTENDS", "Base"),
        ("IMPLEMENTS_TYPE", "HealthIndicator"),
        ("GENERIC_DECLARATION", "App"),
        ("LAMBDA_EXPRESSION", "lambda"),
        ("DECORATED_DEFINITION", "Child"),
        ("ASYNC_FUNCTION_DECLARATION", "stream"),
        ("ASYNC_WITH_STATEMENT", "with"),
        ("TRY_STATEMENT", "try"),
        ("YIELD_EXPRESSION", "yield"),
        ("COMPREHENSION", "list"),
        ("INTERFACE_DECLARATION", "Props"),
        ("TYPE_ALIAS_DECLARATION", "Item"),
        ("CONDITIONAL_TYPE", "Result"),
        ("INFER_TYPE", "Result"),
        ("MAPPED_TYPE", "Flags"),
        ("EXPORTED_BINDING", "revalidate"),
        ("EXPORTED_FUNCTION", "GET"),
        ("ASYNC_GENERATOR_FUNCTION_DECLARATION", "stream"),
        ("FOR_AWAIT_STATEMENT", "for"),
        ("AWAIT_EXPRESSION", "await"),
        ("YIELD_EXPRESSION", "yield"),
        ("JSX_ELEMENT", "Suspense"),
        ("CLASS_EXTENDS", "React.Component"),
        ("ASYNC_METHOD_DECLARATION", "Run"),
        ("ASYNC_METHOD_DECLARATION", "Read"),
        ("AWAIT_USING_STATEMENT", "using"),
        ("AWAIT_FOREACH_STATEMENT", "foreach"),
        ("YIELD_STATEMENT", "yield"),
        ("QUERY_EXPRESSION", "query"),
    } <= observed

    facts = facts_from_syntax(report.syntax)
    suspense = next(
        item
        for item in facts
        if item.fields["KIND"] == "JSX_ELEMENT" and item.fields["NAME"] == "Suspense"
    )
    assert suspense.fields["LANGUAGE"] == "typescript"
    assert suspense.fields["FILE_PATH"] == "route.tsx"
    assert suspense.fields["IS_TEST"] == "false"
    assert suspense.fields["RESOLVED_MODULE"] == "react"


def test_syntax_inside_a_parse_error_is_not_emitted(tmp_path):
    report = parse_file(
        tmp_path,
        "broken.tsx",
        "export function broken( { return <Suspense />; }",
    )

    assert not any(item.name == "Suspense" for item in report.syntax)


def _component_rule() -> Rule:
    return Rule(
        rule_id="python.depth.component",
        tech_id="python",
        rule_type="L3",
        language=None,
        evaluation_scope="REPOSITORY",
        priority=1,
        binding_fields=("FILE_PATH", "COMPONENT"),
        clauses=(
            Clause(
                1,
                1,
                "create-task",
                "REQUIRED",
                "API_CALL",
                1,
                (
                    Predicate("METHOD", "EXACT", None, ("create_task",)),
                    Predicate("RESOLVED_MODULE", "EXACT", None, ("asyncio",)),
                ),
            ),
            Clause(
                2,
                1,
                "cleanup",
                "REQUIRED",
                "SYNTAX_NODE",
                1,
                (Predicate("KIND", "EXACT", None, ("TRY_FINALLY",)),),
            ),
        ),
    )


def _judge_component_source(tmp_path, content: str):
    report = parse_file(tmp_path, "tasks.py", content)
    judgement = Judge(
        RuleSet(
            registry_version="depth-test",
            mappings=(),
            rules=(_component_rule(),),
        )
    ).judge(
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_syntax(report.syntax)
    )
    return report, judgement


def test_component_binding_prevents_cross_class_signal_sums(tmp_path):
    split_report, split = _judge_component_source(
        tmp_path / "split",
        "import asyncio\n"
        "class Scheduler:\n"
        "    async def run(self):\n"
        "        return asyncio.create_task(work())\n"
        "class Cleanup:\n"
        "    async def close(self):\n"
        "        try:\n"
        "            await work()\n"
        "        finally:\n"
        "            close()\n",
    )
    joined_report, joined = _judge_component_source(
        tmp_path / "joined",
        "import asyncio\n"
        "class Worker:\n"
        "    async def run(self):\n"
        "        task = asyncio.create_task(work())\n"
        "        try:\n"
        "            await task\n"
        "        finally:\n"
        "            task.cancel()\n",
    )

    split_facts = facts_from_calls(split_report.calls) + facts_from_syntax(
        split_report.syntax
    )
    assert {
        fact.fields["COMPONENT"]
        for fact in split_facts
        if fact.fields.get("METHOD") == "create_task"
        or fact.fields.get("KIND") == "TRY_FINALLY"
    } == {"class:Scheduler@2:1", "class:Cleanup@5:1"}
    assert split.verdicts == ()
    assert joined.verdicts[0].matched_rule_ids == ("python.depth.component",)
    assert {evidence.fact.fields["COMPONENT"] for evidence in joined.evidence} == {
        "class:Worker@2:1"
    }
    assert all(item.component == "class:Worker@2:1" for item in joined_report.syntax)


def test_components_keep_type_aliases_and_outer_functions_separate(tmp_path):
    report = parse_file(
        tmp_path,
        "scope.ts",
        "type Awaited<T> = T extends Promise<infer U> ? U : never;\n"
        "type Flags<T> = { [K in keyof T]: boolean };\n"
        "function run() { values.map(value => transform(value)); }\n",
    )
    syntax = facts_from_syntax(report.syntax)

    assert {
        item.fields["KIND"]: item.fields["COMPONENT"]
        for item in syntax
        if item.fields["KIND"] in {"CONDITIONAL_TYPE", "INFER_TYPE", "MAPPED_TYPE"}
    } == {
        "CONDITIONAL_TYPE": "type:Awaited@1:1",
        "INFER_TYPE": "type:Awaited@1:1",
        "MAPPED_TYPE": "type:Flags@2:1",
    }
    assert {
        item.fields["COMPONENT"]
        for item in facts_from_calls(report.calls)
        if item.fields["METHOD"] in {"map", "transform"}
    } == {"function:run@3:1"}


def test_exported_decorators_and_implements_share_typed_class_components(tmp_path):
    report = parse_file(
        tmp_path,
        "controller.ts",
        "import { Controller, NestInterceptor } from '@nestjs/common';\n"
        "class AuditInterceptor implements NestInterceptor {\n"
        "  intercept(context, next) { return next.handle(); }\n"
        "}\n"
        "@Controller('accounts')\n"
        "export class AccountController {}\n",
    )
    syntax = facts_from_syntax(report.syntax)
    annotations = facts_from_annotations(report.annotations)

    contract = next(item for item in syntax if item.fields["KIND"] == "IMPLEMENTS_TYPE")
    assert contract.fields == {
        "KIND": "IMPLEMENTS_TYPE",
        "NAME": "NestInterceptor",
        "LANGUAGE": "typescript",
        "FILE_PATH": "controller.ts",
        "IS_TEST": "false",
        "RESOLVED_MODULE": "@nestjs/common",
        "COMPONENT": "class:AuditInterceptor@2:1",
    }
    assert annotations[0].fields["COMPONENT"] == "class:AccountController@6:8"
    assert call(report, "next.handle").component == "class:AuditInterceptor@2:1"


def test_csharp_base_identity_requires_an_alias_or_qualified_name(tmp_path):
    report = parse_file(
        tmp_path,
        "Workers.cs",
        "using Microsoft.Extensions.Hosting;\n"
        "using Bg = Microsoft.Extensions.Hosting.BackgroundService;\n"
        "class Ambiguous : BackgroundService {}\n"
        "class Aliased : Bg {}\n"
        "class Qualified : Microsoft.Extensions.Hosting.BackgroundService {}\n",
    )
    bases = {
        item.name: item.resolved_module
        for item in report.syntax
        if item.kind == "BASE_TYPE"
    }

    assert bases == {
        "BackgroundService": None,
        "Bg": "Microsoft.Extensions.Hosting.BackgroundService",
        "Microsoft.Extensions.Hosting.BackgroundService": (
            "Microsoft.Extensions.Hosting.BackgroundService"
        ),
    }


def test_binding_context_is_built_once_for_all_calls_in_a_file(tmp_path, monkeypatch):
    original = parse_module.build_binding_context
    builds = 0

    def counted(root, imports):
        nonlocal builds
        builds += 1
        return original(root, imports)

    monkeypatch.setattr(parse_module, "build_binding_context", counted)
    calls = "".join(f"value_{index} = tf.constant({index})\n" for index in range(100))
    report = parse_file(tmp_path, "model.py", "import tensorflow as tf\n" + calls)

    assert len(report.calls) == 100
    assert builds == 1
