"""Manifest reading, on real files rather than mocks.

Every case below is a shape that actually occurs and that a naive reader gets
wrong: interpolated Gradle versions, a version catalog, a monorepo's own
packages, `dependencyManagement`, PEP 503 spelling. Mocking the parsers would
prove none of it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from depth_helpers import evaluate_depth_files

from analysis.manifests import ManifestScanner, normalize_coordinate


def repository(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def coordinates(report) -> set[str]:
    return {f"{item.ecosystem}:{item.coordinate}" for item in report.occurrences}


# -- Gradle -----------------------------------------------------------------


def test_gradle_reads_the_coordinate_and_drops_the_version(tmp_path):
    # The interpolated version is why dropping versions matters: the coordinate
    # is a literal even when the version is not.
    root = repository(
        tmp_path,
        {
            "build.gradle": """\
        dependencies {
          implementation 'org.springframework.boot:spring-boot-starter-webmvc'
          implementation 'io.jsonwebtoken:jjwt-api:0.12.6'
          runtimeOnly "org.webjars:webjars-locator-lite:${webjarsLocatorLiteVersion}"
        }
    """
        },
    )

    report = ManifestScanner().scan(root)

    assert coordinates(report) == {
        "MAVEN:org.springframework.boot:spring-boot-starter-webmvc",
        "MAVEN:io.jsonwebtoken:jjwt-api",
        "MAVEN:org.webjars:webjars-locator-lite",
    }


def test_gradle_keeps_the_configuration_as_the_scope(tmp_path):
    # A test-only dependency must stay distinguishable, and re-deriving this
    # later would mean cloning the repository again.
    root = repository(
        tmp_path,
        {
            "build.gradle": """\
        dependencies {
          implementation 'org.postgresql:postgresql'
          testImplementation 'org.testcontainers:testcontainers'
        }
    """
        },
    )

    scopes = {
        item.coordinate: item.scope for item in ManifestScanner().scan(root).occurrences
    }

    assert scopes["org.postgresql:postgresql"] == "implementation"
    assert scopes["org.testcontainers:testcontainers"] == "testImplementation"


def test_gradle_kotlin_dsl_and_platform_wrappers_are_read(tmp_path):
    root = repository(
        tmp_path,
        {
            "build.gradle.kts": """\
        dependencies {
          implementation(platform("org.springframework.boot:spring-boot-dependencies:3.3.0"))
          implementation("com.h2database:h2")
        }
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {
        "MAVEN:org.springframework.boot:spring-boot-dependencies",
        "MAVEN:com.h2database:h2",
    }


