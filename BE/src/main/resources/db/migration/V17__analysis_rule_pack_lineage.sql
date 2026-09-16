-- 분석 결과의 Rule Pack 계보와 지원 범위 (S15P21E102-279 후속).
--
-- 워커는 registry-20260911.4 결과를 `repository-analysis-result/v3`로 발행하며 그
-- payload 에는 v1 에 없던 네 가지가 실린다 -- Rule Pack 버전과 내용 해시, 기술별 지원
-- 범위, 건너뛴 사유. 지금까지 BE 는 v1 만 받아 이 값들을 통째로 버렸다.
--
-- 버리면 안 되는 이유는 C 계약이 이 값들을 요구하기 때문이다. C 는 근거를 평가할 때
-- `evidence_rule_version` 으로 Rule Pack 계보를 확인하고, 판정 상한을
-- `max_supported_level` 로 제한한다. 그 자리에 Registry 버전을 대신 넣으면 C 가 모든
-- 근거를 범위 불일치로 버리고, 화면은 "근거는 있는데 아무것도 보유가 아닌" 상태가 된다.

-- 1. 분석 한 건의 판정 기준.
--
-- registry_version 이 analysis_evidence 에만 있었다. 근거가 0건인 분석은 그 행조차
-- 없어서 "어느 기준으로 판정했는지"를 잃었고, 그래서 등록 기술이 관측되지 않은
-- 사용자는 C 계산 대상에서 통째로 빠졌다. 분석 단위로 올린다.
ALTER TABLE "analysis_job"
    ADD COLUMN "registry_version"         VARCHAR(80),
    ADD COLUMN "rule_pack_version"        VARCHAR(80),
    ADD COLUMN "rule_pack_content_sha256" CHAR(64),
    ADD COLUMN "result_schema_version"    VARCHAR(40),
    -- 건너뛴 사유와 건수. {"BINARY": 12, "TOO_LARGE": 3} 형태다.
    --
    -- NULL 을 허용하는 것이 요점이다. v1 결과에는 이 필드가 없고 그것은 "건너뛴 것이
    -- 없다"가 아니라 "모른다"이다. 기본값 {} 로 채우면 두 상태가 같아지고, 저장소
    -- 전체를 본 적 없는 분석이 완전 판정(coverage_complete)으로 C 에 나간다.
    ADD COLUMN "skipped_reasons"          JSONB;

COMMENT ON COLUMN "analysis_job"."rule_pack_version" IS
    '워커가 판정에 쓴 Rule Pack. C 의 evidence_rule_version 이 이 값이며 Registry 버전으로 대체하지 않는다.';
COMMENT ON COLUMN "analysis_job"."skipped_reasons" IS
    '사유별 건너뛴 파일 수. NULL 은 보고받지 못한 것(v1)이며 0건과 구분한다.';
COMMENT ON COLUMN "analysis_job"."result_schema_version" IS
    '결과를 받은 계약 버전. v1 결과에는 Rule Pack 계보가 없다는 사실을 남긴다.';

-- v1 결과에는 Rule Pack 계보가 없다. 기존 행을 채우지 않는 이유는 그 분석이 실제로
-- 어느 Rule Pack 으로 판정됐는지 알 수 없기 때문이다. NULL 은 "모른다"이고, 조회 쪽이
-- 그것을 "계보 없음"으로 읽어 C 에 보내지 않는다.

-- 2. 기술별 지원 범위.
--
-- 같은 Rule Pack 이라도 기술마다 어디까지 판정할 수 있는지가 다르다. Spring 은 L3 까지
-- 보지만 어떤 기술은 의존성 선언까지만(L1) 본다. 그 상한을 모르면 "관측된 최고 Level"
-- 을 상한으로 쓰게 되는데, 그러면 규칙이 아예 볼 수 없는 구간까지 "판정했는데 없었다"로
-- 단정하게 된다.
--
-- 분석 단위로 저장한다. Rule Pack 이 바뀌면 같은 기술의 상한도 바뀌므로, 과거 분석의
-- 판정을 나중 Rule Pack 의 상한으로 다시 읽으면 안 된다.
CREATE TABLE "analysis_technology_support" (
    "analysis_id"          VARCHAR(80)  NOT NULL REFERENCES "analysis_job"("analysis_id"),
    "tech_id"              VARCHAR(80)  NOT NULL,
    "evaluation_scope"     VARCHAR(16)  NOT NULL CHECK ("evaluation_scope" = 'REPOSITORY'),
    "max_supported_level"  VARCHAR(2)   NOT NULL CHECK ("max_supported_level" IN ('L0','L1','L2','L3')),
    "coverage"             VARCHAR(16)  NOT NULL CHECK ("coverage" IN ('SUPPORTED','PARTIAL','UNSUPPORTED')),
    "required_fact_types"  TEXT[]       NOT NULL,
    "limitations"          JSONB        NOT NULL DEFAULT '[]'::JSONB,
    PRIMARY KEY ("analysis_id", "tech_id")
);

COMMENT ON TABLE "analysis_technology_support" IS
    '그 분석의 Rule Pack 이 기술마다 어디까지 판정할 수 있었는지. C 의 assessment_ceiling 근거다.';

-- 조회는 언제나 "이 분석이 평가할 수 있었던 기술"로 들어온다. C 에 보낼
-- evaluated_tech_ids 가 이 질의다.
CREATE INDEX "idx_analysis_technology_support_analysis"
    ON "analysis_technology_support" ("analysis_id", "coverage");
