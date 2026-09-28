-- C 계산 연결에 필요한 두 테이블 (S15P21E102-279).
--
-- 계약은 docs/be/c-compute-public-api.md §2-A, §2-B.

-- 1. 목표 직무.
--
-- 화면 파라미터가 아니라 서버에 저장한다. 공고 모집단(cohort)을 고르려면 직무·지역·
-- 경력이 필요한데, 분석 완료 처리는 브라우저 없이 서버에서 돌기 때문이다. 화면에서만
-- 받으면 그 시점에 직무를 알 수 없어 계산을 시작할 수 없다.
--
-- 지역·경력을 표가 아니라 쉼표 문자열로 두는 이유는 이 값이 검색 대상이 아니라 C에
-- 그대로 넘기는 선택자이기 때문이다. 조인할 일이 없다. 빈 문자열은 "전체"다 --
-- NULL 과 구분할 필요가 없어 NOT NULL 기본값으로 둔다.
CREATE TABLE user_target (
    user_id       BIGINT       PRIMARY KEY REFERENCES "user"("user_id"),
    target_role   VARCHAR(60)  NOT NULL CHECK (length(trim(target_role)) > 0),
    regions       VARCHAR(200) NOT NULL DEFAULT '',
    career_levels VARCHAR(200) NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ  NOT NULL
);

COMMENT ON TABLE user_target IS
    '사용자의 목표 직무와 공고 필터. C cohort resolve 의 selector 입력이다.';
COMMENT ON COLUMN user_target.regions IS
    '쉼표 구분. 빈 문자열은 전체를 뜻하며 C selector 에서 필드를 생략한다.';

-- 2. C 계산 결과 pointer.
--
-- C 가 계산한 Snapshot 의 ID 만 보관한다. 계산 결과 자체는 C 의 DB 에 있고 B 는
-- 조회할 때마다 C 에 묻는다. 여기에 결과를 복제하면 두 곳이 어긋나는 순간
-- 화면이 어느 쪽을 믿어야 할지 알 수 없게 된다.
--
-- 기본키가 (user_id, evidence_version, cohort_snapshot_id) 인 것은 같은 Evidence 라도
-- 목표 직무가 다르면 다른 결과이기 때문이다. 직무를 바꿨다고 이전 결과를 지우지
-- 않는다 -- 되돌리면 재계산 없이 바로 보인다.
--
-- event_id UNIQUE 가 중복 계산을 막는 마지막 방어선이다. event_id 는
-- (userId, evidenceVersion, cohortSnapshotId, computeVersions) 에서 결정론적으로
-- 만들어지므로, 재시작이나 같은 완료 이벤트 재배달에도 같은 값이 나온다.
CREATE TABLE user_c_snapshot (
    user_id                    BIGINT       NOT NULL REFERENCES "user"("user_id"),
    evidence_version           VARCHAR(64)  NOT NULL CHECK (evidence_version ~ '^[0-9a-f]{64}$'),
    cohort_snapshot_id         VARCHAR(80)  NOT NULL,
    demand_snapshot_id         VARCHAR(80)  NOT NULL,
    recommendation_snapshot_id VARCHAR(80)  NOT NULL,
    event_id                   VARCHAR(80)  NOT NULL,
    target_key                 VARCHAR(200) NOT NULL,
    computed_at                TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (user_id, evidence_version, cohort_snapshot_id),
    UNIQUE (event_id)
);

COMMENT ON TABLE user_c_snapshot IS
    'C 계산 결과의 Snapshot ID. 결과 본문은 C 가 소유하며 여기에 복제하지 않는다.';
COMMENT ON COLUMN user_c_snapshot.event_id IS
    '결정론적 완료 event ID. 재시작·재배달에도 같은 값이라 중복 계산을 막는다.';

-- 조회는 항상 "이 사용자의 이 목표 직무에서 가장 최근 결과"로 들어온다.
-- 사용자가 기술을 더 분석하면 evidence_version 이 바뀌어 행이 하나 더 생기므로,
-- 최신 한 건을 고르는 경로에 인덱스를 맞춘다.
CREATE INDEX idx_user_c_snapshot_latest
    ON user_c_snapshot (user_id, target_key, computed_at DESC);
