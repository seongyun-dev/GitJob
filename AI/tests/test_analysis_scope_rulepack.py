"""Real-file acceptance for callable scope and canonical TSX language facts."""

import json
from pathlib import Path

import pytest

from analysis.configs import ConfigScanner, facts_from_configs
from analysis.judge import (
    Judge,
    facts_from_annotations,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
    facts_from_sources,
    facts_from_syntax,
)
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.rulepack import (
    SCOPE_REGISTRY_PATH,
    SCOPE_RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)

FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "rule_pack_depth"
FIXTURE_PATHS = sorted(FIXTURE_ROOT.glob("*.json"))


def evaluate(root: Path, files: dict[str, str]):
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    report = RepositoryParser().parse_repository(root)
    manifests = ManifestScanner().scan(root)
    configs = ConfigScanner().scan(root)
    facts = (
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_annotations(report.annotations)
        + facts_from_syntax(report.syntax)
        + facts_from_dependencies(manifests.occurrences)
        + facts_from_configs(configs.occurrences)
    )
    pack = load_rule_pack(SCOPE_RULE_PACK_PATH)
    judgement = Judge(
        pack.as_rule_set(mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH))
    ).judge(facts)
    return report, {item.tech_id: item for item in judgement.verdicts}


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_scope_pack_preserves_every_existing_real_file_fixture(fixture_path, tmp_path):
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    tech_id = fixture["tech_id"]
    for index, case in enumerate(fixture["cases"]):
        _, verdicts = evaluate(tmp_path / str(index), case["files"])
        verdict = verdicts.get(tech_id)
        matched = set(verdict.matched_rule_ids) if verdict else set()

        if case["expected_level"] is None:
            assert verdict is None or verdict.level != "L3"
        else:
            assert verdict is not None
            assert verdict.level == case["expected_level"]
        assert set(case["expected_rule_ids"]) <= matched
        assert not set(case["absent_rule_ids"]) & matched


def test_kafka_split_methods_stop_at_l2_while_one_method_reaches_l3(tmp_path):
    imports = (
        "import org.apache.kafka.clients.producer.KafkaProducer;\n"
        "import org.apache.kafka.clients.consumer.KafkaConsumer;\n"
    )
    split = (
        imports
        + """
class SplitWorkflow {
  KafkaProducer producer;
  KafkaConsumer consumer;
  void publish() { producer.send(null); }
  void receive() { consumer.poll(null); }
  void checkpoint() { consumer.commitSync(); }
}
"""
    )
    joined = (
        imports
        + """
class JoinedWorkflow {
  KafkaProducer producer;
  KafkaConsumer consumer;
  void transfer() {
    producer.send(null);
    consumer.poll(null);
    consumer.commitSync();
  }
}
"""
    )

    _, split_verdicts = evaluate(tmp_path / "split", {"src/Workflow.java": split})
    _, joined_verdicts = evaluate(tmp_path / "joined", {"src/Workflow.java": joined})

    assert split_verdicts["apache-kafka"].level == "L2"
    assert (
        "apache-kafka.l3.transactional-consumer"
        not in split_verdicts["apache-kafka"].matched_rule_ids
    )
    assert joined_verdicts["apache-kafka"].level == "L3"
    assert (
        "apache-kafka.l3.transactional-consumer"
        in joined_verdicts["apache-kafka"].matched_rule_ids
    )


def test_kafka_nested_uncalled_functions_cannot_pool_l3_signals(tmp_path):
    _, verdicts = evaluate(
        tmp_path,
        {
            "src/workflow.py": """
from kafka import KafkaProducer, KafkaConsumer
def workflow():
    producer = KafkaProducer()
    consumer = KafkaConsumer("events")
    def publish():
        producer.send("events", b"x")
    def receive():
        consumer.poll()
    def checkpoint():
        consumer.commit()
"""
        },
    )

    assert verdicts["apache-kafka"].level == "L2"
    assert (
        "apache-kafka.l3.transactional-consumer"
        not in verdicts["apache-kafka"].matched_rule_ids
    )


