import json
import re
from pathlib import Path

import pytest
from depth_helpers import evaluate_depth_files

from analysis.configs import facts_from_configs, parse_config_bytes
from analysis.rulepack import DEPTH_RULE_PACK_PATH, load_rule_pack

FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "rule_pack_depth"
INFRA_TECH_IDS = ("docker", "kubernetes", "aws", "azure", "gcp", "jenkins")
EXPECTED_INFRA_RULES = {
    "docker.l3.hardened",
    "kubernetes.l1.workload",
    "kubernetes.l2.operations",
    "kubernetes.l3.hardened",
    "aws.l2.managed-resource",
    "aws.l3.network-managed-iam",
    "azure.l2.managed-resource",
    "azure.l3.network-managed-iam",
    "gcp.l2.managed-resource",
    "gcp.l3.network-managed-iam",
    "jenkins.l3.credentials-lifecycle",
}


def _profile(path: str, content: str, key: str):
    return [
        item for item in parse_config_bytes(path, content.encode()) if item.key == key
    ]


def test_docker_profile_uses_effective_final_stage_and_ignores_heredoc_body():
    content = """\
ARG RUNTIME=python:3.12-slim
FROM python:3.12 AS build
RUN <<EOF
USER fake
HEALTHCHECK CMD false
EOF
FROM ${RUNTIME} AS runtime
USER app:app
HEALTHCHECK --interval=30s CMD python -m app.health
"""

    [profile] = _profile("Dockerfile", content, "DOCKER_FINAL_STAGE_PROFILE")

    assert profile.value == (
        "FINAL_STAGE MULTISTAGE EXPLICIT_NONROOT_USER ACTIVE_HEALTHCHECK"
    )
    assert profile.scope == "stage:2"
    assert profile.component == "runtime"
    assert not [
        item
        for item in parse_config_bytes("Dockerfile", content.encode())
        if item.line in {4, 5}
    ]


@pytest.mark.parametrize(
    "tail,required,forbidden",
    [
        (
            "USER root\nHEALTHCHECK NONE\n",
            {"FINAL_USER_ROOT", "HEALTHCHECK_NONE"},
            {"EXPLICIT_NONROOT_USER", "ACTIVE_HEALTHCHECK"},
        ),
        (
            "ARG APP_USER\nUSER $APP_USER\nHEALTHCHECK CMD true\n",
            {"UNRESOLVED_ARG"},
            {"EXPLICIT_NONROOT_USER"},
        ),
    ],
)
def test_docker_final_resets_and_unresolved_args_are_near_misses(
    tail, required, forbidden
):
    [profile] = _profile(
        "Dockerfile",
        "FROM alpine AS build\nRUN true\nFROM alpine AS runtime\n" + tail,
        "DOCKER_FINAL_STAGE_PROFILE",
    )
    tokens = set(profile.value.split())
    assert required <= tokens
    assert not tokens & forbidden


def test_docker_global_arg_is_not_available_to_user_without_stage_redeclaration():
    content = """\
ARG APP_USER=app
FROM alpine AS build
RUN true
FROM alpine AS runtime
USER $APP_USER
HEALTHCHECK CMD true
"""

    [profile] = _profile("Dockerfile", content, "DOCKER_FINAL_STAGE_PROFILE")

    assert "UNRESOLVED_ARG" in profile.value.split()
    assert "EXPLICIT_NONROOT_USER" not in profile.value.split()

    redeclared = content.replace(
        "FROM alpine AS runtime\n", "FROM alpine AS runtime\nARG APP_USER\n"
    )
    [redeclared_profile] = _profile(
        "Dockerfile", redeclared, "DOCKER_FINAL_STAGE_PROFILE"
    )
    assert "UNRESOLVED_ARG" not in redeclared_profile.value.split()
    assert "EXPLICIT_NONROOT_USER" in redeclared_profile.value.split()


