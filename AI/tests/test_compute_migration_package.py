"""Runtime readiness must not require a migration absent from the Worker image."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from worker.store import MIGRATION_FILES, MIGRATION_VERSION, apply_migration


def test_worker_image_packages_every_required_compute_migration():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Infra/docker/worker/Dockerfile").read_text(encoding="utf-8")
    assert len(MIGRATION_FILES) == MIGRATION_VERSION
    for path in MIGRATION_FILES:
        source = path.relative_to(root).as_posix()
        assert f"COPY {source} /app/migrations/{path.name}" in dockerfile


def test_forward_migration_keeps_contract_valid_dataset_ids_lossless():
    migration = MIGRATION_FILES[3]
    sql = migration.read_text(encoding="utf-8").lower()
    assert "alter column source_dataset_snapshot_id type text" in sql


def test_job_search_projection_migration_is_forward_only_and_immutable():
    assert MIGRATION_VERSION == 7
    migration = MIGRATION_FILES[4]
    assert migration.name == "005_job_search_projection.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    assert "create table if not exists c_compute.job_fact" in sql
    assert "create table if not exists c_compute.job_projection_version" in sql
    assert "create table if not exists c_compute.job_projection_job" in sql
    assert "create table if not exists c_compute.job_projection_head" in sql
    assert "c_job_fact_immutable" in sql
    assert "c_job_projection_job_immutable" in sql


def test_current_result_migration_is_additive_and_keeps_legacy_snapshot_refs():
    migration = MIGRATION_FILES[5]
    assert migration.name == "006_current_result.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    assert "create table if not exists c_compute.user_result" in sql
    assert "create table if not exists c_compute.user_result_head" in sql
    assert "add column job_fact_id" in sql
    assert "add column result_id" in sql
    assert "recommendation_snapshot_id" in sql
    assert "drop table" not in sql


def test_projection_publication_safety_migration_is_forward_only():
    migration = MIGRATION_FILES[-1]
    assert migration.name == "007_projection_publication_safety.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    assert "source_occurred_at" in sql
    assert "source_order_key" in sql
    assert "create table c_compute.matching_source_fact" in sql
    assert "c_matching_job_fact_source_fk" in sql
    assert "insert into c_compute.matching_source_fact" in sql
    assert "validate constraint c_matching_job_fact_source_fk" in sql
    assert "job_projection_head_audit" in sql
    assert "c_job_projection_block_immutable" in sql
    assert "c_job_projection_head_audit_immutable" in sql
    assert "drop table" not in sql


def test_projection_publication_safety_upgrades_existing_fact_links():
    dsn = os.environ.get("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set C_COMPUTE_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    parameters = conninfo_to_dict(dsn)
    database_name = "c_compute_upgrade_" + uuid4().hex
    admin_dsn = make_conninfo(**{**parameters, "dbname": "postgres"})
    upgrade_dsn = make_conninfo(**{**parameters, "dbname": database_name})
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("isolated test database user cannot CREATE DATABASE")

    cohort_id = "c-" + "1" * 64
    recommendation_id = "c-" + "2" * 64
    fact_id = "3" * 64
    try:
        apply_migration(upgrade_dsn, MIGRATION_FILES[:6])
        with psycopg.connect(upgrade_dsn) as conn:
            conn.execute(
                "INSERT INTO c_compute.snapshot "
                "(snapshot_id, kind, owner, payload) VALUES "
                "(%s, 'COHORT', '', '{}'::jsonb), "
                "(%s, 'RECOMMENDATION', 'user-1', '{}'::jsonb)",
                (cohort_id, recommendation_id),
            )
            conn.execute(
                "INSERT INTO c_compute.job_fact "
                "(job_fact_id, schema_version, job_key, source_site, "
                "source_posting_id, content_hash, registry_version, parser_version, "
                "requirements_version, payload, payload_hash) VALUES "
                "(%s, 'job-fact/v1', 'SARAMIN:1', 'SARAMIN', '1', 'content-1', "
                "'registry-1', 'parser-1', 'requirements-1', '{}'::jsonb, %s)",
                (fact_id, "4" * 64),
            )
            conn.execute(
                "INSERT INTO c_compute.matching_source "
                "(cohort_snapshot_id, job_id, payload, source_hash, job_fact_id) "
                "VALUES (%s, 'SARAMIN:1', %s::jsonb, %s, %s)",
                (cohort_id, '{"job_id":"SARAMIN:1"}', "5" * 64, fact_id),
            )
            conn.execute(
                "INSERT INTO c_compute.matching_calculation "
                "(recommendation_snapshot_id, storage_version, calculation_snapshot_id, "
                "owner, cohort_snapshot_id, analysis_id, cohort_id, metadata, "
                "metadata_hash, total_count, eligible_count, conditional_count, stored_bytes) "
                "VALUES (%s, 'job-matching-storage/v2', 'calculation-1', 'user-1', %s, "
                "'analysis-1', 'cohort-1', '{}'::jsonb, %s, 1, 1, 0, 1)",
                (recommendation_id, cohort_id, "6" * 64),
            )
            conn.execute(
                "INSERT INTO c_compute.matching_job "
                "(recommendation_snapshot_id, cohort_snapshot_id, position, job_id, "
                "eligibility, assessment, assessment_hash, job_fact_id) "
                "VALUES (%s, %s, 0, 'SARAMIN:1', 'ELIGIBLE', '{}'::jsonb, %s, %s)",
                (recommendation_id, cohort_id, "7" * 64, fact_id),
            )

        apply_migration(upgrade_dsn)
        with psycopg.connect(upgrade_dsn) as conn:
            assert conn.execute(
                "SELECT count(*) FROM c_compute.matching_source_fact "
                "WHERE cohort_snapshot_id = %s AND job_id = 'SARAMIN:1' "
                "AND job_fact_id = %s",
                (cohort_id, fact_id),
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname = 'c_matching_job_fact_source_fk'"
            ).fetchone()[0]
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(
                sql.Identifier(database_name)
            ))
