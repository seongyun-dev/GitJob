-- 관리자 전용 ID/PW 로그인 자격 증명 자리.
--
-- 관리자 화면 진입은 GitHub OAuth 없이도 되어야 한다(운영·시연). 그 자격 증명을
-- 환경변수로 두면 환경마다 값을 맞추고 컨테이너를 재생성해야 하는데, 관리자 승격
-- (role) 자체가 이미 DB 에서만 바뀌므로 자격 증명도 같은 자리에 두는 편이 일관된다.
-- 값을 바꿀 때 재배포가 필요 없다는 것도 이유다.
--
-- 별도 계정 테이블을 만들지 않는다. 이 로그인이 발급하는 세션의 주체는 결국
-- role=ADMIN 인 사용자이므로, 자격 증명은 그 사용자 행에 붙는 것이 자연스럽다.

-- 로그인 시 입력하는 식별자. 사람이 정하는 값이라 githubLogin 과 별개다.
-- 자격 증명을 쓰지 않는 사용자는 NULL 이며, 그 NULL 들은 UNIQUE 에 걸리지 않는다.
ALTER TABLE "user" ADD COLUMN "admin_login_id" VARCHAR(100);

ALTER TABLE "user"
    ADD CONSTRAINT "UQ_USER_ADMIN_LOGIN_ID" UNIQUE ("admin_login_id");

COMMENT ON COLUMN "user"."admin_login_id" IS
    '관리자 ID/PW 로그인의 식별자. NULL 이면 그 사용자는 이 방식으로 로그인하지 않는다.';

-- 비밀번호는 절대 평문으로 두지 않는다. BCrypt 해시만 저장하며(60자), 검증은
-- PasswordEncoder.matches 가 한다. 덤프·백업·로그에 원문이 남지 않게 하기 위해서다.
ALTER TABLE "user" ADD COLUMN "admin_password_hash" VARCHAR(100);

COMMENT ON COLUMN "user"."admin_password_hash" IS
    'BCrypt 해시. 평문 저장 금지. NULL 이면 ID/PW 로그인 비활성.';

-- 자격 증명 값 자체는 이 파일에 넣지 않는다. 마이그레이션은 저장소에 올라가므로,
-- 실제 ID/해시는 환경별로 한 번 UPDATE 로 넣는다(관리자 role 을 부여하던 방식과 같다).
