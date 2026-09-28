"""All eligible files must be considered without pooling unrelated evidence."""

import pytest
from depth_helpers import evaluate_depth_files


def _verdict(judgement, tech_id):
    return next(item for item in judgement.verdicts if item.tech_id == tech_id)


@pytest.mark.parametrize("valid_first", [False, True])
def test_multistage_dockerfile_matches_regardless_of_filename_order(
    tmp_path, valid_first
):
    valid, decoy = ("a", "z") if valid_first else ("z", "a")
    result = evaluate_depth_files(
        tmp_path,
        {
            f"{decoy}/Dockerfile": "FROM alpine\n",
            f"{valid}/Dockerfile": "FROM python:3.12 AS build\nFROM python:3.12\n",
        },
    )
    assert _verdict(result, "docker").level == "L2"
    evidence = [
        item.fact for item in result.evidence if item.rule_id == "docker.l2.multistage"
    ]
    assert {item.file for item in evidence} == {f"{valid}/Dockerfile"}


def test_from_counts_are_not_combined_across_dockerfiles(tmp_path):
    result = evaluate_depth_files(
        tmp_path, {"a/Dockerfile": "FROM alpine\n", "z/Dockerfile": "FROM alpine\n"}
    )
    assert _verdict(result, "docker").level == "L0"


@pytest.mark.parametrize("valid_first", [False, True])
def test_later_import_bound_call_is_checked_after_unrelated_call(tmp_path, valid_first):
    valid, decoy = ("a", "z") if valid_first else ("z", "a")
    template = (
        "import org.springframework.boot.SpringApplication;\n"
        "class App { void start() { %s.run(App.class); } }\n"
    )
    result = evaluate_depth_files(
        tmp_path,
        {
            f"{decoy}/App.java": template % "Helper",
            f"{valid}/App.java": template % "SpringApplication",
        },
    )
    assert _verdict(result, "spring-boot").level == "L2"
    evidence = [
        item.fact for item in result.evidence if item.rule_id == "spring-boot.l2.api"
    ]
    assert {item.file for item in evidence} == {f"{valid}/App.java"}


def test_no_candidate_with_an_import_bound_call_remains_l1(tmp_path):
    result = evaluate_depth_files(
        tmp_path,
        {
            f"{directory}/App.java": (
                "import org.springframework.boot.SpringApplication;\n"
                "class App { void start() { Helper.run(App.class); } }\n"
            )
            for directory in ("a", "z")
        },
    )
    assert _verdict(result, "spring-boot").level == "L1"
