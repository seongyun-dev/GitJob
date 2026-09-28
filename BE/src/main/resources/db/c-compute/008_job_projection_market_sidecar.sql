-- S15P21E102-363. Typed Current Market data and selector-sensitive
-- cross-site candidates for payload-free demand summaries.
CREATE TABLE c_compute.job_projection_market_job (
    projection_version_id varchar(80) NOT NULL,
    job_key varchar(256) NOT NULL,
    normalized_company text NOT NULL,
    normalized_title text NOT NULL,
    market_region_identity text NOT NULL,
    raw_region_identity text NOT NULL,
    raw_career_identity text NOT NULL,
    market_required_tech_ids text[] NOT NULL DEFAULT '{}',
    market_preferred_tech_ids text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (projection_version_id, job_key),
    FOREIGN KEY (projection_version_id, job_key)
        REFERENCES c_compute.job_projection_job(projection_version_id, job_key),
    CHECK (market_required_tech_ids =
           c_compute.array_sort_distinct(market_required_tech_ids)),
    CHECK (market_preferred_tech_ids =
           c_compute.array_sort_distinct(market_preferred_tech_ids))
);

CREATE TABLE c_compute.job_projection_market_candidate (
    projection_version_id varchar(80) NOT NULL,
    left_job_key varchar(256) NOT NULL,
    right_job_key varchar(256) NOT NULL,
    PRIMARY KEY (projection_version_id, left_job_key, right_job_key),
    FOREIGN KEY (projection_version_id, left_job_key)
        REFERENCES c_compute.job_projection_job(projection_version_id, job_key),
    FOREIGN KEY (projection_version_id, right_job_key)
        REFERENCES c_compute.job_projection_job(projection_version_id, job_key),
    CHECK (left_job_key <> right_job_key)
);

CREATE INDEX c_job_projection_market_candidate_right
    ON c_compute.job_projection_market_candidate
       (projection_version_id, right_job_key);

CREATE TRIGGER c_job_projection_market_job_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_projection_market_job
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();

CREATE TRIGGER c_job_projection_market_candidate_immutable
    BEFORE UPDATE OR DELETE ON c_compute.job_projection_market_candidate
    FOR EACH ROW EXECUTE FUNCTION c_compute.reject_matching_row_mutation();
