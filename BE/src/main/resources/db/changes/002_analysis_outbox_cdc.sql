-- Debezium CDC prerequisites for analysis_outbox. Apply once as the database owner,
-- after the schema exists: db/init.sql for a new database, or db/changes/001 for one
-- that predates the outbox table. These objects are kept out of init.sql on purpose so
-- that the schema file stays runnable with nothing to substitute.
-- Requires PostgreSQL started with wal_level=logical (see Infra/compose/compose.yaml).
-- No credential is committed here: replace both placeholders before running.
--   __CDC_PASSWORD__   password for the replication role, same value as CDC_DATABASE_PASSWORD
--   __DATABASE_NAME__  target database, normally the POSTGRES_DB value
--
-- The connector never writes to analysis_outbox: SELECT is enough for the
-- snapshot, and the publication feeds streaming from the WAL.
CREATE ROLE gitjob_cdc WITH LOGIN REPLICATION PASSWORD '__CDC_PASSWORD__';
GRANT CONNECT ON DATABASE __DATABASE_NAME__ TO gitjob_cdc;
GRANT USAGE ON SCHEMA public TO gitjob_cdc;
GRANT SELECT ON public.analysis_outbox TO gitjob_cdc;

-- analysis_outbox can stay idle for hours. Debezium only confirms a replication
-- slot LSN when it sees WAL for a captured table, so without a table it can
-- write to, the slot pins WAL and the disk fills. The heartbeat query gives it
-- one, and the table is published so the heartbeat itself produces WAL.
CREATE TABLE public.cdc_heartbeat (
    id INTEGER PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL
);
INSERT INTO public.cdc_heartbeat VALUES (1, now());
GRANT SELECT, UPDATE ON public.cdc_heartbeat TO gitjob_cdc;

CREATE PUBLICATION gitjob_analysis_outbox_pub
    FOR TABLE public.analysis_outbox, public.cdc_heartbeat;
