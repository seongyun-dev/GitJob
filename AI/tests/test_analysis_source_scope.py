"""Source-level scope and language regressions for depth-rule facts."""

from pathlib import Path

from analysis.parse import RepositoryParser


def parse_file(tmp_path: Path, path: str, content: str):
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return RepositoryParser().parse_repository(tmp_path)


def calls_by_method(report):
    return {item.method: item for item in report.calls}


def test_java_methods_have_distinct_function_scope_but_keep_class_component(tmp_path):
    report = parse_file(
        tmp_path,
        "src/SplitWorkflow.java",
        """
class SplitWorkflow {
  void publish() { producer.send(null); }
  void receive() { consumer.poll(null); }
  void checkpoint() { consumer.commitSync(); }
}
""",
    )
    calls = calls_by_method(report)

    assert {calls[name].component for name in ("send", "poll", "commitSync")} == {
        "class:SplitWorkflow@2:1"
    }
    assert {calls[name].function for name in ("send", "poll", "commitSync")} == {
        "function:publish@3:3",
        "function:receive@4:3",
        "function:checkpoint@5:3",
    }


def test_calls_in_one_method_share_function_scope(tmp_path):
    report = parse_file(
        tmp_path,
        "src/JoinedWorkflow.java",
        """
class JoinedWorkflow {
  void transfer() {
    producer.send(null);
    consumer.poll(null);
    consumer.commitSync();
  }
}
""",
    )
    calls = calls_by_method(report)

    assert {calls[name].function for name in ("send", "poll", "commitSync")} == {
        "function:transfer@3:3"
    }


def test_framework_class_component_still_spans_methods_and_annotations(tmp_path):
    report = parse_file(
        tmp_path,
        "src/AccountRepository.java",
        """
import org.springframework.stereotype.Repository;
@Repository
class AccountRepository {
  void save() { entityManager.persist(account); }
  void flush() { entityManager.flush(); }
}
""",
    )
    calls = calls_by_method(report)

    assert report.annotations[0].component == "class:AccountRepository@3:1"
    assert {calls[name].component for name in ("persist", "flush")} == {
        "class:AccountRepository@3:1"
    }
    assert calls["persist"].function != calls["flush"].function


def test_nested_callables_do_not_cross_function_or_class_boundaries(tmp_path):
    report = parse_file(
        tmp_path,
        "src/workflow.py",
        """
def outer():
    producer.send(None)
    def inner():
        consumer.poll()
        consumer.commit()
    callback = lambda: consumer.close()
    class Nested:
        client.flush()
""",
    )
    calls = calls_by_method(report)

    assert calls["send"].function == "function:outer@2:1"
    assert {calls[name].function for name in ("poll", "commit")} == {
        "function:inner@4:5"
    }
    assert calls["close"].function == "function:lambda@7:16"
    assert calls["flush"].function is None
    assert calls["flush"].component == "class:Nested@8:5"


def test_tsx_uses_canonical_typescript_language_and_keeps_advanced_syntax(tmp_path):
    report = parse_file(
        tmp_path,
        "src/types.tsx",
        """
import React from "react";
export type AwaitedFields<T> = {
  [K in keyof T]: T[K] extends Promise<infer U> ? U : T[K]
};
export const View = () => { React.createElement("div"); return <div />; };
""",
    )

    assert {item.language for item in report.occurrences} == {"typescript"}
    assert {item.language for item in report.calls} == {"typescript"}
    assert {item.language for item in report.syntax} == {"typescript"}
    assert {
        "CONDITIONAL_TYPE",
        "MAPPED_TYPE",
        "INFER_TYPE",
        "JSX_ELEMENT",
    } <= {item.kind for item in report.syntax}
    assert {item.language for item in report.sources} == {"typescript"}


def test_tsx_near_miss_does_not_invent_advanced_type_syntax(tmp_path):
    report = parse_file(
        tmp_path,
        "src/types.tsx",
        "export interface Box<T> { value: T }\nexport const View = () => <div />;\n",
    )

    assert {item.language for item in report.syntax} == {"typescript"}
    assert not {
        "CONDITIONAL_TYPE",
        "MAPPED_TYPE",
        "INFER_TYPE",
    } & {item.kind for item in report.syntax}
