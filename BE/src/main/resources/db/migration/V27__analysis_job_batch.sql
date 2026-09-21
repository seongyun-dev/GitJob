-- 한 번의 배치 요청으로 함께 접수된 분석을 한 묶음으로 본다 (S15P21E102-136).
--
-- 별도 테이블을 두지 않는다. 배치의 상태는 구성원 Job에서 파생되는 값이고, 테이블로
-- 두면 마지막 Job이 끝날 때 누군가 ACTIVE -> DONE 을 써야 한다. 그 전이를 놓친 배치는
-- 사용자를 영구히 막는데, 그것이 바로 이 기능이 유효시간을 두는 이유인 "QUEUED 에
-- 영원히 남은 분석"과 같은 종류의 고장이다.
ALTER TABLE "analysis_job"
    ADD COLUMN "batch_id" VARCHAR(80);

COMMENT ON COLUMN "analysis_job"."batch_id" IS
    '한 번의 배치 요청으로 함께 접수된 분석의 묶음 ID. 이 컬럼이 생기기 전 단건 요청은 NULL이며 배치 조회가 제외한다.';

-- 기존 행을 backfill 하지 않는다.
--
-- 가짜 묶음 ID를 넣으면 배포 직후 첫 화면에서 몇 달 전 단건 분석이 "지금 진행 중인
-- 배치 1/1"로 되살아난다. NULL 은 V13 이 repository_full_name 에 쓴 것과 같은 구/신
-- 경계 표시다. 옛 진행 중 행이 제출을 막는 것은 그대로다 -- 차단 질의는 batch_id 를
-- 보지 않는다.

-- 제출 차단 검사: (user_id, status IN (...), requested_at > now() - window).
--
-- 부분 인덱스로 만들지 않는다. 질의가 상태 목록을 파라미터로 바인딩하므로 플래너가
-- 그 IN 목록이 인덱스 술어를 함의한다는 것을 증명하지 못한다 -- V1 의
-- idx_analysis_job_user_repository 가 존재하는 이유와 같다. 겸사겸사 상태 목록의 두
-- 번째 사본이 생기지 않아 IN_PROGRESS_STATUSES 와 어긋날 여지도 없다.
CREATE INDEX "idx_analysis_job_user_status_requested"
    ON "analysis_job" ("user_id", "status", "requested_at" DESC);

-- 멈춘 분석 정리(StaleAnalysisReaper). 사용자를 가리지 않고 오래된 진행 중 행을 훑는다.
CREATE INDEX "idx_analysis_job_status_requested"
    ON "analysis_job" ("status", "requested_at");

-- 사용자의 가장 최근 배치 찾기.
CREATE INDEX "idx_analysis_job_user_batch_recent"
    ON "analysis_job" ("user_id", "requested_at" DESC)
    WHERE "batch_id" IS NOT NULL;

-- 그 배치의 구성원 모으기.
CREATE INDEX "idx_analysis_job_batch"
    ON "analysis_job" ("batch_id")
    WHERE "batch_id" IS NOT NULL;
