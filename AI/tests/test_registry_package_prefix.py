"""Prefix matching for PACKAGE mappings.

Every case here is one the registry got wrong before `package_has_prefix`
existed. PACKAGE mappings were EXACT-only, so `spring-boot-starter-webmvc` was
mapped and the other forty starters were not — spring-petclinic declares five of
them and matched none.
"""

from __future__ import annotations

import pytest

from registry.normalization import package_has_prefix


class TestMaven:
    """group:artifact is hierarchical on three characters: '.', ':' and '-'."""

    @pytest.mark.parametrize(
        "candidate",
        [
            "org.springframework.boot:spring-boot-starter",
            "org.springframework.boot:spring-boot-starter-cache",
            "org.springframework.boot:spring-boot-starter-data-jpa",
            "org.springframework.boot:spring-boot-starter-thymeleaf",
            "org.springframework.boot:spring-boot-starter-webmvc",
        ],
    )
    def test_one_prefix_covers_every_starter(self, candidate):
        # The five petclinic declares. One row instead of forty.
        assert package_has_prefix(
            "org.springframework.boot:spring-boot-starter", candidate, "MAVEN"
        )

    def test_the_group_boundary_is_the_colon(self):
        assert package_has_prefix(
            "org.apache.kafka:kafka", "org.apache.kafka:kafka-clients", "MAVEN"
        )
        assert package_has_prefix(
            "org.apache.kafka:kafka", "org.apache.kafka:kafka-streams", "MAVEN"
        )

    def test_a_prefix_does_not_run_past_a_segment(self):
        # The whole point of a boundary: a longer word starting the same way is
        # a different artifact.
        assert not package_has_prefix(
            "org.springframework.boot:spring-boot-starter",
            "org.springframework.boot:spring-boot-starters-legacy",
            "MAVEN",
        )

    def test_a_different_group_never_matches(self):
        assert not package_has_prefix(
            "org.springframework.boot:spring-boot-starter",
            "com.example:spring-boot-starter-web",
            "MAVEN",
        )

    def test_a_malformed_coordinate_is_refused(self):
        with pytest.raises(ValueError, match="group:artifact"):
            package_has_prefix("org.springframework.boot", "anything", "MAVEN")


class TestNuGet:
    def test_dotted_ids_nest(self):
        assert package_has_prefix("Microsoft.Maui", "Microsoft.Maui.Controls", "NUGET")

    def test_matching_ignores_case(self):
        assert package_has_prefix("microsoft.maui", "Microsoft.Maui.Essentials", "NUGET")

    def test_a_longer_word_is_not_a_child(self):
        assert not package_has_prefix("Microsoft.Maui", "Microsoft.MauiX", "NUGET")


class TestNpm:
    def test_a_scope_is_a_namespace(self):
        assert package_has_prefix("@aws-sdk", "@aws-sdk/client-s3", "NPM")

    def test_a_hyphen_is_not_a_boundary(self):
        # react and react-dom are separate packages and, in this registry,
        # separate technologies. Treating '-' as a boundary would merge them.
        assert not package_has_prefix("react", "react-dom", "NPM")
        assert not package_has_prefix("react", "react-router", "NPM")


class TestPypi:
    def test_prefixes_are_refused_outright(self):
        # kafka-python, python-dateutil, scikit-learn: the hyphen is part of the
        # name. Silently returning False would look the same as "nobody uses it".
        with pytest.raises(ValueError, match="flat"):
            package_has_prefix("kafka", "kafka-python", "PYPI")

    def test_an_unknown_ecosystem_is_a_programming_error(self):
        with pytest.raises(ValueError, match="unsupported package ecosystem"):
            package_has_prefix("serde", "serde-json", "CARGO")


def test_the_registry_seed_only_uses_prefixes_where_they_work():
    """V7 leans on this: every PyPI and npm PACKAGE mapping it writes is EXACT.

    The migration is generated from a table that asserts the same rule, so this
    test is the other half of that agreement — if the boundary map ever gained
    a hyphen for a flat ecosystem, the seed would quietly start over-matching.
    """
    for ecosystem in ("PYPI",):
        with pytest.raises(ValueError):
            package_has_prefix("anything", "anything-else", ecosystem)
    assert package_has_prefix("a.b:c", "a.b:c-d", "MAVEN")
