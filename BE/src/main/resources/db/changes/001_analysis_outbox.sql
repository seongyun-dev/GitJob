-- Apply once to an existing PostgreSQL database BEFORE starting the outbox-enabled backend.
-- Fresh installations can apply db/init.sql (which also contains this table).
CREATE TABLE analysis_outbox (
    event_id VARCHAR(80) PRIMARY KEY,
    analysis_id VARCHAR(80) NOT NULL REFERENCES analysis_job(analysis_id),
    analysis_repository_id VARCHAR(80) NOT NULL,
    topic VARCHAR(249) NOT NULL,
    event_json TEXT NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    last_error_code VARCHAR(64)
);
CREATE INDEX idx_analysis_outbox_pending
    ON analysis_outbox (status, next_attempt_at, created_at, event_id);