def test_kafka_without_callable_scope_cannot_claim_l3(tmp_path):
    report, verdicts = evaluate(
        tmp_path,
        {
            "src/workflow.py": (
                "from kafka import KafkaProducer, KafkaConsumer\n"
                "producer = KafkaProducer()\n"
                "consumer = KafkaConsumer('events')\n"
                "producer.send('events', b'x')\n"
                "consumer.poll()\n"
                "consumer.commit()\n"
            )
        },
    )
    assert all(item.function is None for item in report.calls)
    assert verdicts["apache-kafka"].level == "L2"


def test_a_decoy_function_does_not_hide_a_later_valid_kafka_function(tmp_path):
    _, verdicts = evaluate(
        tmp_path,
        {
            "src/workflow.py": """
from kafka import KafkaProducer, KafkaConsumer
def decoy():
    producer = KafkaProducer()
    producer.send("events", b"x")
def transfer():
    producer = KafkaProducer()
    consumer = KafkaConsumer("events")
    producer.send("events", b"x")
    consumer.poll()
    consumer.commit()
"""
        },
    )

    assert verdicts["apache-kafka"].level == "L3"
    assert (
        "apache-kafka.l3.transactional-consumer"
        in verdicts["apache-kafka"].matched_rule_ids
    )


@pytest.mark.parametrize(
    ("tech_id", "source", "level", "rule_id"),
    (
        (
            "spring-framework",
            (
                "import org.springframework.context.annotation.Configuration;\n"
                "import org.springframework.context.annotation.Bean;\n"
                "@Configuration class AppConfig { @Bean Object service() { "
                "return new Object(); } }\n"
            ),
            "L2",
            "spring-framework.l2.bean-configuration",
        ),
        (
            "spring-boot",
            (
                "import org.springframework.boot.actuate.health.Health;\n"
                "import org.springframework.boot.actuate.health.HealthIndicator;\n"
                "class ServiceHealth implements HealthIndicator { Object health() { "
                "return Health.up(); } }\n"
            ),
            "L3",
            "spring-boot.l3.observability",
        ),
        (
            "jpa",
            (
                "import jakarta.persistence.EntityManager;\n"
                "import jakarta.persistence.Lock;\n"
                "import jakarta.persistence.LockModeType;\n"
                "import org.springframework.data.jpa.repository.EntityGraph;\n"
                "import org.springframework.transaction.annotation.Transactional;\n"
                "class AccountRepository { EntityManager em; @EntityGraph "
                "@Transactional @Lock(LockModeType.PESSIMISTIC_WRITE) void load() { "
                'em.createQuery("select a from Account a"); } }\n'
            ),
            "L3",
            "jpa.l3.transactional-locking",
        ),
    ),
)
def test_existing_class_composition_rules_remain_positive(
    tmp_path, tech_id, source, level, rule_id
):
    _, verdicts = evaluate(tmp_path, {"src/Example.java": source})

    assert verdicts[tech_id].level == level
    assert rule_id in verdicts[tech_id].matched_rule_ids


@pytest.mark.parametrize("extension", ("ts", "tsx"))
def test_typescript_and_tsx_identical_advanced_types_both_reach_l3(tmp_path, extension):
    source = (
        "export type AwaitedFields<T> = {\n"
        "  [K in keyof T]: T[K] extends Promise<infer U> ? U : T[K]\n"
        "};\n"
    )

    _, verdicts = evaluate(tmp_path, {f"src/types.{extension}": source})

    assert verdicts["typescript"].level == "L3"
    assert (
        "typescript.l3.conditional-mapped-inference"
        in verdicts["typescript"].matched_rule_ids
    )


@pytest.mark.parametrize("extension", ("ts", "tsx"))
def test_typescript_and_tsx_identical_near_misses_stop_at_l2(tmp_path, extension):
    source = "export type Fields<T> = { [K in keyof T]: T[K] };\n"

    _, verdicts = evaluate(tmp_path, {f"src/types.{extension}": source})

    assert verdicts["typescript"].level == "L2"
    assert (
        "typescript.l3.conditional-mapped-inference"
        not in verdicts["typescript"].matched_rule_ids
    )
