"""Fail-closed preconditions for a Production deploy (S15P21E102-300).

2026-09-17 05:16: a `deploy.sh` from `~/workspace/S15P21E102-monitoring`, stale
at `2f62651`, reconciled the live Data project.  Three things lined up.

* Its `data_path` defaults to `/home/ubuntu/workspace/S15P21E102` -- the
  production checkout, not its own.
* `COMPOSE_PROJECT_NAME=gitjob-data` comes from `.env.data`, which both
  checkouts read, so the project name matching is guaranteed rather than
  coincidental.
* That revision still named `compose.ec2-data.yaml`, the single-node override,
  where `develop` had moved to `compose.ec2-data-cluster.yaml`.

`compose_command` reads the `-f` files from `data_path`, so every file existed
and the command succeeded.  Compose then reconciled `gitjob-data` to a topology
without `hdfs-bootstrap` or `spark-c1-archiver`: HDFS stayed in safe mode with
no live datanode, and the Historical resolver stopped.

### What this module refuses, and what it deliberately does not

The tempting rule -- "every container in a project must carry identical
`config_files`" -- is wrong here, and would have failed the next legitimate
deploy.  Three differences are normal:

* `node-exporter` carries the monitoring overlay on top of the data override,
  by design.
* `analysis-worker` is defined only in the base compose file.  Which data
  override was named cannot change what it renders to, so a stale label on it
  is a label and not a defect.
* Override order is not meaningful to the merged result.

So the checks are per-deployment-kind and per-service, not string equality over
a project.  A full Data reconcile must name the cluster override and must
render the canonical services; a targeted observability run must stay targeted.
Everything is a pure function over arguments the caller already has, so it
runs in a test without Docker, a cluster, or a checkout.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence

BASE_COMPOSE = "compose.yaml"
DATA_CLUSTER_OVERRIDE = "compose.ec2-data-cluster.yaml"
LEGACY_DATA_OVERRIDE = "compose.ec2-data.yaml"
MONITORING_OVERLAY = "compose.monitoring.yaml"

# The services that only exist in the cluster override and whose absence is
# what turned a wrong override into an outage.  `hdfs-bootstrap` is the one
# that leaves safe mode; `spark-c1-archiver` is the streaming writer.
CLUSTER_ONLY_SERVICES = ("hdfs-bootstrap", "spark-c1-archiver")

# Everything a full `--profile data` reconcile must render.  Fewer than this and
# compose will remove the difference from the running project.
CANONICAL_DATA_SERVICES = (
    "collector",
    "worker",
    "hdfs-namenode",
    "hdfs-datanode",
    "hdfs-datanode2",
    "hdfs-datanode3",
    "hdfs-bootstrap",
    "spark-master",
    "spark-worker",
    "spark-c1-archiver",
)

OBSERVABILITY_PROFILE = "observability"
DATA_PROFILE = "data"

# Services the monitoring overlay owns.  A targeted observability run may name
# these and nothing else.
OBSERVABILITY_SERVICES = (
    "node-exporter",
    "kafka-exporter",
    "json-exporter",
    "prometheus",
    "grafana",
)

# A service defined only in the base compose file renders the same whichever
# data override was named, so its `config_files` label carries no signal.
OVERRIDE_INDEPENDENT_SERVICES = ("analysis-worker",)

# S15P21E102-304.  `--no-recreate` is what stops a monitoring run turning into a
# reconcile, and it also stops the one repair a monitoring run sometimes needs:
# a container whose bind mount points at the wrong checkout.  A mount is fixed
# when the container is created, so no config reload moves it -- only a
# recreate does.  `-292` found production Prometheus mounted from
# `S15P21E102-monitoring` instead of the canonical checkout, which is exactly
# that shape.
#
# The exception is an allowlist rather than a mode that relaxes the contract:
# every other condition still holds, and a service is not eligible merely
# because it is a monitoring service.  `json-exporter` is deliberately absent —
# it does not exist in production yet, and `--no-recreate` permits a *create*,
# so the normal contract already covers it.
REMEDIATION_SERVICES = ("prometheus",)


class GuardFailure(Exception):
    """A deploy precondition that did not hold.  Always fail-closed."""


def _normalize(files: Iterable[str]) -> tuple[str, ...]:
    """Reduce `-f` arguments to bare file names, order preserved."""

    return tuple(
        str(value).rstrip("/").rsplit("/", 1)[-1] for value in files if str(value)
    )


def check_full_data_deploy(
    *,
    compose_files: Sequence[str],
    profiles: Sequence[str],
    rendered_services: Sequence[str],
    deploy_path: str,
    production_path: str,
) -> list[str]:
    """Contract A: a full `--profile data` reconcile of the live Data project.

    Returns the reasons it must not run; empty means it may.
    """

    errors: list[str] = []
    names = _normalize(compose_files)

    if deploy_path.rstrip("/") != production_path.rstrip("/"):
        errors.append(
            "full Data deploy must run against the production checkout: "
            f"{deploy_path!r} != {production_path!r}"
        )
    if BASE_COMPOSE not in names:
        errors.append(f"base {BASE_COMPOSE} is not among the compose files")
    if LEGACY_DATA_OVERRIDE in names:
        # The exact 2026-09-17 shape.  Named first because it explains the rest.
        errors.append(
            f"{LEGACY_DATA_OVERRIDE} is the single-node override and must not "
            f"reconcile the cluster project; use {DATA_CLUSTER_OVERRIDE}"
        )
    if DATA_CLUSTER_OVERRIDE not in names:
        errors.append(
            f"full Data deploy requires {DATA_CLUSTER_OVERRIDE} among its compose files"
        )
    if DATA_PROFILE not in tuple(profiles):
        errors.append(f"full Data deploy must select the {DATA_PROFILE!r} profile")

    missing = [
        service
        for service in CANONICAL_DATA_SERVICES
        if service not in set(rendered_services)
    ]
    if missing:
        errors.append(
            "rendered topology is missing canonical Data services, which "
            f"compose would remove from the running project: {missing}"
        )
    return errors


def check_observability_deploy(
    *,
    compose_files: Sequence[str],
    profiles: Sequence[str],
    target_services: Sequence[str],
    flags: Sequence[str],
    remediation: bool = False,
    deploy_path: str | None = None,
    production_path: str | None = None,
) -> list[str]:
    """Contract B: a targeted monitoring run beside a live Data project.

    The documented procedure is already safe -- `--no-deps --no-recreate` with
    an explicit service.  This holds it that way, and refuses the one thing it
    must never become: an untargeted reconcile wearing the observability
    profile.

    `remediation` waives *only* the `--no-recreate` requirement, and only for
    `REMEDIATION_SERVICES` on the canonical checkout.  Everything else -- the
    explicit targets, `--no-deps`, the observability profile, the cluster base,
    the refusal of Data and service containers -- is unchanged, because none of
    those were what stood between an operator and a correct mount.
    """

    errors: list[str] = []
    names = _normalize(compose_files)
    flag_set = set(flags)

    if remediation:
        # Fail closed on an unstated checkout: "not declared" is not "canonical".
        if not deploy_path or not production_path:
            errors.append(
                "a remediation deploy must declare its checkout and the "
                "canonical production checkout"
            )
        elif deploy_path.rstrip("/") != production_path.rstrip("/"):
            errors.append(
                "a remediation deploy must run from the canonical production "
                f"checkout: {deploy_path!r} != {production_path!r}"
            )
        outside = [
            service
            for service in target_services
            if service not in set(REMEDIATION_SERVICES)
        ]
        if outside:
            errors.append(
                "a remediation deploy may only recreate "
                f"{list(REMEDIATION_SERVICES)}; refused: {outside}"
            )

    if MONITORING_OVERLAY not in names:
        errors.append(f"an observability deploy must include {MONITORING_OVERLAY}")
    if OBSERVABILITY_PROFILE not in tuple(profiles):
        errors.append(
            f"an observability deploy must select the {OBSERVABILITY_PROFILE!r} profile"
        )
    if not tuple(target_services):
        errors.append(
            "an observability deploy must name its target services; an "
            "untargeted up reconciles the whole project"
        )
    unexpected = [
        service
        for service in target_services
        if service not in set(OBSERVABILITY_SERVICES)
    ]
    if unexpected:
        errors.append(
            f"an observability deploy may only target monitoring services: {unexpected}"
        )
    required_flags = ("--no-deps",) if remediation else ("--no-deps", "--no-recreate")
    for required in required_flags:
        if required not in flag_set:
            errors.append(
                f"{required} is required so a monitoring run cannot touch"
                " the Data services"
            )
    if LEGACY_DATA_OVERRIDE in names:
        errors.append(
            f"{LEGACY_DATA_OVERRIDE} no longer describes the data host; use "
            f"{DATA_CLUSTER_OVERRIDE} as the base for the monitoring overlay"
        )
    return errors


def classify_running_service(
    service: str, config_files: Sequence[str]
) -> tuple[str, str]:
    """Contract C: judge one running container, by what its service is.

    Returns `(verdict, reason)` where verdict is one of `OK`,
    `LABEL_ONLY`, or `RECONCILE`.  Only `RECONCILE` means the container really
    renders from the wrong topology; `LABEL_ONLY` is a stale label on a service
    the override cannot affect, and is reported without demanding a recreate.
    """

    names = _normalize(config_files)

    if service in OVERRIDE_INDEPENDENT_SERVICES:
        # The override is not part of what this service renders from, so the
        # label records history rather than state.
        if DATA_CLUSTER_OVERRIDE in names:
            return "OK", "cluster override, and the override does not affect it"
        reason = (
            f"{service} is defined only in {BASE_COMPOSE}; the recorded "
            "override does not change what it renders to"
        )
        return "LABEL_ONLY", reason

    if service in OBSERVABILITY_SERVICES:
        if MONITORING_OVERLAY not in names:
            return "RECONCILE", "monitoring service without the monitoring overlay"
        if DATA_CLUSTER_OVERRIDE in names:
            return "OK", "monitoring overlay on the cluster override, as intended"
        return (
            "RECONCILE",
            f"monitoring overlay on top of a base that is not {DATA_CLUSTER_OVERRIDE}",
        )

    if service in CANONICAL_DATA_SERVICES:
        if DATA_CLUSTER_OVERRIDE in names:
            return "OK", "cluster override"
        return (
            "RECONCILE",
            f"canonical Data service rendered without {DATA_CLUSTER_OVERRIDE}",
        )

    return "LABEL_ONLY", "service is not covered by a deployment contract"


def classify_running_project(
    containers: Iterable[Mapping[str, object]],
) -> dict[str, list[dict[str, str]]]:
    """Group a project's containers into the three reconcile buckets.

    Deliberately not an equality check over the project: the buckets exist
    because two of the three differences are correct.
    """

    buckets: dict[str, list[dict[str, str]]] = {
        "RECONCILE": [],
        "LABEL_ONLY": [],
        "OK": [],
    }
    for container in containers:
        service = str(container.get("service", ""))
        config_files = container.get("config_files") or ()
        if isinstance(config_files, str):
            config_files = config_files.split(",")
        verdict, reason = classify_running_service(service, tuple(config_files))
        buckets[verdict].append({"service": service, "reason": reason})
    return buckets


def check_deploy_checkout(
    *,
    head: str | None,
    approved_ref: str | None,
    is_ancestor_of_approved: bool,
    is_descendant_of_approved: bool,
    dirty: bool,
) -> list[str]:
    """Contract D: only an approved, clean checkout may reconcile production.

    `is_ancestor_of_approved` is the stale case -- the checkout predates what
    was approved and cannot know the current topology.  That is exactly the
    2026-09-17 shape, and it is the reason this check is by ancestry rather
    than by branch name.

    A *descendant* is refused too: code that is not merged yet has not been
    reviewed, and production is not where it gets tried.

    The caller resolves the ancestry because that needs a repository; the
    decision lives here because that is what the tests can exercise.
    """

    errors: list[str] = []
    if not head:
        errors.append("checkout HEAD could not be resolved")
    if not approved_ref:
        errors.append("no approved deploy ref was supplied")
    if dirty:
        errors.append(
            "checkout has uncommitted changes; a deploy from it is not reproducible"
        )
    if not head or not approved_ref:
        return errors

    if head == approved_ref:
        return errors
    if is_ancestor_of_approved:
        errors.append(
            f"checkout {head} is behind the approved ref {approved_ref}; a "
            "stale checkout does not know the current topology"
        )
    elif is_descendant_of_approved:
        errors.append(
            f"checkout {head} is ahead of the approved ref {approved_ref}; "
            "unmerged work is not deployed to production"
        )
    else:
        errors.append(
            f"checkout {head} is unrelated to the approved ref {approved_ref}"
        )
    return errors


def _emit(name: str, errors: Sequence[str]) -> int:
    document = {"check": name, "pass": not errors, "errors": list(errors)}
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed deploy preconditions.  Exits non-zero with the "
            "reasons, so a shell stage cannot continue past a refusal."
        )
    )
    sub = parser.add_subparsers(dest="check", required=True)

    full = sub.add_parser("full-data", help="contract A")
    full.add_argument("--compose-file", action="append", default=[])
    full.add_argument("--profile", action="append", default=[])
    full.add_argument("--rendered-service", action="append", default=[])
    full.add_argument("--deploy-path", required=True)
    full.add_argument("--production-path", required=True)

    obs = sub.add_parser("observability", help="contract B")
    obs.add_argument("--compose-file", action="append", default=[])
    obs.add_argument("--profile", action="append", default=[])
    obs.add_argument("--target-service", action="append", default=[])
    obs.add_argument("--flag", action="append", default=[])
    obs.add_argument(
        "--remediation",
        action="store_true",
        help=(
            "waive --no-recreate for "
            "REMEDIATION_SERVICES on the canonical checkout, for a verified "
            "mount or config drift that a reload cannot fix"
        ),
    )
    obs.add_argument("--deploy-path", help="remediation only")
    obs.add_argument("--production-path", help="remediation only")

    checkout = sub.add_parser("checkout", help="contract D")
    checkout.add_argument("--head")
    checkout.add_argument("--approved-ref")
    checkout.add_argument("--ancestor-of-approved", action="store_true")
    checkout.add_argument("--descendant-of-approved", action="store_true")
    checkout.add_argument("--dirty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.check == "full-data":
        return _emit(
            "full-data",
            check_full_data_deploy(
                compose_files=arguments.compose_file,
                profiles=arguments.profile,
                rendered_services=arguments.rendered_service,
                deploy_path=arguments.deploy_path,
                production_path=arguments.production_path,
            ),
        )
    if arguments.check == "observability":
        return _emit(
            "observability",
            check_observability_deploy(
                compose_files=arguments.compose_file,
                profiles=arguments.profile,
                target_services=arguments.target_service,
                flags=arguments.flag,
                remediation=arguments.remediation,
                deploy_path=arguments.deploy_path,
                production_path=arguments.production_path,
            ),
        )
    return _emit(
        "checkout",
        check_deploy_checkout(
            head=arguments.head,
            approved_ref=arguments.approved_ref,
            is_ancestor_of_approved=arguments.ancestor_of_approved,
            is_descendant_of_approved=arguments.descendant_of_approved,
            dirty=arguments.dirty,
        ),
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
