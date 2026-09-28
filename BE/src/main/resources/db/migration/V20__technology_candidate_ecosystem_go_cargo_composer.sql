-- 기술 후보 생태계에 GO·CARGO·COMPOSER 를 연다.
--
-- 이 세 값은 `repository-analysis-result/v2` 계약에 이미 있었다(TechnologyCandidateV2).
-- BE 만 네 개로 굳어 있었고, 그 불일치는 후보 하나를 버리는 정도로 끝나지 않는다.
--
--   1. 이벤트 역직렬화: ecosystem 은 enum 이라 모르는 값이 오면 결과 이벤트가 통째로
--      거절된다. Go·Rust·PHP 저장소를 분석한 사용자는 후보뿐 아니라 판정과 근거까지
--      전부 잃고 분석이 QUEUED 에 남는다. `syntax_node_count` 가 일으킨 것과 같은
--      고장이며, 미등록 의존성이 하나라도 나오면 바로 재현된다.
--   2. 여기: enum 만 늘리면 역직렬화는 통과하고 INSERT 가 CHECK 제약에 걸린다.
--      실패 지점이 옮겨갈 뿐 사용자가 보는 결과는 같다.
--
-- 그래서 둘을 같은 배포에 둔다.

-- 값 목록만 바뀐다. 기존 네 값은 그대로라 기존 행은 전부 통과하고, 재검증도
-- technology_candidate 한 테이블에서 끝난다.
ALTER TABLE "technology_candidate"
    DROP CONSTRAINT "CK_TECHNOLOGY_CANDIDATE_ECOSYSTEM";

ALTER TABLE "technology_candidate"
    ADD CONSTRAINT "CK_TECHNOLOGY_CANDIDATE_ECOSYSTEM"
        CHECK ("ecosystem" IN ('MAVEN', 'NPM', 'PYPI', 'NUGET', 'GO', 'CARGO', 'COMPOSER'));

COMMENT ON COLUMN "technology_candidate"."ecosystem" IS
    'DEPENDENCY fact의 생태계. 결과 계약(TechnologyCandidate.Ecosystem)과 같은 목록이어야 한다 -- 한쪽만 늘리면 결과 이벤트가 통째로 거절되거나 INSERT가 깨진다.';
