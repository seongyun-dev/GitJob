-- Debezium only confirms a replication slot LSN when it sees WAL for a captured
-- table. analysis_outbox can stay idle for hours, so without a table the
-- connector can write to, the slot pins WAL and the disk fills. This heartbeat
-- gives it one, and it is published so the heartbeat itself produces WAL.
--
-- The rest of the CDC setup needs a password substituted into it and creates a
-- cluster-level role, so it stays out of the migrations: see db/cdc/README or
-- db/cdc/cdc_prerequisites.sql.
CREATE TABLE public.cdc_heartbeat (
    id INTEGER PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL
);
INSERT INTO public.cdc_heartbeat VALUES (1, now());
