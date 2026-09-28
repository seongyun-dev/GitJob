import json
from pathlib import Path

import pytest

from registry.contracts import load_registry
from registry.mapper import MapperInput, MapperSource, MatchStatus, RegistryMapper
from registry.normalization import normalize_mapping_value

AI_ROOT = Path(__file__).resolve().parents[1]
PATH = AI_ROOT / "registry/data/technology_registry_20260911_2.json"
PREVIOUS_PATH = AI_ROOT / "registry/data/technology_registry_20260911_1.json"
TARGET = frozenset(
    [
        "c",
        "cpp",
        "csharp",
        "go",
        "java",
        "kotlin",
        "python",
        "javascript",
        "typescript",
        "php",
        "sql",
        "html",
        "css",
        "spring-framework",
        "spring-boot",
        "jpa",
        "mybatis",
        "dotnet",
        "nodejs",
        "nestjs",
        "django",
        "fastapi",
        "react",
        "nextjs",
        "vuejs",
        "unity",
        "numpy",
        "pandas",
        "scikit-learn",
        "pytorch",
        "tensorflow",
        "apache-spark",
        "hadoop",
        "apache-kafka",
        "mysql",
        "postgresql",
        "mongodb",
        "redis",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "jenkins",
    ]
)


@pytest.fixture(scope="module")
def mapper() -> RegistryMapper:
    return RegistryMapper(load_registry(PATH, repository_root=AI_ROOT.parent))


def test_common44_snapshot_is_exact_active_target() -> None:
    registry = load_registry(PATH, repository_root=AI_ROOT.parent)
    active = {
        item.tech_id for item in registry.technologies if item.status.value == "ACTIVE"
    }

    assert registry.registry_version == "registry-20260911.2"
    assert active == TARGET
    assert len(registry.technologies) == 44


def test_common44_preserves_previous_mappings_for_retained_tech_ids() -> None:
    previous = json.loads(PREVIOUS_PATH.read_text(encoding="utf-8"))
    current = json.loads(PATH.read_text(encoding="utf-8"))

    def semantic_key(mapping: dict[str, object]) -> tuple[object, ...]:
        mapping_type = str(mapping["mapping_type"])
        ecosystem_value = mapping["ecosystem"]
        ecosystem = str(ecosystem_value) if ecosystem_value is not None else None
        return (
            mapping["tech_id"],
            mapping_type,
            ecosystem,
            normalize_mapping_value(mapping_type, ecosystem, str(mapping["value"])),
            mapping["status"],
        )

    retained = {
        semantic_key(mapping)
        for mapping in previous["mappings"]
        if mapping["tech_id"] in TARGET
    }
    current_keys = {semantic_key(mapping) for mapping in current["mappings"]}

    assert len(retained) == 36
    assert retained <= current_keys


