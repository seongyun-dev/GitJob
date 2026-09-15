"""Deployment contract for the JobKorea PaddleOCR CPU runtime."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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


def test_worker_dockerfile_keeps_jobkorea_ocr_opt_in() -> None:
    dockerfile = (ROOT / "Infra/docker/worker/Dockerfile").read_text(encoding="utf-8")

    assert "ARG JOBKOREA_OCR_ENABLED=false" in dockerfile
    assert "libgl1" in dockerfile
    assert "libglib2.0-0" in dockerfile
    assert "libgomp1" in dockerfile
    assert "paddlepaddle==3.2.0" in dockerfile
    assert "AI/requirements-ocr.txt" in dockerfile
    assert "${JOBKOREA_OCR_ENABLED}" in dockerfile


def test_collector_builds_enable_ocr_but_worker_builds_remain_slim() -> None:
    for relative in (
        "Infra/compose/compose.ec2-data-cluster.yaml",
        "Infra/compose/compose.ec2-data.yaml",
        "Infra/compose/compose.wsl.yaml",
    ):
        compose = ROOT / relative
        collector = _service_block(compose, "collector")
        worker = _service_block(compose, "worker")
        assert 'JOBKOREA_OCR_ENABLED: "true"' in collector
        assert "JOBKOREA_OCR_ENABLED" not in worker

    deploy = (ROOT / "Infra/scripts/deploy.sh").read_text(encoding="utf-8")
    assert "--tag ${quoted_collector_image} --tag ${quoted_worker_image}" not in deploy
    assert "--build-arg JOBKOREA_OCR_ENABLED=true" in deploy


def test_collector_persists_models_and_has_resource_guardrails() -> None:
    compose = ROOT / "Infra/compose/compose.yaml"
    collector = _service_block(compose, "collector")

    assert 'cpus: "${COLLECTOR_CPUS:-2.0}"' in collector
    assert 'mem_limit: "${COLLECTOR_MEMORY_LIMIT:-4g}"' in collector
    assert "PADDLE_PDX_CACHE_HOME:" in collector
    assert "/data/.paddlex" in collector
    assert "PADDLE_PDX_CPU_NUM_THREADS:" in collector
    assert "collector-state:/data" in collector
