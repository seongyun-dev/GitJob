-- Debezium CDC prerequisites that the Flyway migrations deliberately do not own.
-- Apply once as the database owner, after the migrations have run.
--
-- These are kept out of db/migration for three reasons: the password has to be
-- substituted in, CREATE ROLE is a cluster-level object rather than a schema
-- change, and neither CREATE ROLE nor CREATE PUBLICATION can be re-run. A
-- failed migration would leave the application unable to start.
--
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
GRANT SELECT, UPDATE ON public.cdc_heartbeat TO gitjob_cdc;

CREATE PUBLICATION gitjob_analysis_outbox_pub
    FOR TABLE public.analysis_outbox, public.cdc_heartbeat;
