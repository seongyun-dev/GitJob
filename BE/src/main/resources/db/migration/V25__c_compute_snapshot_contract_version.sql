-- 활성 매칭 계산 계약이 바뀐 뒤에도 기존 Snapshot을 영구 재사용하지 않게 한다.
-- 기존 행은 legacy로 표시되어 복구 scheduler가 현재 계약으로 한 번 다시 계산한다.
ALTER TABLE user_c_snapshot
    ADD COLUMN compute_contract_version VARCHAR(80) NOT NULL DEFAULT 'legacy';

ALTER TABLE user_c_snapshot
    ALTER COLUMN compute_contract_version DROP DEFAULT;

-- 같은 Evidence·cohort라도 추천 알고리즘 계약이 바뀌면 결과가 달라질 수 있다.
-- 기존 3열 PK는 새 계약 행을 막으므로 계약 버전까지 identity에 포함한다.
ALTER TABLE user_c_snapshot
    DROP CONSTRAINT user_c_snapshot_pkey,
    ADD PRIMARY KEY (
        user_id, evidence_version, cohort_snapshot_id, compute_contract_version
    );

COMMENT ON COLUMN user_c_snapshot.compute_contract_version IS
    'BE-C 활성 매칭 계산 계약. 현재 계약과 다른 Snapshot은 복구 scheduler가 재계산한다.';
