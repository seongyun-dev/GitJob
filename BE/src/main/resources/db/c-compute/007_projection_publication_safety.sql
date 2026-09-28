-- S15P21E102-360. Forward-only ordering and fact-source safety for current results.
ALTER TABLE c_compute.user_result
    ALTER COLUMN target_key TYPE varchar(200);

ALTER TABLE c_compute.user_result_head
    ALTER COLUMN target_key TYPE varchar(200),
    ADD COLUMN source_occurred_at timestamptz,
    ADD COLUMN source_order_key varchar(128);

UPDATE c_compute.user_result_head h
SET source_occurred_at = h.updated_at,
    source_order_key = h.result_id
WHERE h.source_occurred_at IS NULL;

ALTER TABLE c_compute.user_result_head
    ALTER COLUMN source_occurred_at SET NOT NULL,
    ALTER COLUMN source_order_key SET NOT NULL;

CREATE TABLE c_compute.matching_source_fact (
    cohort_snapshot_id varchar(66) NOT NULL REFERENCES c_compute.snapshot(snapshot_id),
    job_id varchar(256) NOT NULL,
    job_fact_id char(64) NOT NULL REFERENCES c_compute.job_fact(job_fact_id),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    source_hash char(64) NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (cohort_snapshot_id, job_id, job_fact_id),
    CHECK (payload ->> 'job_id' = job_id)
);

CREATE TRIGGER c_matching_source_fact_immutable
    BEFORE UPDATE OR DELETE ON c_compute.matching_source_fact
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();

-- 006 wrote at most one immutable source per cohort/job and copied that exact
-- job_fact_id to matching_job. Lift those rows into the versioned table before
-- validating the new FK so pre-007 results stay readable and protected.
INSERT INTO c_compute.matching_source_fact
    (cohort_snapshot_id, job_id, job_fact_id, payload, source_hash, created_at)
SELECT cohort_snapshot_id, job_id, job_fact_id, payload, source_hash, created_at
FROM c_compute.matching_source
WHERE job_fact_id IS NOT NULL
ON CONFLICT DO NOTHING;

ALTER TABLE c_compute.matching_job
    ADD CONSTRAINT c_matching_job_fact_source_fk
    FOREIGN KEY (cohort_snapshot_id, job_id, job_fact_id)
    REFERENCES c_compute.matching_source_fact(cohort_snapshot_id, job_id, job_fact_id)
    NOT VALID;

ALTER TABLE c_compute.matching_job
    VALIDATE CONSTRAINT c_matching_job_fact_source_fk;

ALTER TABLE c_compute.job_projection_head
    ADD COLUMN observed_at timestamptz;

UPDATE c_compute.job_projection_head h
SET observed_at = v.observed_at
FROM c_compute.job_projection_version v
WHERE v.projection_version_id = h.projection_version_id
  AND h.observed_at IS NULL;

ALTER TABLE c_compute.job_projection_head
    ALTER COLUMN observed_at SET NOT NULL;

CREATE TABLE c_compute.job_projection_block (
    projection_version_id varchar(80) PRIMARY KEY
        REFERENCES c_compute.job_projection_version(projection_version_id),
    reason text NOT NULL CHECK (reason <> ''),
    actor varchar(128) NOT NULL CHECK (actor <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE c_compute.job_projection_head_audit (
    change_id uuid PRIMARY KEY,
    from_projection_version_id varchar(80) NOT NULL
        REFERENCES c_compute.job_projection_version(projection_version_id),
    to_projection_version_id varchar(80) NOT NULL
        REFERENCES c_compute.job_projection_version(projection_version_id),
    actor varchar(128) NOT NULL CHECK (actor <> ''),
    reason text NOT NULL CHECK (reason <> ''),
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (from_projection_version_id <> to_projection_version_id)
);

CREATE TRIGGER c_job_projection_block_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_projection_block
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();

CREATE TRIGGER c_job_projection_head_audit_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_projection_head_audit
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();
