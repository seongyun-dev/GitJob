-- C 계산은 GitHub 기여 판정 시도 뒤에만 시작한다 (S15P21E102-311).
--
-- analysis_job.status = SUCCEEDED 는 worker 결과와 Evidence가 저장됐다는 뜻이고,
-- 기여 판정까지 끝났다는 뜻은 아니었다. 두 단계 사이에서 복구 스케줄러가 실행되면
-- 개인 판정이 없는 payload가 결정론적 event ID로 먼저 고정될 수 있다.
ALTER TABLE "analysis_job"
    ADD COLUMN "compute_ready_at" TIMESTAMPTZ;

-- 이 marker가 도입되기 전에 끝난 분석은 당시 consumer가 이미 기여 판정 시도를 마친
-- 것으로 취급한다. 계보가 없는 v1 분석은 복구 조회가 별도로 제외한다.
UPDATE "analysis_job"
   SET "compute_ready_at" = COALESCE("completed_at", "requested_at")
 WHERE "status" = 'SUCCEEDED';

COMMENT ON COLUMN "analysis_job"."compute_ready_at" IS
    'GitHub 기여 판정 시도가 종료되어 C Evidence payload를 조립해도 되는 시각. NULL인 성공 분석은 후처리 중이다.';

CREATE INDEX "idx_analysis_job_compute_recovery"
    ON "analysis_job" ("user_id", "repository_id", "completed_at" DESC)
    WHERE "status" = 'SUCCEEDED';
