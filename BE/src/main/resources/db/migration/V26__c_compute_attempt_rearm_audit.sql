-- S15P21E102-363. Operator-only terminal attempt rearm with an append-only audit.
ALTER TABLE user_c_compute_attempt
    DROP CONSTRAINT IF EXISTS user_c_compute_attempt_attempt_count_check;
ALTER TABLE user_c_compute_attempt
    ADD CONSTRAINT user_c_compute_attempt_attempt_count_check
        CHECK (attempt_count >= 0);

CREATE TABLE user_c_compute_attempt_rearm_audit (
    rearm_id           UUID         PRIMARY KEY,
    user_id            BIGINT       NOT NULL REFERENCES "user"("user_id"),
    target_key         VARCHAR(200) NOT NULL,
    evidence_version   VARCHAR(64)  NOT NULL,
    before_reason      VARCHAR(80),
    before_attempt_count INTEGER    NOT NULL CHECK (before_attempt_count > 0),
    before_run_token   UUID         NOT NULL,
    after_run_token    UUID         NOT NULL,
    actor_user_id      BIGINT       NOT NULL REFERENCES "user"("user_id"),
    operator_reason    TEXT         NOT NULL CHECK (btrim(operator_reason) <> ''),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    CHECK (before_run_token <> after_run_token)
);

COMMENT ON TABLE user_c_compute_attempt_rearm_audit IS
    'FAILED C 계산을 exact-CAS로 재개한 관리자 작업의 append-only 감사 기록';

CREATE OR REPLACE FUNCTION reject_compute_rearm_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'compute attempt rearm audit rows are immutable';
END;
$$;

CREATE TRIGGER user_c_compute_attempt_rearm_audit_immutable
    BEFORE UPDATE OR DELETE ON user_c_compute_attempt_rearm_audit
    FOR EACH ROW EXECUTE FUNCTION reject_compute_rearm_audit_mutation();
