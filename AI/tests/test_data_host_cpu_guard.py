"""CPU guard contract for the 4-vCPU data host.

On 2026-09-21 the data host came back from an abrupt shutdown and every
container started at once. The C worker -- which has no CPU bound of its own
and ingests every declared PUBLIC source at boot -- took enough CPU that
`spark-c1-archiver` restarted four times before an operator stopped C by hand.
Nothing in the deployment prevented that: `collector` was the only service on
this host with any resource setting at all.

These tests pin the two halves of the fix, because they are easy to "simplify"
into one and the simplification is wrong in both directions:

* the C worker gets a **ceiling** (`cpus`). It is the container whose work is
  driven by user traffic and by a boot-time intake, so it is the one that can
  spend the whole host on a burst.
* HDFS gets a **share** and deliberately no ceiling. A share is free while the
  host is idle and only decides who yields when everything wants CPU at once,
  which is exactly a reboot. Capping HDFS instead would throttle block reports
  and re-replication, which is how a slow host becomes a cluster with dead
  DataNodes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "Infra/compose/compose.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
HDFS_SERVICES = ("hdfs-namenode", "hdfs-datanode", "hdfs-datanode2", "hdfs-datanode3")


def _service_block(path: Path, service: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"  {service}:"
    start = next(i for i, line in enumerate(lines) if line == marker)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("  ") and not lines[i].startswith("    "):
            end = i
            break
    return "\n".join(lines[start:end])


def test_c_worker_has_a_cpu_ceiling_the_operator_can_override() -> None:
    worker = _service_block(COMPOSE, "worker")

    # Roughly twice the highest usage measured on this host (0.78 vCPU), so the
    # ceiling bounds the tail without throttling ordinary work.
    assert 'cpus: "${WORKER_CPUS:-1.5}"' in worker


def test_c_worker_yields_to_hdfs_when_the_host_is_saturated() -> None:
    worker = _service_block(COMPOSE, "worker")

    assert "cpu_shares: ${WORKER_CPU_SHARES:-512}" in worker


def test_hdfs_outranks_the_c_worker() -> None:
    # The numbers only mean anything relative to each other: a share is a
    # weight, not an allocation. If these two ever converge the guard stops
    # protecting anything, and nothing else in the deployment would say so.
    for service in HDFS_SERVICES:
        assert "cpu_shares: ${HDFS_CPU_SHARES:-2048}" in _service_block(
            COMPOSE, service
        )


def test_hdfs_is_never_given_a_cpu_ceiling() -> None:
    # The failure this prevents is subtle: a capped DataNode stays alive and
    # answers its healthcheck while falling behind on block reports, so the
    # cluster degrades without anything reporting a failure.
    for service in HDFS_SERVICES:
        assert "cpus:" not in _service_block(COMPOSE, service)


def test_env_example_declares_the_same_defaults_as_the_compose_file() -> None:
    # A default that lives only in the compose file is one an operator cannot
    # discover before a deploy changes it.
    env = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "WORKER_CPUS=1.5" in env
    assert "WORKER_CPU_SHARES=512" in env
    assert "HDFS_CPU_SHARES=2048" in env


def test_the_collector_guard_is_left_alone() -> None:
    # The data host's other bounded container. It is not part of this change,
    # and a regression here would silently widen what may run on the host.
    collector = _service_block(COMPOSE, "collector")

    assert 'cpus: "${COLLECTOR_CPUS:-2.0}"' in collector
    assert 'mem_limit: "${COLLECTOR_MEMORY_LIMIT:-4g}"' in collector
