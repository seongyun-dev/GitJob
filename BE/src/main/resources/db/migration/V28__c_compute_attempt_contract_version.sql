-- 계산 계약 변경 시 구 버전의 FAILED/RETRYING 시도가 새 계산을 막지 않게 한다.
-- 기존 행은 모두 이전 계약에서 만들어졌으므로 legacy로 분리한다.
ALTER TABLE user_c_compute_attempt
    ADD COLUMN compute_contract_version VARCHAR(80) NOT NULL DEFAULT 'legacy';

-- 롤링 배포 중 아직 살아 있는 구 BE의 INSERT는 버전 필드를 보내지 않는다.
-- 이 경우 계속 legacy로 분류해 새 계약의 시도를 가로막지 않게 한다.

COMMENT ON COLUMN user_c_compute_attempt.compute_contract_version IS
    '시도 당시 BE-C 계산 계약. 다른 계약의 시도는 새 계약의 재시도를 막지 않는다.';
