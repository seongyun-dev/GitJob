-- S15P21E102-221. Structural depth facts for the new immutable .3 Rule Pack.
-- Keep V7/V9/V11_1 and all existing Registry/Rule Pack data unchanged.
ALTER TABLE evidence_rule
    DROP CONSTRAINT ck_evidence_rule_binding_fields,
    ADD CONSTRAINT ck_evidence_rule_binding_fields
        CHECK (binding_fields <@ ARRAY['FILE_PATH', 'COMPONENT']::TEXT[]
          AND (NOT ('COMPONENT' = ANY(binding_fields)) OR 'FILE_PATH' = ANY(binding_fields)));

ALTER TABLE evidence_rule_clause
    DROP CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_FACT_TYPE",
    ADD CONSTRAINT "CK_EVIDENCE_RULE_CLAUSE_FACT_TYPE"
        CHECK (fact_type IN ('IMPORT', 'DEPENDENCY', 'ANNOTATION', 'CONFIG_KEY',
                            'API_CALL', 'SOURCE_FILE', 'SYNTAX_NODE'));

ALTER TABLE evidence_rule_predicate
    DROP CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD",
    ADD CONSTRAINT "CK_EVIDENCE_RULE_PREDICATE_FIELD"
        CHECK (fact_field IN ('MODULE', 'TECH_ID', 'COORDINATE', 'ECOSYSTEM',
                             'SCOPE', 'LANGUAGE', 'FILE_PATH', 'CALL', 'METHOD',
                             'RECEIVER', 'NAME', 'FORMAT', 'KEY', 'VALUE',
                             'EXTENSION', 'SLOC', 'IS_TEST', 'LOCAL_NAMES',
                             'KIND', 'RESOLVED_LOCAL_NAME', 'RESOLVED_MODULE', 'COMPONENT'));

ALTER TABLE technology_rule_support
    DROP CONSTRAINT technology_rule_support_required_fact_types_check,
    ADD CONSTRAINT technology_rule_support_required_fact_types_check
        CHECK (required_fact_types <@ ARRAY['IMPORT', 'DEPENDENCY', 'ANNOTATION',
                     'CONFIG_KEY', 'API_CALL', 'SOURCE_FILE', 'SYNTAX_NODE']::TEXT[]);
