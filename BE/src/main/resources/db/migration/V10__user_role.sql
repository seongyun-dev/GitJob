-- S15P21E102-121. 관리자를 실체화한다.
--
-- Role enum 에 ADMIN 이 있었지만 아무도 그것이 될 수 없었다. user 테이블에
-- 컬럼이 없고 로그인이 Role.USER 를 하드코딩했으므로, ADMIN 은 코드에만 있는
-- 값이었다.
--
-- 관리자 화면이 하는 일은 레지스트리를 바꾸는 것이고, 레지스트리는 모든
-- 사용자의 기술 프로필이 판정되는 기준이다. 로그인한 아무나 후보를 승격할 수
-- 있으면 한 사람이 전체 판정을 바꾼다. 그래서 화면보다 이것이 먼저다.
--
-- 승격은 DB 에서 준다. 설정 파일의 허용 목록으로 하면 누가 관리자인지가
-- 배포 산출물에 박히고, 사람이 바뀔 때마다 재배포해야 한다.
--
--   UPDATE "user" SET role = 'ADMIN' WHERE github_login = '...';

ALTER TABLE "user"
    ADD COLUMN "role" VARCHAR(16) NOT NULL DEFAULT 'USER';

ALTER TABLE "user"
    ADD CONSTRAINT "CK_USER_ROLE" CHECK ("role" IN ('USER', 'ADMIN'));

-- 관리자는 소수이므로 부분 인덱스로 충분하다. 전체 인덱스는 거의 모든 행이
-- USER 라 선택도가 없다.
CREATE INDEX "idx_user_admin" ON "user" ("user_id") WHERE "role" = 'ADMIN';
