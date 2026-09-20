-- S15P21E102-360. Immutable search facts and atomically published job projections.
CREATE FUNCTION c_compute.array_sort_distinct(values_to_sort text[])
RETURNS text[]
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT COALESCE(array_agg(value ORDER BY value), '{}')
    FROM (SELECT DISTINCT unnest(values_to_sort) AS value) AS distinct_values
    WHERE value IS NOT NULL;
$$;

CREATE TABLE IF NOT EXISTS c_compute.job_fact (
    job_fact_id char(64) PRIMARY KEY,
    schema_version varchar(64) NOT NULL CHECK (schema_version = 'job-fact/v1'),
    job_key varchar(256) NOT NULL,
    source_site varchar(32) NOT NULL,
    source_posting_id varchar(192) NOT NULL,
    content_hash varchar(128) NOT NULL,
    registry_version varchar(128) NOT NULL,
    parser_version varchar(128) NOT NULL,
    requirements_version varchar(128) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (job_key, content_hash, payload_hash),
    CHECK (job_fact_id ~ '^[0-9a-f]{64}$'),
    CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CHECK (pg_column_size(payload) <= 1048576)
);

CREATE TABLE IF NOT EXISTS c_compute.job_projection_version (
    projection_version_id varchar(80) PRIMARY KEY,
    state varchar(16) NOT NULL
        CHECK (state IN ('BUILDING', 'PUBLISHED', 'FAILED')),
    input_union_id varchar(128) NOT NULL,
    input_signature char(64) NOT NULL CHECK (input_signature ~ '^[0-9a-f]{64}$'),
    registry_version varchar(128) NOT NULL,
    parser_version varchar(128) NOT NULL,
    quality_version varchar(128) NOT NULL,
    requirements_version varchar(128) NOT NULL,
    aggregation_version varchar(128) NOT NULL,
    observed_at timestamptz NOT NULL,
    published_at timestamptz,
    job_count integer NOT NULL CHECK (job_count >= 0),
    build_stats jsonb NOT NULL CHECK (jsonb_typeof(build_stats) = 'object'),
    error_code varchar(64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((state = 'PUBLISHED') = (published_at IS NOT NULL)),
    CHECK ((state = 'FAILED') = (error_code IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS c_compute.job_projection_job (
    projection_version_id varchar(80) NOT NULL
        REFERENCES c_compute.job_projection_version(projection_version_id),
    job_key varchar(256) NOT NULL,
    job_fact_id char(64) NOT NULL REFERENCES c_compute.job_fact(job_fact_id),
    source_site varchar(32) NOT NULL,
    role_codes text[] NOT NULL DEFAULT '{}',
    region_codes text[] NOT NULL DEFAULT '{}',
    region_state varchar(16) NOT NULL
        CHECK (region_state IN ('KNOWN', 'NATIONWIDE', 'UNKNOWN')),
    career_codes text[] NOT NULL DEFAULT '{}',
    career_state varchar(16) NOT NULL
        CHECK (career_state IN ('KNOWN', 'UNRESTRICTED', 'AMBIGUOUS', 'UNKNOWN')),
    posting_status varchar(16) NOT NULL
        CHECK (posting_status IN ('ACTIVE', 'CLOSED', 'UNKNOWN')),
    body_status varchar(32) NOT NULL
        CHECK (body_status IN ('TEXT_AVAILABLE', 'IMAGE_ONLY', 'BLOCKED', 'MISSING', 'PARSE_FAILED')),
    posted_at timestamptz,
    deadline timestamptz,
    collected_at timestamptz NOT NULL,
    required_tech_ids text[] NOT NULL DEFAULT '{}',
    preferred_tech_ids text[] NOT NULL DEFAULT '{}',
    general_tech_ids text[] NOT NULL DEFAULT '{}',
    quality_flags text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (projection_version_id, job_key),
    CHECK (role_codes = c_compute.array_sort_distinct(role_codes)),
    CHECK (region_codes = c_compute.array_sort_distinct(region_codes)),
    CHECK (career_codes = c_compute.array_sort_distinct(career_codes)),
    CHECK (required_tech_ids = c_compute.array_sort_distinct(required_tech_ids)),
    CHECK (preferred_tech_ids = c_compute.array_sort_distinct(preferred_tech_ids)),
    CHECK (general_tech_ids = c_compute.array_sort_distinct(general_tech_ids)),
    CHECK (quality_flags = c_compute.array_sort_distinct(quality_flags))
);

CREATE TABLE IF NOT EXISTS c_compute.job_projection_head (
    stream varchar(64) PRIMARY KEY CHECK (stream = 'JOB_SEARCH'),
    projection_version_id varchar(80) NOT NULL
        REFERENCES c_compute.job_projection_version(projection_version_id),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS c_job_projection_job_source
    ON c_compute.job_projection_job(projection_version_id, source_site);
CREATE INDEX IF NOT EXISTS c_job_projection_job_status_deadline
    ON c_compute.job_projection_job(projection_version_id, posting_status, deadline);
CREATE INDEX IF NOT EXISTS c_job_projection_job_roles
    ON c_compute.job_projection_job USING gin(role_codes);
CREATE INDEX IF NOT EXISTS c_job_projection_job_regions
    ON c_compute.job_projection_job USING gin(region_codes);
CREATE INDEX IF NOT EXISTS c_job_projection_job_careers
    ON c_compute.job_projection_job USING gin(career_codes);

CREATE TRIGGER c_job_fact_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_fact
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();

CREATE TRIGGER c_job_projection_job_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_projection_job
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();
