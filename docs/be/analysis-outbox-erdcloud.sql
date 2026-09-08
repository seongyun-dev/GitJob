-- PostgreSQL DDL for importing analysis_outbox into the existing ERDCloud diagram.
-- The diagram must already contain analysis_job with analysis_id as its primary key.
-- Documentation export only: use db/changes/001_analysis_outbox.sql for DB deployment.

CREATE TABLE "analysis_outbox" (
    "event_id" VARCHAR(80) NOT NULL,
    "analysis_id" VARCHAR(80) NOT NULL,
    "analysis_repository_id" VARCHAR(80) NOT NULL,
    "topic" VARCHAR(249) NOT NULL,
    "event_json" TEXT NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMPTZ NOT NULL,
    "next_attempt_at" TIMESTAMPTZ NOT NULL,
    "published_at" TIMESTAMPTZ NULL,
    "last_error_code" VARCHAR(64) NULL
);

ALTER TABLE "analysis_outbox"
    ADD CONSTRAINT "PK_ANALYSIS_OUTBOX" PRIMARY KEY ("event_id");

ALTER TABLE "analysis_outbox"
    ADD CONSTRAINT "FK_analysis_job_TO_analysis_outbox"
    FOREIGN KEY ("analysis_id") REFERENCES "analysis_job" ("analysis_id");

ALTER TABLE "analysis_outbox"
    ADD CONSTRAINT "CK_ANALYSIS_OUTBOX_STATUS"
    CHECK ("status" IN ('PENDING', 'PUBLISHED', 'FAILED'));

ALTER TABLE "analysis_outbox"
    ADD CONSTRAINT "CK_ANALYSIS_OUTBOX_ATTEMPTS" CHECK ("attempts" >= 0);

CREATE INDEX "idx_analysis_outbox_pending"
    ON "analysis_outbox" ("status", "next_attempt_at", "created_at", "event_id");
