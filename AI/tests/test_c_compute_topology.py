"""Regression contract for the private C Compute endpoint topology."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DATA_CLUSTER = ROOT / "Infra" / "compose" / "compose.ec2-data-cluster.yaml"


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


def test_data_cluster_publishes_c_compute_only_on_tailscale_address():
    block = _service_block(COMPOSE_DATA_CLUSTER, "worker")

    assert (
        '"${DATA_TS_IP:?DATA_TS_IP must be set}:${C_COMPUTE_PORT:-8080}:8080"' in block
    )
    assert "0.0.0.0" not in block
    assert "127.0.0.1" not in block
