-- Duplicate protection and lookup support for analysis requests.
-- Apply once to a database created before this change; new databases get db/init.sql,
-- which carries the same three statements.
--
-- Before running on a database that already has rows, check for duplicates the new
-- unique index would reject, and resolve them first:
--
--   SELECT user_id, repository_id, count(*), array_agg(analysis_id)
--   FROM analysis_job
--   WHERE status IN ('QUEUED','COLLECTING','RUNNING','ANALYZING','RATE_LIMITED','CANCEL_REQUESTED')
--   GROUP BY user_id, repository_id HAVING count(*) > 1;

-- One in-progress analysis per (user, repository). The application checks this first, but
-- the check and the insert are separate statements, so two near-simultaneous requests can
-- both pass it. This index is what actually decides the race.
-- The status list must stay in sync with AnalysisJob.IN_PROGRESS_STATUSES.
CREATE UNIQUE INDEX uq_analysis_job_active
    ON analysis_job (user_id, repository_id)
    WHERE status IN ('QUEUED', 'COLLECTING', 'RUNNING', 'ANALYZING', 'RATE_LIMITED', 'CANCEL_REQUESTED');

-- Serves the duplicate check itself; the partial index above cannot, because the query
-- binds the status list as parameters.
CREATE INDEX idx_analysis_job_user_repository
    ON analysis_job (user_id, repository_id);

-- PostgreSQL does not index the child side of a foreign key automatically.
CREATE INDEX idx_analysis_outbox_analysis_id
    ON analysis_outbox (analysis_id);
