-- S15P21E102-33. Apply explicitly with python -m worker.migrate.
-- Existing public Registry/Evidence tables are intentionally unchanged.
CREATE SCHEMA IF NOT EXISTS c_compute;

CREATE TABLE IF NOT EXISTS c_compute.schema_version (
    version integer PRIMARY KEY,
    checksum char(64) NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS c_compute.event (
    event_id varchar(128) PRIMARY KEY,
    kind varchar(24) NOT NULL,
    owner varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    occurred_at timestamptz NOT NULL,
    state varchar(16) NOT NULL CHECK (state IN ('RUNNING', 'COMPLETED', 'FAILED')),
    lease_token uuid NOT NULL,
    lease_until timestamptz NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    results jsonb NOT NULL DEFAULT '[]',
    error_code varchar(64),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS c_compute.snapshot (
    snapshot_id varchar(66) PRIMARY KEY,
    kind varchar(24) NOT NULL CHECK (kind IN ('COHORT', 'DEMAND', 'RECOMMENDATION', 'PUBLIC_GITHUB', 'TREND')),
    owner varchar(128) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((kind = 'RECOMMENDATION' AND owner <> '') OR (kind <> 'RECOMMENDATION' AND owner = ''))
);
CREATE INDEX IF NOT EXISTS c_snapshot_owner_kind ON c_compute.snapshot(owner, kind);

CREATE TABLE IF NOT EXISTS c_compute.head (
    kind varchar(24) NOT NULL,
    owner varchar(128) NOT NULL,
    stream varchar(160) NOT NULL,
    snapshot_id varchar(66) NOT NULL REFERENCES c_compute.snapshot(snapshot_id),
    occurred_at timestamptz NOT NULL,
    event_id varchar(128) NOT NULL REFERENCES c_compute.event(event_id),
    PRIMARY KEY (kind, owner, stream)
);
