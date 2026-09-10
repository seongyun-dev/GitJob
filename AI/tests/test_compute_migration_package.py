"""Runtime readiness must not require a migration absent from the Worker image."""

from pathlib import Path

from worker.store import MIGRATION_FILES, MIGRATION_VERSION


def test_worker_image_packages_every_required_compute_migration():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Infra/docker/worker/Dockerfile").read_text(encoding="utf-8")
    assert len(MIGRATION_FILES) == MIGRATION_VERSION
    for path in MIGRATION_FILES:
        source = path.relative_to(root).as_posix()
        assert f"COPY {source} /app/migrations/{path.name}" in dockerfile


def test_forward_migration_keeps_contract_valid_dataset_ids_lossless():
    assert MIGRATION_VERSION == 4
    migration = MIGRATION_FILES[-1]
    assert migration.name == "004_registry_review_source_identity.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    assert "alter column source_dataset_snapshot_id type text" in sql
