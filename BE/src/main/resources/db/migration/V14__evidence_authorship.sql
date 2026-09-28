-- 근거 한 줄을 누가 썼는지 판정하기 위한 자리.
--
-- analysis_evidence_commit 과 repository_commit 은 V1 부터 있었지만 아무도 채우지
-- 않았다. 채우려면 세 가지가 빠져 있다.

-- 1. 근거가 어느 커밋에서 왔는지.
--
-- 워커가 git blame 으로 알아내 결과 이벤트에 싣는다. NULL 은 "본인이 아니다"가
-- 아니라 "작성자를 읽지 못했다"는 뜻이다 -- 얕은 체크아웃이거나, blame 이 안 되는
-- 파일이거나, 기여 판정을 끄고 돌린 분석이다. 조회 쪽이 그 차이를 지켜야 한다.
ALTER TABLE "analysis_evidence" ADD COLUMN "commit_sha" CHAR(40);

COMMENT ON COLUMN "analysis_evidence"."commit_sha" IS
    'git blame 이 지목한 커밋. NULL 은 작성자 미확인이며 기여 없음과 구분한다.';

-- 2. 커밋 캐시의 동일성.
--
-- 커밋 하나를 GitHub 에 묻는 데 API 호출 한 번이 든다. 같은 저장소를 다시 분석하면
-- 대부분의 근거가 같은 커밋을 가리키므로 캐시가 필요하고, 캐시에는 중복이 없어야
-- ON CONFLICT 로 안전하게 쌓을 수 있다. SHA 는 저장소 안에서 유일하다.
ALTER TABLE "repository_commit"
    ADD CONSTRAINT "UQ_REPOSITORY_COMMIT" UNIQUE ("repository_id", "commit_sha");

-- 3. 기여 판정의 멱등성.
--
-- 결과 이벤트는 at-least-once 라 재배달이 정상 경로다. 이 제약이 없으면 같은 결과를
-- 두 번 받을 때 기여가 두 배로 세어진다. 근거 하나에 사용자 하나의 판정은 하나다.
ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "UQ_EVIDENCE_COMMIT_USER" UNIQUE ("analysis_evidence_id", "user_id");

-- contribution_type 의 값 집합. 화면의 ContributionLabel 4종과 같다.
--
-- PARTIAL_EDIT 는 "근거 줄은 남이 썼지만 그 파일을 본인이 건드린 적 있다"는 뜻이라
-- Level 판정에는 쓰지 않는다. 엄격 판정에서 세는 것은 SOLE_AUTHOR 와 CO_AUTHORED
-- 뿐이다 -- 나머지 둘은 그 근거 줄을 본인이 쓰지 않았다는 뜻이기 때문이다.
ALTER TABLE "analysis_evidence_commit"
    ADD CONSTRAINT "CK_CONTRIBUTION_TYPE" CHECK ("contribution_type" IN
        ('SOLE_AUTHOR', 'CO_AUTHORED', 'PARTIAL_EDIT', 'UNVERIFIED'));

-- 조회는 "이 사용자가 쓴 근거"로 들어온다. 그 경로에 인덱스를 맞춘다.
CREATE INDEX "idx_evidence_commit_user_contribution"
    ON "analysis_evidence_commit" ("user_id", "contribution_type");
