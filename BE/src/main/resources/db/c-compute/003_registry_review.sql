-- S15P21E102-88. Persist unresolved C Registry mappings with cohort provenance.
CREATE TABLE IF NOT EXISTS c_compute.registry_review (
    review_id varchar(31) PRIMARY KEY,
    source_dataset_snapshot_id varchar(256) NOT NULL,
    source_hash char(64) NOT NULL,
    record jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    status varchar(16) NOT NULL CHECK (status IN ('PENDING', 'RESOLVED')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (source_dataset_snapshot_id <> '')
);

CREATE INDEX IF NOT EXISTS c_registry_review_status_id
    ON c_compute.registry_review(status, review_id);

CREATE TABLE IF NOT EXISTS c_compute.registry_review_cohort (
    review_id varchar(31) NOT NULL
        REFERENCES c_compute.registry_review(review_id) ON DELETE CASCADE,
    cohort_snapshot_id varchar(66) NOT NULL
        REFERENCES c_compute.snapshot(snapshot_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (review_id, cohort_snapshot_id)
);

CREATE INDEX IF NOT EXISTS c_registry_review_cohort_snapshot
    ON c_compute.registry_review_cohort(cohort_snapshot_id, review_id);

CREATE TABLE IF NOT EXISTS c_compute.registry_review_action (
    review_id varchar(31) NOT NULL
        REFERENCES c_compute.registry_review(review_id) ON DELETE CASCADE,
    idempotency_key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    action varchar(24) NOT NULL
        CHECK (action IN ('MANUAL_RESOLVE', 'REPROCESS')),
    actor varchar(128) NOT NULL,
    note text NOT NULL,
    registry_version varchar(128) NOT NULL,
    before_version integer NOT NULL CHECK (before_version > 0),
    after_version integer NOT NULL CHECK (after_version = before_version + 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (review_id, idempotency_key),
    CHECK (actor <> '' AND note <> '' AND registry_version <> '')
);
