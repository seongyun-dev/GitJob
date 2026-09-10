-- S15P21E102-199. Add C-owned immutable snapshot metadata to the Registry
-- schema established by V1-V10.
--
-- Native B Registry versions keep their existing lifecycle and rule catalog.
-- Their C metadata remains NULL: this migration does not invent a content hash,
-- source provenance, or row ordering for data that C did not import. Complete C
-- snapshots are inserted as RETIRED by the importer and can be selected through
-- the C-only alias without changing B's single CURRENT version.

ALTER TABLE technology_registry
    ADD COLUMN content_sha256 VARCHAR(64),
    ADD COLUMN source_ref TEXT,
    ADD COLUMN imported_at TIMESTAMPTZ,
    ADD CONSTRAINT uq_c_registry_schema_version
        UNIQUE (schema_version, registry_version),
    ADD CONSTRAINT ck_c_registry_content_hash
        CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$') NOT VALID,
    ADD CONSTRAINT ck_c_registry_operational_metadata
        CHECK (
            (content_sha256 IS NULL AND source_ref IS NULL AND imported_at IS NULL)
            OR
            (content_sha256 IS NOT NULL AND NULLIF(BTRIM(source_ref), '') IS NOT NULL
             AND imported_at IS NOT NULL)
        ) NOT VALID;

ALTER TABLE technology
    ADD COLUMN registry_order INTEGER,
    ADD COLUMN provenance_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT ck_c_technology_registry_order
        CHECK (registry_order IS NULL OR registry_order >= 0) NOT VALID,
    ADD CONSTRAINT ck_c_technology_provenance_array
        CHECK (
            jsonb_typeof(provenance_refs) = 'array'
            AND (registry_order IS NULL OR jsonb_array_length(provenance_refs) > 0)
        ) NOT VALID;

CREATE UNIQUE INDEX uq_c_technology_registry_order
    ON technology (registry_version, registry_order)
    WHERE registry_order IS NOT NULL;

ALTER TABLE technology_mapping
    ADD COLUMN registry_order INTEGER,
    ADD COLUMN normalized_value TEXT,
    ADD COLUMN provenance_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT ck_c_technology_mapping_registry_order
        CHECK (registry_order IS NULL OR registry_order >= 0) NOT VALID,
    ADD CONSTRAINT ck_c_technology_mapping_provenance_array
        CHECK (
            jsonb_typeof(provenance_refs) = 'array'
            AND (registry_order IS NULL OR jsonb_array_length(provenance_refs) > 0)
        ) NOT VALID;

CREATE UNIQUE INDEX uq_c_technology_mapping_registry_order
    ON technology_mapping (registry_version, registry_order)
    WHERE registry_order IS NOT NULL;

CREATE UNIQUE INDEX uq_c_technology_mapping_normalized_source
    ON technology_mapping (
        registry_version,
        mapping_type,
        ecosystem,
        normalized_value
    ) NULLS NOT DISTINCT
    WHERE normalized_value IS NOT NULL;

ALTER TABLE technology_category
    ADD COLUMN category_order SMALLINT,
    ADD CONSTRAINT ck_c_technology_category_order
        CHECK (category_order IS NULL OR category_order >= 0) NOT VALID;

CREATE UNIQUE INDEX uq_c_technology_category_value
    ON technology_category (registry_version, tech_id, job_domain)
    WHERE category_order IS NOT NULL;

CREATE UNIQUE INDEX uq_c_technology_category_order
    ON technology_category (registry_version, tech_id, category_order)
    WHERE category_order IS NOT NULL;

-- This pointer is C-owned. It deliberately has no relationship with the B
-- lifecycle status and therefore cannot publish or retire an Evidence Rule set.
CREATE TABLE technology_registry_alias (
    schema_version VARCHAR(40) PRIMARY KEY,
    registry_version TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_c_registry_alias_snapshot
        FOREIGN KEY (schema_version, registry_version)
        REFERENCES technology_registry (schema_version, registry_version)
        ON DELETE RESTRICT
);
