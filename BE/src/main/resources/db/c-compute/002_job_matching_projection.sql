-- S15P21E102-185. Forward-only projection for bounded matching list/detail reads.
CREATE TABLE IF NOT EXISTS c_compute.matching_source (
    cohort_snapshot_id varchar(66) NOT NULL REFERENCES c_compute.snapshot(snapshot_id),
    job_id varchar(256) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    source_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (cohort_snapshot_id, job_id),
    CHECK (payload ->> 'job_id' = job_id)
);

CREATE TABLE IF NOT EXISTS c_compute.matching_calculation (
    recommendation_snapshot_id varchar(66) PRIMARY KEY
        REFERENCES c_compute.snapshot(snapshot_id),
    storage_version varchar(64) NOT NULL
        CHECK (storage_version = 'job-matching-storage/v2'),
    calculation_snapshot_id varchar(73) NOT NULL,
    owner varchar(128) NOT NULL CHECK (owner <> ''),
    cohort_snapshot_id varchar(66) NOT NULL REFERENCES c_compute.snapshot(snapshot_id),
    analysis_id varchar(128) NOT NULL,
    cohort_id varchar(128) NOT NULL,
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    metadata_hash char(64) NOT NULL,
    total_count integer NOT NULL CHECK (total_count >= 0),
    eligible_count integer NOT NULL CHECK (eligible_count >= 0),
    conditional_count integer NOT NULL CHECK (conditional_count >= 0),
    stored_bytes bigint NOT NULL CHECK (stored_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (total_count = eligible_count + conditional_count)
);

CREATE TABLE IF NOT EXISTS c_compute.matching_job (
    recommendation_snapshot_id varchar(66) NOT NULL
        REFERENCES c_compute.matching_calculation(recommendation_snapshot_id),
    cohort_snapshot_id varchar(66) NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    job_id varchar(256) NOT NULL,
    eligibility varchar(16) NOT NULL
        CHECK (eligibility IN ('ELIGIBLE', 'CONDITIONAL')),
    assessment jsonb NOT NULL CHECK (jsonb_typeof(assessment) = 'object'),
    assessment_hash char(64) NOT NULL,
    PRIMARY KEY (recommendation_snapshot_id, job_id),
    UNIQUE (recommendation_snapshot_id, position),
    FOREIGN KEY (cohort_snapshot_id, job_id)
        REFERENCES c_compute.matching_source(cohort_snapshot_id, job_id)
);

CREATE INDEX IF NOT EXISTS c_matching_job_page
    ON c_compute.matching_job(recommendation_snapshot_id, eligibility, position);

CREATE FUNCTION c_compute.reject_matching_row_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'published matching rows are immutable' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER c_matching_source_immutable
    BEFORE UPDATE OR DELETE ON c_compute.matching_source
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();

CREATE TRIGGER c_matching_job_immutable
    BEFORE UPDATE OR DELETE ON c_compute.matching_job
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();