def test_gradle_skips_this_repositorys_own_modules(tmp_path):
    root = repository(
        tmp_path,
        {
            "build.gradle": """\
        dependencies {
          implementation project(':core')
          implementation 'com.mysql:mysql-connector-j'
        }
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {
        "MAVEN:com.mysql:mysql-connector-j"
    }


def test_gradle_resolves_a_version_catalog_alias(tmp_path):
    # Gradle turns the TOML key `spring-boot` into `libs.spring.boot`. Without
    # reading the catalog a modern build looks like it has no dependencies.
    root = repository(
        tmp_path,
        {
            "gradle/libs.versions.toml": """\
            [libraries]
            spring-boot = { module = "org.springframework.boot:spring-boot-starter", version = "3.3.0" }
            lombok = { group = "org.projectlombok", name = "lombok", version = "1.18.32" }
        """,
            "build.gradle": """\
            dependencies {
              implementation libs.spring.boot
              compileOnly libs.lombok
            }
        """,
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {
        "MAVEN:org.springframework.boot:spring-boot-starter",
        "MAVEN:org.projectlombok:lombok",
    }


def test_a_catalog_entry_nobody_references_is_not_a_dependency(tmp_path):
    # Declaring a version is not using the library.
    root = repository(
        tmp_path,
        {
            "gradle/libs.versions.toml": """\
            [libraries]
            unused = { module = "org.example:unused", version = "1.0" }
        """,
            "build.gradle": "dependencies {\n}\n",
        },
    )

    assert ManifestScanner().scan(root).occurrences == ()


def test_gradle_ignores_commented_out_dependencies(tmp_path):
    root = repository(
        tmp_path,
        {
            "build.gradle": """\
        dependencies {
          // implementation 'org.example:removed'
          implementation 'org.example:kept'
        }
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {"MAVEN:org.example:kept"}


# -- npm --------------------------------------------------------------------


def test_package_json_reads_every_dependency_section_with_its_scope(tmp_path):
    root = repository(
        tmp_path,
        {
            "package.json": """\
        {
          "name": "gitjob-fe",
          "dependencies": { "react": "^19.0.0", "@tanstack/react-query": "^5.0.0" },
          "devDependencies": { "oxlint": "^1.0.0" }
        }
    """
        },
    )

    report = ManifestScanner().scan(root)
    scopes = {item.coordinate: item.scope for item in report.occurrences}

    assert coordinates(report) == {
        "NPM:react",
        "NPM:@tanstack/react-query",
        "NPM:oxlint",
    }
    assert scopes["react"] == "dependencies"
    assert scopes["oxlint"] == "devDependencies"


def test_package_json_skips_packages_from_inside_this_repository(tmp_path):
    # The monorepo noise that the import side could only guess at is explicit here.
    root = repository(
        tmp_path,
        {
            "package.json": """\
        {
          "dependencies": {
            "@company/ui": "workspace:*",
            "core": "file:../core",
            "shared": "link:../shared",
            "react": "^19.0.0"
          }
        }
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {"NPM:react"}


def test_a_committed_node_modules_is_not_scanned(tmp_path):
    # Otherwise one repository contributes thousands of dependencies that
    # belong to someone else's package.
    root = repository(
        tmp_path,
        {
            "package.json": '{ "dependencies": { "react": "^19.0.0" } }',
            "node_modules/left-pad/package.json": '{ "dependencies": { "sneaky": "^1.0.0" } }',
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {"NPM:react"}


# -- Maven ------------------------------------------------------------------


def test_pom_reads_dependencies_and_ignores_managed_versions(tmp_path):
    # dependencyManagement pins a version for modules that may never declare
    # the dependency; counting it reports intent as use.
    root = repository(
        tmp_path,
        {
            "pom.xml": """\
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencyManagement>
            <dependencies>
              <dependency>
                <groupId>org.managed</groupId><artifactId>only-pinned</artifactId>
                <version>1.0</version>
              </dependency>
            </dependencies>
          </dependencyManagement>
          <dependencies>
            <dependency>
              <groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>
              <scope>runtime</scope>
            </dependency>
          </dependencies>
        </project>
    """
        },
    )

    report = ManifestScanner().scan(root)

    assert coordinates(report) == {"MAVEN:org.postgresql:postgresql"}
    assert report.occurrences[0].scope == "runtime"


def test_pom_skips_a_coordinate_that_needs_the_effective_pom(tmp_path):
    # Resolving ${project.groupId} needs Maven, and running Maven on a fetched
    # repository is remote code execution.
    root = repository(
        tmp_path,
        {
            "pom.xml": """\
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies>
            <dependency>
              <groupId>${project.groupId}</groupId><artifactId>sibling</artifactId>
            </dependency>
          </dependencies>
        </project>
    """
        },
    )

    assert ManifestScanner().scan(root).occurrences == ()


# -- Python -----------------------------------------------------------------


def test_requirements_strips_extras_specifiers_and_comments(tmp_path):
    root = repository(
        tmp_path,
        {
            "requirements.txt": """\
        fastapi==0.141.1
        psycopg[binary]==3.3.3
        tzdata>=2024.1
        # a comment
        kafka-python==3.0.11  # trailing comment
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {
        "PYPI:fastapi",
        "PYPI:psycopg",
        "PYPI:tzdata",
        "PYPI:kafka-python",
    }


def test_requirements_skips_includes_editables_and_urls(tmp_path):
    root = repository(
        tmp_path,
        {
            "requirements-dev.txt": """\
        -r requirements.txt
        -e .
        --index-url https://example.invalid/simple
        https://example.invalid/pkg.whl
        pytest==9.1.1
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {"PYPI:pytest"}


def test_pypi_names_are_normalized_so_one_project_is_one_candidate(tmp_path):
    # PEP 503: these three are the same project on PyPI, and counting them
    # separately would split one candidate three ways.
    assert normalize_coordinate("PYPI", "Python_Dateutil") == "python-dateutil"
    assert normalize_coordinate("PYPI", "python.dateutil") == "python-dateutil"
    assert normalize_coordinate("PYPI", "python-dateutil") == "python-dateutil"


def test_pyproject_reads_project_and_poetry_layouts(tmp_path):
    root = repository(
        tmp_path,
        {
            "pyproject.toml": """\
        [project]
        dependencies = ["httpx>=0.28", "pydantic[email]==2.13.5"]

        [project.optional-dependencies]
        dev = ["pytest==9.1.1"]

        [tool.poetry.dependencies]
        python = "^3.12"
        requests = "^2.32"
    """
        },
    )

    report = ManifestScanner().scan(root)

    assert coordinates(report) == {
        "PYPI:httpx",
        "PYPI:pydantic",
        "PYPI:pytest",
        "PYPI:requests",
    }
    # The interpreter constraint is not a dependency.
    assert "PYPI:python" not in coordinates(report)


# -- NuGet ------------------------------------------------------------------


def test_csproj_reads_package_references_case_insensitively(tmp_path):
    root = repository(
        tmp_path,
        {
            "App/App.csproj": """\
        <Project Sdk="Microsoft.NET.Sdk">
          <ItemGroup>
            <PackageReference Include="Microsoft.Maui.Controls" Version="8.0.0" />
            <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
          </ItemGroup>
        </Project>
    """
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == {
        "NUGET:microsoft.maui.controls",
        "NUGET:newtonsoft.json",
    }


def test_central_package_version_metadata_is_not_a_dependency(tmp_path):
    root = repository(
        tmp_path,
        {
            "Directory.Packages.props": """\
                <Project><ItemGroup>
                  <PackageVersion Include="Azure.Storage.Blobs" Version="12.0.0" />
                </ItemGroup></Project>
            """,
            "App/App.csproj": '<Project Sdk="Microsoft.NET.Sdk" />',
        },
    )

    assert coordinates(ManifestScanner().scan(root)) == set()

    result = evaluate_depth_files(
        tmp_path / "judgement",
        {
            "Directory.Packages.props": """\
                <Project><ItemGroup>
                  <PackageVersion Include="Azure.Storage.Blobs" Version="12.0.0" />
                </ItemGroup></Project>
            """,
            "App/App.csproj": '<Project Sdk="Microsoft.NET.Sdk" />',
        },
    )
    assert "azure" not in {item.tech_id for item in result.verdicts}


def test_csproj_reads_actual_package_references_without_a_version(tmp_path):
    root = repository(
        tmp_path,
        {
            "Directory.Packages.props": """\
                <Project><ItemGroup>
                  <PackageVersion Include="Azure.Storage.Blobs" Version="12.0.0" />
                  <GlobalPackageReference Include="Microsoft.Build.Tasks.Git" Version="1.0.0" />
                </ItemGroup></Project>
            """,
            "App/App.csproj": """\
                <Project><ItemGroup>
                  <PackageReference Include="Azure.Storage.Blobs" />
                  <PackageReference Update="Not.A.Declaration" PrivateAssets="all" />
                </ItemGroup></Project>
            """,
        },
    )

    report = ManifestScanner().scan(root)

    assert coordinates(report) == {
        "NUGET:azure.storage.blobs",
        "NUGET:microsoft.build.tasks.git",
    }
    assert {item.coordinate: item.scope for item in report.occurrences} == {
        "azure.storage.blobs": "PackageReference",
        "microsoft.build.tasks.git": "GlobalPackageReference",
    }
    result = evaluate_depth_files(
        tmp_path / "judgement",
        {
            "Directory.Packages.props": """\
                <Project><ItemGroup>
                  <PackageVersion Include="Azure.Storage.Blobs" Version="12.0.0" />
                </ItemGroup></Project>
            """,
            "App/App.csproj": """\
                <Project><ItemGroup>
                  <PackageReference Include="Azure.Storage.Blobs" />
                </ItemGroup></Project>
            """,
        },
    )
    azure = next(item for item in result.verdicts if item.tech_id == "azure")
    assert azure.level == "L0"


# -- reporting --------------------------------------------------------------


def test_positions_point_at_the_declaration(tmp_path):
    # An L0 verdict has to link to build.gradle:3, not merely assert the fact.
    root = repository(
        tmp_path,
        {
            "build.gradle": """\
        dependencies {
          implementation 'org.example:first'
          implementation 'org.example:second'
        }
    """
        },
    )

    lines = {
        item.coordinate: item.line for item in ManifestScanner().scan(root).occurrences
    }

    assert lines["org.example:first"] == 2
    assert lines["org.example:second"] == 3


def test_a_package_named_in_scripts_does_not_steal_the_line(tmp_path):
    # Found on this repository's own FE/package.json: "lint": "oxlint" appears
    # before devDependencies, so a whole-file search pointed the permalink at
    # the script instead of the declaration.
    root = repository(
        tmp_path,
        {
            "package.json": """\
        {
          "scripts": {
            "dev": "vite",
            "lint": "oxlint"
          },
          "devDependencies": {
            "oxlint": "^1.79.0",
            "vite": "^8.2.2"
          }
        }
    """
        },
    )

    lines = {
        item.coordinate: item.line for item in ManifestScanner().scan(root).occurrences
    }

    assert lines["oxlint"] == 7
    assert lines["vite"] == 8


def test_a_repository_with_no_manifest_reports_nothing_rather_than_failing(tmp_path):
    root = repository(tmp_path, {"README.md": "# nothing here\n"})

    report = ManifestScanner().scan(root)

    assert report.occurrences == ()
    assert report.manifests_read == 0


def test_a_broken_manifest_is_counted_rather_than_raised(tmp_path):
    # One unreadable file must not cost the dependencies of the rest.
    root = repository(
        tmp_path,
        {
            "package.json": "{ this is not json",
            "requirements.txt": "pytest==9.1.1\n",
        },
    )

    report = ManifestScanner().scan(root)

    assert coordinates(report) == {"PYPI:pytest"}
    assert report.skipped_reasons["manifest_error"] == 1


def test_the_report_summarizes_by_ecosystem_and_distinct_coordinate(tmp_path):
    root = repository(
        tmp_path,
        {
            "package.json": '{ "dependencies": { "react": "^19.0.0" } }',
            "web/package.json": '{ "dependencies": { "react": "^19.0.0" } }',
            "requirements.txt": "pytest==9.1.1\n",
        },
    )

    report = ManifestScanner().scan(root)

    assert report.by_ecosystem() == {"NPM": 2, "PYPI": 1}
    # react appears twice but is one candidate.
    assert len(report.coordinates) == 2


def test_an_oversized_manifest_is_skipped(tmp_path):
    root = repository(
        tmp_path, {"package.json": '{ "dependencies": { "react": "1" } }'}
    )

    report = ManifestScanner(max_file_bytes=8).scan(root)

    assert report.occurrences == ()
    assert report.skipped_reasons["too_large"] == 1


def test_an_unknown_ecosystem_is_a_programming_error(tmp_path):
    with pytest.raises(ValueError, match="unknown ecosystem"):
        normalize_coordinate("UNKNOWN", "serde")
