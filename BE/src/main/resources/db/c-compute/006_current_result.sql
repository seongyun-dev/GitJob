-- S15P21E102-360. Immutable personalized results with per-target current pointers.
CREATE TABLE IF NOT EXISTS c_compute.user_result (
    result_id varchar(80) PRIMARY KEY,
    user_id varchar(128) NOT NULL CHECK (user_id <> ''),
    target_key varchar(160) NOT NULL CHECK (target_key <> ''),
    evidence_version varchar(128) NOT NULL,
    projection_version_id varchar(80)
        REFERENCES c_compute.job_projection_version(projection_version_id),
    compute_contract_version varchar(128) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('READY', 'FAILED')),
    recommendation_snapshot_id varchar(66) NOT NULL UNIQUE
        REFERENCES c_compute.snapshot(snapshot_id),
    compact_payload jsonb NOT NULL CHECK (jsonb_typeof(compact_payload) = 'object'),
    payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (result_id ~ '^ur-[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS c_compute.user_result_head (
    user_id varchar(128) NOT NULL CHECK (user_id <> ''),
    target_key varchar(160) NOT NULL CHECK (target_key <> ''),
    result_id varchar(80) NOT NULL REFERENCES c_compute.user_result(result_id),
    previous_result_id varchar(80) REFERENCES c_compute.user_result(result_id),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, target_key),
    CHECK (previous_result_id IS NULL OR previous_result_id <> result_id)
);

ALTER TABLE c_compute.matching_source
    ADD COLUMN job_fact_id char(64) REFERENCES c_compute.job_fact(job_fact_id);

ALTER TABLE c_compute.matching_calculation
    ADD COLUMN result_id varchar(80) REFERENCES c_compute.user_result(result_id);

ALTER TABLE c_compute.matching_job
    ADD COLUMN result_id varchar(80) REFERENCES c_compute.user_result(result_id),
    ADD COLUMN job_fact_id char(64) REFERENCES c_compute.job_fact(job_fact_id);

CREATE INDEX IF NOT EXISTS c_user_result_user_target_created
    ON c_compute.user_result(user_id, target_key, created_at DESC);
CREATE INDEX IF NOT EXISTS c_matching_source_job_fact
    ON c_compute.matching_source(job_fact_id);
CREATE INDEX IF NOT EXISTS c_matching_job_result_position
    ON c_compute.matching_job(result_id, position);

CREATE TRIGGER c_user_result_immutable
    BEFORE UPDATE OR DELETE ON c_compute.user_result
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();