def test_kubernetes_hardening_is_bound_to_one_workload_container():
    complete = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: app
          image: app:1
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 1
              memory: 256Mi
          readinessProbe:
            httpGet:
              path: /ready
          livenessProbe:
            httpGet:
              path: /live
          securityContext:
            runAsNonRoot: true
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
"""
    profiles = _profile("k8s/deployment.yaml", complete, "KUBERNETES_CONTAINER_PROFILE")
    assert {
        "REQUEST_CPU",
        "REQUEST_MEMORY",
        "READINESS_PROBE",
        "LIVENESS_PROBE",
        "RUN_AS_NON_ROOT",
        "NO_PRIVILEGE_ESCALATION",
        "READ_ONLY_ROOT_FILESYSTEM",
    } <= {profile.value for profile in profiles}
    assert {profile.component for profile in profiles} == {
        "document:0/Deployment:api/container:app@line:9"
    }
    assert {profile.value: profile.line for profile in profiles}[
        "READ_ONLY_ROOT_FILESYSTEM"
    ] == 27

    split = complete.replace(
        "        - name: app\n",
        "        - name: resources-only\n",
    ).replace(
        "          readinessProbe:",
        "        - name: security-only\n          image: app:1\n          readinessProbe:",
    )
    profiles = _profile("k8s/deployment.yaml", split, "KUBERNETES_CONTAINER_PROFILE")
    by_component = {}
    for profile in profiles:
        by_component.setdefault(profile.component, set()).add(profile.value)
    assert len(by_component) == 2
    assert all(
        not {
            "REQUEST_CPU",
            "REQUEST_MEMORY",
            "READINESS_PROBE",
            "LIVENESS_PROBE",
            "RUN_AS_NON_ROOT",
            "NO_PRIVILEGE_ESCALATION",
            "READ_ONLY_ROOT_FILESYSTEM",
        }
        <= tokens
        for tokens in by_component.values()
    )


def test_kubernetes_policy_profiles_and_block_scalar_near_miss():
    content = """\
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api
spec:
  minReplicas: 2
  maxReplicas: 10
  scaleTargetRef:
    name: api
  metrics:
    - type: Resource
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: api
---
kind: ConfigMap
data:
  fake: |
    kind: Deployment
    readinessProbe:
      enabled: true
"""
    profiles = _profile("k8s/policies.yaml", content, "KUBERNETES_POLICY_PROFILE")
    assert [item.value for item in profiles] == [
        "HPA MIN_REPLICAS MAX_REPLICAS METRICS",
        "PDB AVAILABILITY_BUDGET SELECTOR",
    ]


@pytest.mark.parametrize(
    "cloud,provider,resources",
    [
        (
            "aws",
            "aws",
            'resource "aws_vpc" "main" {}\nresource "aws_subnet" "db" { vpc_id = aws_vpc.main.id }\nresource "aws_db_instance" "data" { db_subnet_group_name = aws_subnet.db.id }\nresource "aws_iam_policy" "reader" { Action = ["rds-db:connect"]\nResource = [aws_db_instance.data.arn] }',
        ),
        (
            "azure",
            "azurerm",
            'resource "azurerm_resource_group" "main" {}\nresource "azurerm_virtual_network" "main" { resource_group_name = azurerm_resource_group.main.name }\nresource "azurerm_subnet" "db" { virtual_network_name = azurerm_virtual_network.main.name }\nresource "azurerm_postgresql_flexible_server" "data" { delegated_subnet_id = azurerm_subnet.db.id\nresource_group_name = azurerm_resource_group.main.name }\nresource "azurerm_role_definition" "reader" { actions = ["Microsoft.DBforPostgreSQL/flexibleServers/read"]\nassignable_scopes = [azurerm_postgresql_flexible_server.data.id] }',
        ),
        (
            "gcp",
            "google",
            'resource "google_project" "main" {}\nresource "google_compute_network" "main" {}\nresource "google_sql_database_instance" "data" { private_network = google_compute_network.main.id\nproject = google_project.main.project_id }\nresource "google_project_iam_custom_role" "reader" { project = google_sql_database_instance.data.project\npermissions = ["cloudsql.instances.get"] }',
        ),
    ],
)
def test_terraform_cloud_profile_requires_real_resources_and_narrow_iam(
    cloud, provider, resources
):
    content = f'''\
provider "{provider}" {{}}
{resources}
'''
    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")
    assert profile.scope == cloud
    assert set(profile.value.split()) == {
        "DECLARED_RESOURCE",
        "IAM_LEAST_PRIVILEGE",
        "IAM_POLICY",
        "IAM_MANAGED_LINK",
        "MANAGED_SERVICE",
        "MANAGED_NETWORK_LINK",
        "NETWORK",
    }

    assert not _profile(
        "infra/provider.tf", f'provider "{provider}" {{}}\n', "TERRAFORM_CLOUD_PROFILE"
    )
    wildcard = re.sub(
        r"(?i)(actions?|permissions)\s*=\s*\[[^]]+\]",
        r'\1 = ["*"]',
        content,
    )
    [wildcard_profile] = _profile("infra/main.tf", wildcard, "TERRAFORM_CLOUD_PROFILE")
    assert "IAM_LEAST_PRIVILEGE" not in wildcard_profile.value.split()

    disconnected = (
        content.replace("aws_db_instance.data.arn", '"detached"')
        .replace("azurerm_postgresql_flexible_server.data.id", '"detached"')
        .replace(
            "project = google_sql_database_instance.data.project",
            'project = "detached"',
        )
    )
    [disconnected_profile] = _profile(
        "infra/main.tf", disconnected, "TERRAFORM_CLOUD_PROFILE"
    )
    assert "IAM_MANAGED_LINK" not in disconnected_profile.value.split()


def test_terraform_comments_and_heredocs_do_not_create_resource_profiles():
    content = """\
