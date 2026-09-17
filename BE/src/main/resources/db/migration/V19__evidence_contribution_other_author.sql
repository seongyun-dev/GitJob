-- 기여 라벨에 OTHER_AUTHOR 를 연다.
--
-- 지금까지 기여 판정은 두 가지를 같은 값으로 저장했다.
--
--   1. GitHub 이 커밋을 계정에 붙이지 못했다 -- 등록하지 않은 이메일로 커밋하면
--      본인 코드여도 여기로 온다. "모른다"이다.
--   2. 물어봤더니 다른 사람이 썼다. "본인이 아니다"이다.
--
-- Level 판정만 보면 둘 다 제외되니 결과가 같아서 합쳐 두어도 티가 나지 않았다.
-- 그 뒤 둘을 실제로 구분해야 하는 곳이 생겼다 -- 기술 요약 계약의 authorship 은
-- MOSTLY_OTHERS("본인 근거가 소수다")와 NOT_VERIFIED("판정 자체가 없다")를 다른
-- 값으로 요구한다(docs/ai/technology-summary-api.md 2장). 저장할 때 합쳐 두면
-- 나중에 되살릴 방법이 없다.
--
-- PARTIAL_EDIT 를 재사용하지 않는 이유는 뜻이 더 좁기 때문이다. V14 가 그것을
-- "근거 줄은 남이 썼지만 그 파일을 본인이 건드린 적 있다"로 정의했는데, 우리는
-- 파일을 건드린 적이 있는지 확인하지 않는다. 확인하지 않은 것을 주장할 수는 없다.

ALTER TABLE "analysis_evidence_commit"
    DROP CONSTRAINT "CK_CONTRIBUTION_TYPE";

ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "CK_CONTRIBUTION_TYPE" CHECK ("contribution_type" IN
        ('SOLE_AUTHOR', 'CO_AUTHORED', 'PARTIAL_EDIT', 'OTHER_AUTHOR', 'UNVERIFIED'));

-- 기존 행은 바꾸지 않는다. 지금 저장된 UNVERIFIED 안에 두 뜻이 섞여 있지만, 어느
-- 쪽이었는지는 커밋을 다시 물어봐야 알 수 있고 그것은 마이그레이션이 할 일이 아니다.
-- 재분석하면 새 값으로 다시 쓰인다.
--
-- 엄격 판정이 세는 값은 그대로 SOLE_AUTHOR 와 CO_AUTHORED 둘뿐이다. OTHER_AUTHOR 는
-- 그 근거 줄을 본인이 쓰지 않았다는 뜻이므로 Level 에 기여하지 않는다.
COMMENT ON COLUMN "analysis_evidence_commit"."contribution_type" IS
    'SOLE_AUTHOR·CO_AUTHORED만 본인 기여다. OTHER_AUTHOR는 물어봐서 남이 쓴 것, UNVERIFIED는 물어보지 못한 것이다.';