@pytest.mark.parametrize(
    ("source", "ecosystem", "raw_value", "expected"),
    [
        (MapperSource.GITHUB_LANGUAGE, None, "C++", "cpp"),
        (MapperSource.GITHUB_LANGUAGE, None, "C#", "csharp"),
        (MapperSource.GITHUB_LANGUAGE, None, "Kotlin", "kotlin"),
        (MapperSource.GITHUB_LANGUAGE, None, "HTML", "html"),
        (MapperSource.GITHUB_LANGUAGE, None, "CSS", "css"),
        (MapperSource.GITHUB_LANGUAGE, None, "SQL", "sql"),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "org.springframework.boot:spring-boot-starter-data-jpa",
            "jpa",
        ),
        (MapperSource.PACKAGE, "NPM", "react-dom", "react"),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "org.apache.kafka:kafka-streams",
            "apache-kafka",
        ),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "org.apache.kafka:kafka-clients",
            "apache-kafka",
        ),
        (MapperSource.PACKAGE, "PYPI", "confluent-kafka", "apache-kafka"),
        (MapperSource.PACKAGE, "MAVEN", "io.lettuce:lettuce-core", "redis"),
        (MapperSource.PACKAGE, "PYPI", "psycopg2-binary", "postgresql"),
        (MapperSource.PACKAGE, "MAVEN", "com.mysql:mysql-connector-j", "mysql"),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "org.springframework.boot:spring-boot-starter-data-mongodb",
            "mongodb",
        ),
        (MapperSource.PACKAGE, "PYPI", "djangorestframework", "django"),
        (MapperSource.PACKAGE, "PYPI", "torchvision", "pytorch"),
        (MapperSource.PACKAGE, "PYPI", "pyspark", "apache-spark"),
        (MapperSource.PACKAGE, "MAVEN", "org.apache.hadoop:hadoop-client", "hadoop"),
        (MapperSource.PACKAGE, "MAVEN", "org.apache.hadoop:hadoop-hdfs", "hadoop"),
        (MapperSource.PACKAGE, "NPM", "@aws-sdk/client-s3", "aws"),
        (MapperSource.PACKAGE, "NUGET", "Azure.Storage.Blobs", "azure"),
        (MapperSource.PACKAGE, "MAVEN", "com.google.cloud:google-cloud-storage", "gcp"),
        (MapperSource.PACKAGE, "MAVEN", "org.mybatis:mybatis", "mybatis"),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "org.springframework.boot:spring-boot-starter-actuator",
            "spring-boot",
        ),
        (MapperSource.PACKAGE, "NUGET", "Microsoft.Maui.Controls", "dotnet"),
        (MapperSource.ALIAS, None, ".NET MAUI", "dotnet"),
        (MapperSource.STACKOVERFLOW_TAG, None, "hdfs", "hadoop"),
        (
            MapperSource.PACKAGE,
            "MAVEN",
            "jakarta.persistence:jakarta.persistence-api",
            "jpa",
        ),
        (
            MapperSource.IMPORT_PATH,
            "JAVA",
            "org.springframework.boot.autoconfigure.SpringBootApplication",
            "spring-boot",
        ),
        (
            MapperSource.IMPORT_PATH,
            "JAVA",
            "org.springframework.data.jpa.repository.JpaRepository",
            "jpa",
        ),
        (
            MapperSource.IMPORT_PATH,
            "JAVA",
            "org.springframework.web.bind.annotation.RestController",
            "spring-framework",
        ),
        (
            MapperSource.IMPORT_PATH,
            "PYTHON",
            "confluent_kafka.Consumer",
            "apache-kafka",
        ),
        (MapperSource.IMPORT_PATH, "PYTHON", "motor.motor_asyncio", "mongodb"),
        (MapperSource.IMPORT_PATH, "JAVA", "io.lettuce.core.RedisClient", "redis"),
        (MapperSource.IMPORT_PATH, "PYTHON", "pyspark.sql", "apache-spark"),
        (MapperSource.IMPORT_PATH, "JAVA", "org.apache.hadoop.fs.FileSystem", "hadoop"),
        (MapperSource.IMPORT_PATH, "JAVASCRIPT", "@aws-sdk/client-s3", "aws"),
        (MapperSource.IMPORT_PATH, "JAVASCRIPT", "@azure/storage-blob", "azure"),
        (MapperSource.IMPORT_PATH, "PYTHON", "google.cloud.storage", "gcp"),
        (MapperSource.IMPORT_PATH, "JAVASCRIPT", "@nestjs/common", "nestjs"),
        (MapperSource.IMPORT_PATH, "DOTNET", "UnityEngine.SceneManagement", "unity"),
        (MapperSource.IMPORT_PATH, "DOTNET", "Microsoft.Maui.Controls", "dotnet"),
    ],
)
def test_common44_source_qualified_mappings(
    mapper: RegistryMapper,
    source: MapperSource,
    ecosystem: str | None,
    raw_value: str,
    expected: str,
) -> None:
    result = mapper.map(
        MapperInput(source=source, raw_value=raw_value, ecosystem=ecosystem)
    )

    assert result.status is MatchStatus.MATCHED
    assert result.tech_id == expected
    assert result.candidates == (expected,)


@pytest.mark.parametrize(
    ("source", "ecosystem", "raw_value"),
    [
        (MapperSource.PACKAGE, "NPM", "unrelated-react"),
        (
            MapperSource.IMPORT_PATH,
            "JAVA",
            "org.springframework.data.repository.Repository",
        ),
        (MapperSource.IMPORT_PATH, "JAVASCRIPT", "@aws-sdk-client/fake"),
    ],
)
def test_common44_mapping_near_misses_stay_unknown(
    mapper: RegistryMapper,
    source: MapperSource,
    ecosystem: str,
    raw_value: str,
) -> None:
    result = mapper.map(
        MapperInput(source=source, raw_value=raw_value, ecosystem=ecosystem)
    )

    assert result.status is MatchStatus.UNKNOWN
    assert result.tech_id is None


def test_common44_provenance_avoids_known_placeholder_or_invented_docs_urls() -> None:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    refs = {
        ref
        for item in (*payload["technologies"], *payload["mappings"])
        for ref in item["provenance_refs"]
    }
    disallowed = {
        "https://docs.nestjs.com/docs",
        "https://www.docker.com/docs",
        "https://www.mysql.com/docs",
        "https://azure.microsoft.com/docs",
        "https://docs.oracle.com/en/java/",
    }

    assert refs.isdisjoint(disallowed)
