-- 분석한 저장소의 이름을 남긴다.
--
-- 지금은 GitHub 숫자 id만 있어서 근거를 화면에 보여줄 수 없다. Evidence 한 줄은
-- "이 파일 이 라인" 링크가 있어야 근거 구실을 하고, 그 링크는
-- https://github.com/{owner}/{repo}/blob/{sha}/{path}#L{n} 이라 이름이 필요하다.
-- FE 의 EvidenceRow 는 permalink 가 없으면 아예 렌더하지 않는다.
--
-- 조회 시점에 GitHub 에 id 로 물어보는 방법도 있지만, 호출 한도를 쓰고 저장소가
-- 삭제되거나 비공개로 바뀌면 과거 근거를 영영 못 읽는다.
--
-- 이름은 바뀔 수 있으므로 "분석 당시의 이름"으로 박아 둔다. 이름이 바뀐 뒤에도
-- 그때 만든 링크는 그 커밋을 가리켜야 한다. repository_id 가 동일성의 기준이고
-- 이 컬럼은 표시와 링크에만 쓴다.
--
-- 기존 행은 NULL 이다. 그때는 이름을 받아 적지 않았으므로 되살릴 수 없다.
-- 채워 넣는 대신, 조회 쪽에서 permalink 를 만들지 못하는 근거로 다룬다.

ALTER TABLE "analysis_job" ADD COLUMN "repository_full_name" VARCHAR(255);

COMMENT ON COLUMN "analysis_job"."repository_full_name" IS
    '분석 당시의 owner/repo. 표시와 permalink 전용이며 동일성 판단은 repository_id 로 한다.';
