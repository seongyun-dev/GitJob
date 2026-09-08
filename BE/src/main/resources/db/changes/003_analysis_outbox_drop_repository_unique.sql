-- Drops the UNIQUE constraint on analysis_outbox.analysis_repository_id.
-- Apply once to a database created before this change; new databases get
-- db/init.sql, which no longer has it.
--
-- The constraint never fired in normal operation: analysis_repository_id is a fresh
-- UUID per request, so two rows never collided. What it did do was block the documented
-- recovery path, which re-inserts the same event_json under a new event_id. Keeping the
-- same analysis_repository_id there is the point -- it is the Kafka key, so a re-published
-- event lands on the same partition as the original and stays in order behind it.
--
-- Uniqueness of an outbox row is still enforced by the event_id primary key.
ALTER TABLE public.analysis_outbox
    DROP CONSTRAINT analysis_outbox_analysis_repository_id_key;
