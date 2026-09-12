-- S15P21E102-221. Callable-scoped binding for the additive .4 Rule Pack.
-- Existing .2/.3 Registry, Rule Pack and normalized evidence rows stay unchanged.
ALTER TABLE evidence_rule
    DROP CONSTRAINT ck_evidence_rule_binding_fields,
    ADD CONSTRAINT ck_evidence_rule_binding_fields
        CHECK (binding_fields <@ ARRAY['FILE_PATH', 'COMPONENT', 'FUNCTION']::TEXT[]
          AND (NOT (binding_fields && ARRAY['COMPONENT', 'FUNCTION']::TEXT[])
               OR 'FILE_PATH' = ANY(binding_fields)));
