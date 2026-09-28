-- GitHub Access Token을 평문이 아니라 암호문으로 보관한다.
--
-- 이 토큰의 scope는 read:user,repo다. DB를 읽을 수 있는 사람은 그 사용자의
-- 비공개 저장소를 전부 읽을 수 있었다. V1의 TODO가 가리키던 작업이다.
--
-- 이 마이그레이션은 암호화 키를 다루는 애플리케이션 백필을 수행하지 않는다.
-- 대신 기존 토큰이 한 건이라도 있으면 컬럼을 삭제하기 전에 실패한다. 운영자가
-- 토큰을 잃는 줄 모르고 배포하는 것보다, 애플리케이션에서 암호화 이관하거나
-- 재로그인 정책을 명시적으로 선택한 뒤 다시 적용하는 편이 안전하다.
--
-- 컬럼 이름을 바꾸는 것도 의도한 것이다. 남아 있는 코드가 옛 컬럼을 참조하면
-- 조용히 NULL을 읽는 대신 기동 시 검증(ddl-auto=validate)에서 걸린다.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM "user" WHERE "access_token" IS NOT NULL) THEN
        RAISE EXCEPTION
            'V12 cannot drop user.access_token while GitHub tokens remain; encrypt or clear them first';
    END IF;
END
$$;

ALTER TABLE "user" ADD COLUMN "access_token_enc" BYTEA;
ALTER TABLE "user" DROP COLUMN "access_token";

COMMENT ON COLUMN "user"."access_token_enc" IS
    'AES-GCM(난수 IV 16B + 암호문 + 인증태그 16B). 매번 다른 바이트가 되므로 조회 조건으로 쓸 수 없다.';
