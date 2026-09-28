-- Keep the C review store aligned with the unbounded A-to-C snapshot ID contract.
-- Existing rows and foreign-key relationships are preserved; no value is truncated.
ALTER TABLE c_compute.registry_review
    ALTER COLUMN source_dataset_snapshot_id TYPE text;
