"""Deploy preconditions for S15P21E102-300, exercised without Docker.

The first test is the incident: the arguments the stale `deploy.sh` actually
used on 2026-09-17.  Everything else exists so the guard does not overcorrect
into refusing the deploys that are fine.

Nothing here starts a container or reads a checkout.  The guard takes the facts
as arguments precisely so this file can hold the contract.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Infra" / "scripts"))

from deploy_guard import (
    CANONICAL_DATA_SERVICES,
    CLUSTER_ONLY_SERVICES,
    DATA_CLUSTER_OVERRIDE,
    LEGACY_DATA_OVERRIDE,
    MONITORING_OVERLAY,
    REMEDIATION_SERVICES,
    check_deploy_checkout,
    check_full_data_deploy,
    check_observability_deploy,
    classify_running_project,
    classify_running_service,
)

PRODUCTION = "/home/ubuntu/workspace/S15P21E102"
MONITORING_CHECKOUT = "/home/ubuntu/workspace/S15P21E102-monitoring"
GUARD = ROOT / "Infra" / "scripts" / "deploy_guard.py"


def cluster_files(path=PRODUCTION):
    return [
        f"{path}/Infra/compose/compose.yaml",
        f"{path}/Infra/compose/{DATA_CLUSTER_OVERRIDE}",
    ]


def legacy_files(path=PRODUCTION):
    return [
        f"{path}/Infra/compose/compose.yaml",
        f"{path}/Infra/compose/{LEGACY_DATA_OVERRIDE}",
    ]


# --------------------------------------------------------------------------
# contract A -- full Data deploy
# --------------------------------------------------------------------------


def test_canonical_full_data_deploy_passes():
    assert (
        check_full_data_deploy(
            compose_files=cluster_files(),
            profiles=["data"],
            rendered_services=list(CANONICAL_DATA_SERVICES),
            deploy_path=PRODUCTION,
            production_path=PRODUCTION,
        )
        == []
    )


def test_the_2026_09_17_incident_is_refused():
    """The stale checkout's own arguments, verbatim.

    `data_path` defaulted to the production checkout, the override was the
    single-node one, and the rendered set therefore lacked `hdfs-bootstrap`
    and `spark-c1-archiver`.
    """

    rendered = [
        service
        for service in CANONICAL_DATA_SERVICES
        if service not in CLUSTER_ONLY_SERVICES
    ]

    errors = check_full_data_deploy(
        compose_files=legacy_files(),
        profiles=["data"],
        rendered_services=rendered,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert errors
    joined = " ".join(errors)
    assert LEGACY_DATA_OVERRIDE in joined
    assert "hdfs-bootstrap" in joined
    assert "spark-c1-archiver" in joined


def test_legacy_override_alone_is_refused():
    errors = check_full_data_deploy(
        compose_files=legacy_files(),
        profiles=["data"],
        rendered_services=list(CANONICAL_DATA_SERVICES),
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any(LEGACY_DATA_OVERRIDE in error for error in errors)


@pytest.mark.parametrize("dropped", CLUSTER_ONLY_SERVICES)
def test_missing_cluster_only_service_is_refused(dropped):
    rendered = [s for s in CANONICAL_DATA_SERVICES if s != dropped]

    errors = check_full_data_deploy(
        compose_files=cluster_files(),
        profiles=["data"],
        rendered_services=rendered,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any(dropped in error for error in errors)


def test_full_deploy_from_another_checkout_is_refused():
    """The stale run reconciled production from a different working tree."""

    errors = check_full_data_deploy(
        compose_files=cluster_files(MONITORING_CHECKOUT),
        profiles=["data"],
        rendered_services=list(CANONICAL_DATA_SERVICES),
        deploy_path=MONITORING_CHECKOUT,
        production_path=PRODUCTION,
    )

    assert any("production checkout" in error for error in errors)


def test_full_deploy_without_the_data_profile_is_refused():
    errors = check_full_data_deploy(
        compose_files=cluster_files(),
        profiles=["core"],
        rendered_services=list(CANONICAL_DATA_SERVICES),
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any("'data' profile" in error for error in errors)


def test_override_order_does_not_matter():
    reversed_files = list(reversed(cluster_files()))

    assert (
        check_full_data_deploy(
            compose_files=reversed_files,
            profiles=["data"],
            rendered_services=list(CANONICAL_DATA_SERVICES),
            deploy_path=PRODUCTION,
            production_path=PRODUCTION,
        )
        == []
    )


# --------------------------------------------------------------------------
# contract B -- targeted observability deploy
# --------------------------------------------------------------------------


def observability_files():
    return [*cluster_files(), f"{PRODUCTION}/Infra/compose/{MONITORING_OVERLAY}"]


def test_documented_observability_deploy_passes():
    assert (
        check_observability_deploy(
            compose_files=observability_files(),
            profiles=["core", "data", "observability"],
            target_services=["node-exporter"],
            flags=["--no-deps", "--no-recreate", "--no-build"],
        )
        == []
    )


def test_observability_without_no_deps_is_refused():
    errors = check_observability_deploy(
        compose_files=observability_files(),
        profiles=["observability"],
        target_services=["node-exporter"],
        flags=["--no-recreate"],
    )

    assert any("--no-deps" in error for error in errors)


def test_observability_without_no_recreate_is_refused():
    errors = check_observability_deploy(
        compose_files=observability_files(),
        profiles=["observability"],
        target_services=["node-exporter"],
        flags=["--no-deps"],
    )

    assert any("--no-recreate" in error for error in errors)


def test_observability_without_target_services_is_refused():
    """An untargeted up is a full reconcile wearing the observability profile."""

    errors = check_observability_deploy(
        compose_files=observability_files(),
        profiles=["observability"],
        target_services=[],
        flags=["--no-deps", "--no-recreate"],
    )

    assert any("name its target services" in error for error in errors)


def test_observability_may_not_target_data_services():
    errors = check_observability_deploy(
        compose_files=observability_files(),
        profiles=["data", "observability"],
        target_services=["node-exporter", "hdfs-namenode"],
        flags=["--no-deps", "--no-recreate"],
    )

    assert any("hdfs-namenode" in error for error in errors)


def test_observability_on_the_legacy_base_is_refused():
    """What the runbook still says today, and why it is being corrected."""

    errors = check_observability_deploy(
        compose_files=[
            *legacy_files(),
            f"{PRODUCTION}/Infra/compose/{MONITORING_OVERLAY}",
        ],
        profiles=["observability"],
        target_services=["node-exporter"],
        flags=["--no-deps", "--no-recreate"],
    )

    assert any(LEGACY_DATA_OVERRIDE in error for error in errors)


# --------------------------------------------------------------------------
# contract C -- service-aware verification, not project equality
# --------------------------------------------------------------------------


def test_monitoring_overlay_on_node_exporter_is_not_a_mismatch():
    verdict, _ = classify_running_service(
        "node-exporter",
        ["compose.yaml", DATA_CLUSTER_OVERRIDE, MONITORING_OVERLAY],
    )

    assert verdict == "OK"


def test_override_independent_service_is_label_only():
    """`analysis-worker` is defined only in the base file.

    Which data override was named cannot change what it renders to, so a stale
    label on it must not demand a recreate.
    """

    verdict, reason = classify_running_service(
        "analysis-worker", ["compose.yaml", LEGACY_DATA_OVERRIDE]
    )

    assert verdict == "LABEL_ONLY"
    assert "does not change what it renders to" in reason


def test_canonical_data_service_on_legacy_override_must_reconcile():
    verdict, _ = classify_running_service(
        "hdfs-namenode", ["compose.yaml", LEGACY_DATA_OVERRIDE]
    )

    assert verdict == "RECONCILE"


def test_monitoring_service_on_legacy_base_must_reconcile():
    verdict, _ = classify_running_service(
        "node-exporter", ["compose.yaml", LEGACY_DATA_OVERRIDE, MONITORING_OVERLAY]
    )

    assert verdict == "RECONCILE"


def test_the_live_project_is_classified_not_equalised():
    """The data host as observed on 2026-09-17, after recovery.

    Nine canonical services are correct, `analysis-worker` carries a stale but
    harmless label, and `node-exporter` really does render from the wrong base.
    A project-wide equality rule would have demanded eleven recreates.
    """

    containers = [
        {"service": service, "config_files": ["compose.yaml", DATA_CLUSTER_OVERRIDE]}
        for service in CANONICAL_DATA_SERVICES
        if service != "hdfs-bootstrap"
    ]
    containers.append(
        {
            "service": "analysis-worker",
            "config_files": ["compose.yaml", LEGACY_DATA_OVERRIDE],
        }
    )
    containers.append(
        {
            "service": "node-exporter",
            "config_files": ["compose.yaml", LEGACY_DATA_OVERRIDE, MONITORING_OVERLAY],
        }
    )

    buckets = classify_running_project(containers)

    assert [entry["service"] for entry in buckets["RECONCILE"]] == ["node-exporter"]
    assert [entry["service"] for entry in buckets["LABEL_ONLY"]] == ["analysis-worker"]
    assert len(buckets["OK"]) == len(CANONICAL_DATA_SERVICES) - 1


def test_config_files_may_be_a_comma_joined_label():
    buckets = classify_running_project(
        [
            {
                "service": "hdfs-namenode",
                "config_files": f"compose.yaml,{DATA_CLUSTER_OVERRIDE}",
            }
        ]
    )

    assert buckets["OK"]


# --------------------------------------------------------------------------
# contract D -- checkout
# --------------------------------------------------------------------------


def test_checkout_at_the_approved_ref_passes():
    assert (
        check_deploy_checkout(
            head="604be00",
            approved_ref="604be00",
            is_ancestor_of_approved=False,
            is_descendant_of_approved=False,
            dirty=False,
        )
        == []
    )


def test_stale_checkout_is_refused():
    """`2f62651`, the revision the outage was deployed from."""

    errors = check_deploy_checkout(
        head="2f62651",
        approved_ref="604be00",
        is_ancestor_of_approved=True,
        is_descendant_of_approved=False,
        dirty=False,
    )

    assert any("behind the approved ref" in error for error in errors)


def test_unmerged_checkout_is_refused():
    errors = check_deploy_checkout(
        head="abc1234",
        approved_ref="604be00",
        is_ancestor_of_approved=False,
        is_descendant_of_approved=True,
        dirty=False,
    )

    assert any("unmerged work" in error for error in errors)


def test_unrelated_checkout_is_refused():
    """The production main checkout as found on 2026-09-17.

    HEAD was `2e7742b Merge commit '15065cd' into ai/S15P21E102-256-ai-llm` --
    neither an ancestor nor a descendant of `develop`.  It is refused because
    nothing about it says which topology it carries: a merge of a feature
    branch can contain compose changes that were never reviewed for
    production, and can equally be missing ones that were.
    """

    errors = check_deploy_checkout(
        head="2e7742b",
        approved_ref="604be00",
        is_ancestor_of_approved=False,
        is_descendant_of_approved=False,
        dirty=False,
    )

    assert any("unrelated to the approved ref" in error for error in errors)


def test_dirty_checkout_is_refused():
    errors = check_deploy_checkout(
        head="604be00",
        approved_ref="604be00",
        is_ancestor_of_approved=False,
        is_descendant_of_approved=False,
        dirty=True,
    )

    assert any("uncommitted changes" in error for error in errors)


def test_unknown_ref_is_refused():
    assert check_deploy_checkout(
        head=None,
        approved_ref="604be00",
        is_ancestor_of_approved=False,
        is_descendant_of_approved=False,
        dirty=False,
    )
    assert check_deploy_checkout(
        head="604be00",
        approved_ref=None,
        is_ancestor_of_approved=False,
        is_descendant_of_approved=False,
        dirty=False,
    )


# --------------------------------------------------------------------------
# the command line a shell stage actually calls
# --------------------------------------------------------------------------


def run_guard(*args):
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_zero_on_a_canonical_full_deploy():
    result = run_guard(
        "full-data",
        *[f"--compose-file={path}" for path in cluster_files()],
        "--profile=data",
        *[f"--rendered-service={s}" for s in CANONICAL_DATA_SERVICES],
        f"--deploy-path={PRODUCTION}",
        f"--production-path={PRODUCTION}",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_exits_non_zero_on_the_incident_arguments():
    result = run_guard(
        "full-data",
        *[f"--compose-file={path}" for path in legacy_files()],
        "--profile=data",
        *[
            f"--rendered-service={s}"
            for s in CANONICAL_DATA_SERVICES
            if s not in CLUSTER_ONLY_SERVICES
        ],
        f"--deploy-path={PRODUCTION}",
        f"--production-path={PRODUCTION}",
    )

    assert result.returncode == 1
    assert LEGACY_DATA_OVERRIDE in result.stdout


# --------------------------------------------------------------------------
# S15P21E102-304 -- observability remediation mode
#
# `-300` made `--no-recreate` mandatory so a monitoring run could not become an
# untargeted reconcile.  That is still right, and it also blocks the one
# legitimate thing a monitoring run sometimes has to do: replace a container
# whose bind mount points at the wrong checkout.  A mount is fixed when the
# container is created, so no amount of config reload moves it.
#
# The exception is deliberately narrow: an explicit allowlist, on the canonical
# checkout, with every other condition of the normal contract still in force.
# --------------------------------------------------------------------------


def remediation_files():
    return observability_files()


def test_prometheus_mount_drift_remediation_passes():
    """The -292 case: Prometheus bind-mounted from the stale checkout."""

    assert (
        check_observability_deploy(
            compose_files=remediation_files(),
            profiles=["core", "data", "observability"],
            target_services=["prometheus"],
            flags=["--no-deps", "--no-build"],
            remediation=True,
            deploy_path=PRODUCTION,
            production_path=PRODUCTION,
        )
        == []
    )


def test_json_exporter_needs_no_remediation_to_be_created():
    """`--no-recreate` stops a recreate, not a create.

    `json-exporter` does not exist in production, so the normal contract
    already creates it.  Keeping it out of the remediation allowlist is the
    point of this test: the exception stays as small as the evidence requires.
    """

    assert (
        check_observability_deploy(
            compose_files=observability_files(),
            profiles=["core", "data", "observability"],
            target_services=["json-exporter"],
            flags=["--no-deps", "--no-recreate", "--no-build"],
        )
        == []
    )
    assert "json-exporter" not in REMEDIATION_SERVICES


def test_recreate_without_remediation_mode_is_refused():
    errors = check_observability_deploy(
        compose_files=observability_files(),
        profiles=["observability"],
        target_services=["prometheus"],
        flags=["--no-deps"],
    )

    assert any("--no-recreate" in error for error in errors)


@pytest.mark.parametrize("service", ["node-exporter", "grafana", "kafka-exporter"])
def test_remediation_outside_the_allowlist_is_refused(service):
    """A monitoring service is not automatically a remediation target."""

    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=[service],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any(service in error for error in errors)


def test_remediation_from_a_stale_checkout_is_refused():
    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=["prometheus"],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=MONITORING_CHECKOUT,
        production_path=PRODUCTION,
    )

    assert any("canonical production checkout" in error for error in errors)


def test_remediation_without_a_declared_checkout_is_refused():
    """Fail closed: an unstated checkout is not a canonical one."""

    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=["prometheus"],
        flags=["--no-deps"],
        remediation=True,
    )

    assert errors


def test_remediation_still_requires_no_deps():
    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=["prometheus"],
        flags=[],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any("--no-deps" in error for error in errors)


def test_remediation_still_requires_explicit_targets():
    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=[],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any("name its target services" in error for error in errors)


def test_remediation_still_requires_the_observability_profile():
    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["data"],
        target_services=["prometheus"],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any("observability" in error for error in errors)


def test_remediation_still_refuses_the_legacy_base():
    errors = check_observability_deploy(
        compose_files=[
            *legacy_files(),
            f"{PRODUCTION}/Infra/compose/{MONITORING_OVERLAY}",
        ],
        profiles=["observability"],
        target_services=["prometheus"],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any(LEGACY_DATA_OVERRIDE in error for error in errors)


@pytest.mark.parametrize(
    "service", ["hdfs-namenode", "spark-master", "kafka", "backend"]
)
def test_remediation_may_not_target_data_or_service_containers(service):
    errors = check_observability_deploy(
        compose_files=remediation_files(),
        profiles=["observability"],
        target_services=[service],
        flags=["--no-deps"],
        remediation=True,
        deploy_path=PRODUCTION,
        production_path=PRODUCTION,
    )

    assert any(service in error for error in errors)


def test_cli_allows_the_prometheus_remediation():
    result = run_guard(
        "observability",
        *[f"--compose-file={path}" for path in remediation_files()],
        "--profile=observability",
        "--target-service=prometheus",
        "--flag=--no-deps",
        "--remediation",
        f"--deploy-path={PRODUCTION}",
        f"--production-path={PRODUCTION}",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_refuses_remediation_of_an_unlisted_service():
    result = run_guard(
        "observability",
        *[f"--compose-file={path}" for path in remediation_files()],
        "--profile=observability",
        "--target-service=grafana",
        "--flag=--no-deps",
        "--remediation",
        f"--deploy-path={PRODUCTION}",
        f"--production-path={PRODUCTION}",
    )

    assert result.returncode == 1
    assert "grafana" in result.stdout
