-- C 계산 시도의 안정적인 상태 (S15P21E102-308).
--
-- 공개 GET은 이 표를 읽기만 한다. 분석 완료나 목표 직무 변경이 계산을 시작하고,
-- 영구 오류는 같은 Evidence/목표 조합에서 다시 보내지 않는다.
CREATE TABLE user_c_compute_attempt (
    user_id          BIGINT       NOT NULL REFERENCES "user"("user_id"),
    target_key       VARCHAR(200) NOT NULL,
    evidence_version VARCHAR(64)  NOT NULL CHECK (evidence_version ~ '^[0-9a-f]{64}$'),
    status            VARCHAR(16)  NOT NULL
        CHECK (status IN ('RUNNING', 'RETRYING', 'FAILED')),
    reason            VARCHAR(80),
    attempt_count     INTEGER      NOT NULL CHECK (attempt_count > 0),
    run_token         UUID         NOT NULL,
    next_retry_at     TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (user_id, target_key, evidence_version)
);

COMMENT ON TABLE user_c_compute_attempt IS
    'C 계산의 진행, 재시도, 영구 실패 상태. GET은 이 상태를 노출할 뿐 계산하지 않는다.';
COMMENT ON COLUMN user_c_compute_attempt.next_retry_at IS
    'RUNNING lease 또는 RETRYING backoff가 끝나는 시각. 이 전에는 같은 계산을 다시 보내지 않는다.';
COMMENT ON COLUMN user_c_compute_attempt.run_token IS
    '실행마다 새로 발급하는 fencing token. 삭제·재생성 뒤 돌아온 이전 worker의 상태 변경을 막는다.';