# resource "aws_vpc" "fake" {}
locals {
  example = <<EOF
resource "aws_db_instance" "fake" {}
EOF
}
provider "aws" {}
"""
    assert not _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")


def test_terraform_service_wildcard_is_not_least_privilege():
    content = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "reader" {
  actions = ["rds:*"]
  resources = [aws_db_instance.data.arn]
}
"""

    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")

    assert "IAM_LEAST_PRIVILEGE" not in profile.value.split()


@pytest.mark.parametrize(
    "action",
    [
        "var.action",
        '"${var.action}"',
        '"rds:DescribeDBInstances", var.additional_action',
        '"rds:DescribeDBInstances", "rds:*"',
        r'"\u002a"',
        '"rds:Describe?BInstances"',
        '"   "',
        '"%{ if var.enabled }rds:DescribeDBInstances%{ endif }"',
    ],
)
def test_terraform_iam_requires_statically_narrow_literal_actions(action):
    content = f"""\
resource "aws_vpc" "main" {{}}
resource "aws_db_instance" "data" {{ vpc_id = aws_vpc.main.id }}
resource "aws_iam_policy" "reader" {{
  Action = [{action}]
  Resource = [aws_db_instance.data.arn]
}}
"""

    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")

    assert "IAM_LEAST_PRIVILEGE" not in profile.value.split()


def test_terraform_iam_rejects_scalar_action_alongside_a_valid_list():
    content = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "reader" {
  Action = ["rds:DescribeDBInstances"]
  Action = "*"
  Resource = [aws_db_instance.data.arn]
}
"""

    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")

    assert "IAM_LEAST_PRIVILEGE" not in profile.value.split()


def test_terraform_iam_accepts_literal_actions_with_linked_resource_reference():
    content = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "reader" {
  Action = ["rds:DescribeDBInstances", "rds:ListTagsForResource"]
  Resource = [aws_db_instance.data.arn]
}
"""

    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")

    assert "IAM_LEAST_PRIVILEGE" in profile.value.split()


def test_terraform_unresolved_iam_action_cannot_raise_aws_to_l3(tmp_path):
    result = evaluate_depth_files(
        tmp_path,
        {
            "infra/main.tf": """\
variable "action" {
  type = string
  default = "*"
}
provider "aws" {}
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "reader" {
  Action = [var.action]
  Resource = [aws_db_instance.data.arn]
}
"""
        },
    )

    aws = next(item for item in result.verdicts if item.tech_id == "aws")
    assert aws.level == "L2"
    assert "aws.l3.network-managed-iam" not in aws.matched_rule_ids


