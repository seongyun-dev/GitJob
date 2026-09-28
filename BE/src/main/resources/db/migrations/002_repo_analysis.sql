-- S15P21E102-121. The repository analysis worker's own state.
-- Apply explicitly, the same way 001_c_compute.sql is applied.
--
-- Separate schema on purpose. analysis_job belongs to the Spring service, which
-- runs with ddl-auto=validate and owns its status vocabulary; a second writer in
-- another language would turn every column change into a two-repository
-- migration. Job status travels back over the results topic instead, so B stays
-- the only writer of its own table.
CREATE SCHEMA IF NOT EXISTS repo_analysis;

-- One row per Kafka event_id. The request topic is fed by Debezium, which is
-- at-least-once, and the runbook has operators re-publish events by hand, so the
-- same event arrives more than once by design.
--
-- state CLONING is a lease, not a fact: a worker that dies mid-clone leaves one
-- behind, and without a takeover rule that event is stuck forever. The claim
-- query reclaims a CLONING row older than the lease, which therefore has to be
-- longer than the slowest clone or two workers run at once.
CREATE TABLE IF NOT EXISTS repo_analysis.event_claim (
    event_id varchar(80) PRIMARY KEY,
    analysis_id varchar(80) NOT NULL,
    state varchar(16) NOT NULL CHECK (state IN ('CLONING', 'CLONED', 'FAILED')),
    attempt integer NOT NULL DEFAULT 1 CHECK (attempt > 0),
    error_code varchar(64),
    claimed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Operators look for stuck leases and recent failures; both scan by state.
CREATE INDEX IF NOT EXISTS idx_repo_analysis_claim_state
    ON repo_analysis.event_claim (state, claimed_at);
