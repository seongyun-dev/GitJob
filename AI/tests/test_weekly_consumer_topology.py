"""Regression contract for the split weekly Trend consumer topology."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DATA_CLUSTER = ROOT / "Infra" / "compose" / "compose.ec2-data-cluster.yaml"
COMPOSE_WEEKLY_HOST = ROOT / "Infra" / "compose" / "compose.weekly-host.yaml"


def _service_block(path: Path, service: str) -> str:
    """Return one top-level service block without requiring PyYAML."""

    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"  {service}:"
    start = next(i for i, line in enumerate(lines) if line == marker)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("  ") and not lines[i].startswith("    "):
            end = i
            break
    return "\n".join(lines[start:end])


def test_data_cluster_overlay_quarantines_weekly_consumer_from_data_profile():
    block = _service_block(COMPOSE_DATA_CLUSTER, "weekly-trend-consumer")
    assert "profiles: !override [weekly]" in block
    assert "network_mode" not in block


def test_service_weekly_overlay_keeps_consumer_definition_and_host_network():
    block = _service_block(COMPOSE_WEEKLY_HOST, "weekly-trend-consumer")
    assert "profiles: !override [weekly]" in block
    assert "network_mode: host" in block
    assert "WEEKLY_CONSUMER_GROUP" in block
    assert "WEEKLY_CONSUMER_DATANODE_HOSTS" in block