def test_terraform_unresolved_iam_resource_cannot_raise_aws_to_l3(tmp_path):
    result = evaluate_depth_files(
        tmp_path,
        {
            "infra/main.tf": """\
provider "aws" {}
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "reader" {
  Action = ["rds:DescribeDBInstances"]
  Resource = [var.resource]
}
"""
        },
    )

    aws = next(item for item in result.verdicts if item.tech_id == "aws")
    assert aws.level == "L2"
    assert "aws.l3.network-managed-iam" not in aws.matched_rule_ids


def test_terraform_reference_graph_ignores_plain_strings_but_accepts_interpolation():
    lookalikes = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { description = "aws_vpc.main.id" }
resource "aws_iam_policy" "reader" {
  actions = ["rds:DescribeDBInstances"]
  resources = ["aws_db_instance.data.arn"]
}
"""
    [lookalike_profile] = _profile(
        "infra/main.tf", lookalikes, "TERRAFORM_CLOUD_PROFILE"
    )
    lookalike_tokens = set(lookalike_profile.value.split())
    assert "MANAGED_NETWORK_LINK" not in lookalike_tokens
    assert "IAM_MANAGED_LINK" not in lookalike_tokens

    interpolated = lookalikes.replace(
        '"aws_vpc.main.id"', '"${aws_vpc.main.id}"'
    ).replace('"aws_db_instance.data.arn"', '"${aws_db_instance.data.arn}"')
    [interpolated_profile] = _profile(
        "infra/main.tf", interpolated, "TERRAFORM_CLOUD_PROFILE"
    )
    interpolated_tokens = set(interpolated_profile.value.split())
    assert "MANAGED_NETWORK_LINK" in interpolated_tokens
    assert "IAM_MANAGED_LINK" in interpolated_tokens


def test_terraform_literal_count_zero_resources_are_inactive():
    content = """\
resource "aws_vpc" "main" { count = 0 }
resource "aws_db_instance" "data" { count = 0 }
resource "aws_iam_policy" "reader" {
  count = 0
  actions = ["rds:DescribeDBInstances"]
  resources = [aws_db_instance.data.arn]
}
"""

    assert not _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")
    assert not _profile("infra/main.tf", content, "TERRAFORM_RESOURCE_PROFILE")

    dynamic = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" {
  count = var.database_enabled ? 1 : 0
  vpc_id = aws_vpc.main.id
}
resource "aws_iam_policy" "reader" {
  actions = ["rds:DescribeDBInstances"]
  resources = [aws_db_instance.data.arn]
}
"""
    [dynamic_profile] = _profile("infra/main.tf", dynamic, "TERRAFORM_CLOUD_PROFILE")
    dynamic_tokens = set(dynamic_profile.value.split())
    assert "MANAGED_SERVICE" in dynamic_tokens
    assert "MANAGED_NETWORK_LINK" not in dynamic_tokens
    assert "IAM_MANAGED_LINK" not in dynamic_tokens


def test_terraform_iam_link_does_not_follow_undirected_managed_network_path():
    content = """\
resource "aws_vpc" "main" {}
resource "aws_db_instance" "data" { vpc_id = aws_vpc.main.id }
resource "aws_iam_policy" "network_reader" {
  actions = ["ec2:DescribeVpcs"]
  resources = [aws_vpc.main.arn]
}
"""

    [profile] = _profile("infra/main.tf", content, "TERRAFORM_CLOUD_PROFILE")
    tokens = set(profile.value.split())

    assert "MANAGED_NETWORK_LINK" in tokens
    assert "IAM_MANAGED_LINK" not in tokens


