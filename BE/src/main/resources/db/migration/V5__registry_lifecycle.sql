-- S15P21E102-121. Registry 버전에 수명 주기를 준다.
--
-- V4가 registry_version을 콘텐츠 4개 테이블의 PK에 넣어 "한 버전의 내용은 불변"을
-- 만들었다. 그런데 버전이 여러 개일 때 어느 것이 현재인지 DB가 말해주지 못했다.
-- 그래서 BE는 설정값(gitjob.analysis.request.registry-version)에 버전을 박아
-- 두었고, 그 기본값은 schema_version인 'technology-registry/v1'이었다. 실재하는
-- registry_version과 다른 값이라, 이 값으로 규칙을 조회하면 0행이 나온다.
--
-- 0행은 예외가 아니라 "매칭된 기술 없음"으로 조용히 흘러간다. 기술을 하나도
-- 쓰지 않는 저장소와 구분되지 않는다. 아직 판정 단계가 없어 증상이 없을 뿐이다.
--
-- 현재 버전을 DB가 들고 있으면 설정과 데이터가 어긋날 자리가 없어진다.

ALTER TABLE "technology_registry"
    ADD COLUMN "status" VARCHAR(16),
    ADD COLUMN "published_at" TIMESTAMPTZ;

-- V3이 넣은 유일한 버전이 현재다.
UPDATE "technology_registry"
SET "status" = 'CURRENT',
    "published_at" = now()
WHERE "registry_version" = 'registry-20260908.1';

-- 위에 걸리지 않은 행이 있다면(이 마이그레이션 이전에 손으로 넣은 것) 아래
-- NOT NULL이 통과하도록 물러난 버전으로 본다.
UPDATE "technology_registry"
SET "status" = 'RETIRED',
    "published_at" = now()
WHERE "status" IS NULL;

ALTER TABLE "technology_registry"
    ALTER COLUMN "status" SET NOT NULL;

-- DRAFT   관리자가 후보를 승격해 쌓는 중. 아직 어떤 분석도 이 버전을 쓰지 않는다
-- CURRENT 새 분석 요청이 사용하는 버전. 항상 정확히 하나
-- RETIRED 지난 버전. 그때 판정한 분석을 되짚기 위해 남긴다
ALTER TABLE "technology_registry"
    ADD CONSTRAINT "CK_TECHNOLOGY_REGISTRY_STATUS"
        CHECK ("status" IN ('DRAFT', 'CURRENT', 'RETIRED'));

-- 발행 시각은 발행된 버전에만 있다. DRAFT에 값이 있으면 발행된 것처럼 보이고,
-- CURRENT에 없으면 언제부터 쓰였는지 알 수 없다.
ALTER TABLE "technology_registry"
    ADD CONSTRAINT "CK_TECHNOLOGY_REGISTRY_PUBLISHED_AT"
        CHECK (("status" = 'DRAFT') = ("published_at" IS NULL));

-- 현재 버전은 하나뿐이어야 한다. 둘이면 요청마다 다른 규칙으로 판정되고, 그
-- 차이는 결과를 비교하기 전까지 드러나지 않는다. 부분 유니크 인덱스로 막으면
-- 발행 절차가 실수해도 DB가 거절한다.
CREATE UNIQUE INDEX "uq_technology_registry_current"
    ON "technology_registry" ("status")
    WHERE "status" = 'CURRENT';
