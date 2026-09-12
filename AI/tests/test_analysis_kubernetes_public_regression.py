"""Regression coverage from a SHA-pinned public Kubernetes manifest."""

from depth_helpers import evaluate_depth_files

from analysis.configs import parse_config_bytes

# Re-authored from kubernetes/examples@d6b8cd27eacb51e651a1aa6f7c190a28713eff6e
# nginx-platform-app/deployment.yml lines 1-43. The original public checkout is
# retained under validation/job-source-calibration-20260912/repos.
# https://github.com/kubernetes/examples/blob/d6b8cd27eacb51e651a1aa6f7c190a28713eff6e/nginx-platform-app/deployment.yml
PUBLIC_DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-platform-app
spec:
  template:
    spec:
      containers:
      - name: nginx
        image: nginx:stable
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 300m
            memory: 256Mi
        readinessProbe:
          httpGet:
            path: /
            port: 80
        livenessProbe:
          httpGet:
            path: /
            port: 80
"""


SECOND_DOCUMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-platform-app
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
      containers:
      - name: nginx
        image: nginx:stable
        livenessProbe:
          httpGet:
            path: /
            port: 80
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
"""


def _profiles(path: str, content: str):
    return [
        item
        for item in parse_config_bytes(path, content.encode())
        if item.key == "KUBERNETES_CONTAINER_PROFILE"
    ]


def _kubernetes_verdict(tmp_path, content: str):
    judgement = evaluate_depth_files(tmp_path, {"deployment.yml": content})
    return next(item for item in judgement.verdicts if item.tech_id == "kubernetes")


def test_public_workload_is_detected_by_content_and_indentless_sequence():
    [profile] = _profiles("nginx-platform-app/deployment.yml", PUBLIC_DEPLOYMENT)

    assert profile.format == "KUBERNETES"
    assert profile.component == (
        "document:0/Deployment:nginx-platform-app/container:nginx@line:9"
    )
    assert set(profile.value.split()) == {
        "WORKLOAD_CONTAINER",
        "IMAGE",
        "REQUEST_CPU",
        "REQUEST_MEMORY",
        "LIMIT_CPU",
        "LIMIT_MEMORY",
        "READINESS_PROBE",
        "LIVENESS_PROBE",
    }


def test_indentless_sequence_does_not_mix_signals_between_containers():
    split = PUBLIC_DEPLOYMENT.replace(
        "      - name: nginx\n",
        "      - name: sized\n",
    ).replace(
        "        readinessProbe:",
        "      - name: probed\n        image: nginx:stable\n        readinessProbe:",
    )

    profiles = _profiles("manifests/deployment.yml", split)

    assert {item.component for item in profiles} == {
        "document:0/Deployment:nginx-platform-app/container:sized@line:9",
        "document:0/Deployment:nginx-platform-app/container:probed@line:18",
    }
    assert all(
        not {"REQUEST_CPU", "REQUEST_MEMORY", "READINESS_PROBE"}
        <= set(item.value.split())
        for item in profiles
    )


def test_arbitrary_yaml_with_kubernetes_words_is_not_promoted():
    content = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: documentation
spec:
  example:
    containers:
    - name: fake
      image: fake:latest
"""

    occurrences = parse_config_bytes("docs/example.yml", content.encode())

    assert occurrences
    assert {item.format for item in occurrences} == {"YAML"}
    assert not [
        item for item in occurrences if item.key == "KUBERNETES_CONTAINER_PROFILE"
    ]


def test_same_named_containers_in_separate_documents_do_not_combine(tmp_path):
    first = PUBLIC_DEPLOYMENT.replace(
        "        livenessProbe:\n"
        "          httpGet:\n"
        "            path: /\n"
        "            port: 80\n",
        "",
    )
    combined = f"{first}---\n{SECOND_DOCUMENT}"

    assert _kubernetes_verdict(tmp_path / "first", first).level == "L2"
    assert _kubernetes_verdict(tmp_path / "second", SECOND_DOCUMENT).level == "L1"
    combined_verdict = _kubernetes_verdict(tmp_path / "combined", combined)

    assert combined_verdict.level == "L2"
    assert "kubernetes.l3.hardened" not in combined_verdict.matched_rule_ids


def test_duplicate_container_names_in_one_document_do_not_combine(tmp_path):
    first = PUBLIC_DEPLOYMENT.replace(
        "        livenessProbe:\n"
        "          httpGet:\n"
        "            path: /\n"
        "            port: 80\n",
        "",
    )
    second_container = """\
      - name: nginx
        image: nginx:stable
        livenessProbe:
          httpGet:
            path: /
            port: 80
        securityContext:
          runAsNonRoot: true
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
"""
    combined = first + second_container

    verdict = _kubernetes_verdict(tmp_path, combined)

    assert verdict.level == "L2"
    assert "kubernetes.l3.hardened" not in verdict.matched_rule_ids


def test_one_hardened_container_still_reaches_l3(tmp_path):
    hardened = (
        PUBLIC_DEPLOYMENT
        + """\
        securityContext:
          runAsNonRoot: true
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
"""
    )

    verdict = _kubernetes_verdict(tmp_path, hardened)

    assert verdict.level == "L3"
    assert "kubernetes.l3.hardened" in verdict.matched_rule_ids
