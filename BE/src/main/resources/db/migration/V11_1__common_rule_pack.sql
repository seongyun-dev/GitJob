-- S15P21E102-221. New common Registry/Rule Pack publication metadata.
-- 11.1 follows develop V11 without colliding with B's unmerged V12/V13.
-- Existing versions, CURRENT selection and V7/V9 rows are preserved.
-- Apply before V12/V13 on a fresh/upgraded V11 database. An environment that
-- already applied higher versions needs an explicit migration-order review.

ALTER TABLE evidence_rule
    ADD COLUMN binding_fields TEXT[] NOT NULL DEFAULT '{}',
    ADD CONSTRAINT ck_evidence_rule_binding_fields
        CHECK (binding_fields <@ ARRAY['FILE_PATH']::TEXT[]);

ALTER TABLE evidence_rule_clause
    DROP CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_FACT_TYPE",
    ADD CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_FACT_TYPE"
        CHECK (fact_type IN ('IMPORT', 'DEPENDENCY', 'ANNOTATION', 'CONFIG_KEY',
                            'API_CALL', 'SOURCE_FILE'));

ALTER TABLE evidence_rule_predicate
    DROP CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD",
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD"
        CHECK (fact_field IN ('MODULE', 'TECH_ID', 'COORDINATE', 'ECOSYSTEM',
                             'SCOPE', 'LANGUAGE', 'FILE_PATH', 'CALL', 'METHOD',
                             'RECEIVER', 'NAME', 'FORMAT', 'KEY', 'VALUE',
                             'EXTENSION', 'SLOC', 'IS_TEST', 'LOCAL_NAMES'));

CREATE TABLE technology_rule_pack (
    rule_pack_version TEXT PRIMARY KEY,
    registry_version VARCHAR(80) NOT NULL UNIQUE
        REFERENCES technology_registry(registry_version),
    content_sha256 VARCHAR(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    source_ref TEXT NOT NULL CHECK (length(trim(source_ref)) > 0),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (rule_pack_version, registry_version)
);

CREATE TABLE technology_rule_support (
    tech_id VARCHAR(80) NOT NULL,
    registry_version VARCHAR(80) NOT NULL,
    rule_pack_version TEXT NOT NULL,
    evaluation_scope VARCHAR(16) NOT NULL CHECK (evaluation_scope = 'REPOSITORY'),
    max_supported_level VARCHAR(2) NOT NULL
        CHECK (max_supported_level IN ('L0', 'L1', 'L2', 'L3')),
    coverage VARCHAR(16) NOT NULL CHECK (coverage IN ('SUPPORTED', 'PARTIAL', 'UNSUPPORTED')),
    required_fact_types TEXT[] NOT NULL,
    limitations JSONB NOT NULL CHECK (jsonb_typeof(limitations) = 'array'),
    PRIMARY KEY (tech_id, registry_version),
    FOREIGN KEY (tech_id, registry_version) REFERENCES technology(tech_id, registry_version),
    FOREIGN KEY (rule_pack_version, registry_version)
        REFERENCES technology_rule_pack(rule_pack_version, registry_version),
    CHECK (required_fact_types <@ ARRAY['IMPORT', 'DEPENDENCY', 'ANNOTATION',
                                       'CONFIG_KEY', 'API_CALL', 'SOURCE_FILE']::TEXT[])
);