def test_jenkins_summary_requires_real_pipeline_and_binds_credentials():
    content = """\
pipeline {
  agent any
  stages {
    stage('Build') { steps { echo 'build' } }
    stage('Deploy') { steps { withCredentials([]) { echo 'deploy' } } }
  }
  post { always { echo 'done' } }
}
"""
    [profile] = _profile("Jenkinsfile", content, "JENKINS_PIPELINE_PROFILE")
    assert {
        "PIPELINE_BOUND",
        "DECLARATIVE",
        "MULTI_STAGE",
        "POST",
        "CREDENTIALS_BOUND",
    } <= set(profile.value.split())

    fake = 'println "pipeline stage post withCredentials credentials"\n// pipeline {\n'
    assert not _profile("Jenkinsfile", fake, "JENKINS_PIPELINE_PROFILE")

    outside = """\
pipeline {
  agent any
  stages { stage('Build') { steps { echo 'build' } } }
}
withCredentials([]) { echo 'outside' }
"""
    [outside_profile] = _profile("Jenkinsfile", outside, "JENKINS_PIPELINE_PROFILE")
    assert "CREDENTIALS_BOUND" not in outside_profile.value.split()


def test_structural_scope_and_component_are_exposed_as_fact_fields():
    [occurrence] = _profile(
        "Dockerfile",
        "FROM alpine AS runtime\nUSER app\nHEALTHCHECK CMD true\n",
        "DOCKER_FINAL_STAGE_PROFILE",
    )
    [fact] = facts_from_configs((occurrence,))
    assert fact.fields["SCOPE"] == "stage:1"
    assert fact.fields["COMPONENT"] == "runtime"


def test_infrastructure_depth_profiles_and_fixtures_are_published():
    pack = load_rule_pack(DEPTH_RULE_PACK_PATH)
    published = {
        rule.rule_id
        for tech_id in INFRA_TECH_IDS
        for rule in pack.support[tech_id].rules
    }
    assert EXPECTED_INFRA_RULES <= published
    assert all(
        (FIXTURE_ROOT / f"{tech_id}.json").is_file() for tech_id in INFRA_TECH_IDS
    )


def test_every_new_infrastructure_rule_has_positive_and_near_miss_evidence():
    cases = [
        case
        for tech_id in INFRA_TECH_IDS
        for case in json.loads((FIXTURE_ROOT / f"{tech_id}.json").read_text("utf-8"))[
            "cases"
        ]
    ]
    positive = {
        rule_id
        for case in cases
        if case["kind"] == "positive"
        for rule_id in case["expected_rule_ids"]
    }
    near_miss = {
        rule_id
        for case in cases
        if case["kind"] in {"negative", "near_miss"}
        for rule_id in case["absent_rule_ids"]
    }
    assert EXPECTED_INFRA_RULES <= positive
    assert EXPECTED_INFRA_RULES <= near_miss


@pytest.mark.parametrize("tech_id", INFRA_TECH_IDS)
def test_infrastructure_depth_cases_use_real_extraction(tech_id, tmp_path):
    fixture = json.loads((FIXTURE_ROOT / f"{tech_id}.json").read_text("utf-8"))
    for index, case in enumerate(fixture["cases"]):
        result = evaluate_depth_files(tmp_path / str(index), case["files"])
        verdict = next(
            (item for item in result.verdicts if item.tech_id == tech_id), None
        )
        matched = set(verdict.matched_rule_ids) if verdict else set()
        if case["expected_level"] is None:
            assert verdict is None or verdict.level != "L3"
        else:
            assert verdict is not None
            assert verdict.level == case["expected_level"]
        assert set(case["expected_rule_ids"]) <= matched
        assert not set(case["absent_rule_ids"]) & matched


def test_new_infrastructure_l3_rules_are_composite_and_component_bound():
    pack = load_rule_pack(DEPTH_RULE_PACK_PATH)
    for tech_id in INFRA_TECH_IDS:
        for rule in pack.support[tech_id].rules:
            if rule.rule_id not in EXPECTED_INFRA_RULES or rule.rule_type != "L3":
                continue
            assert rule.binding_fields == ("FILE_PATH", "COMPONENT")
            assert all(len(group) >= 3 for group in rule.groups)
