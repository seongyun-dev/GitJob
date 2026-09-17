-- PyPI 후보의 scope는 짧은 enum이 아니라 저장소 상대 requirements 파일 경로다.
-- 40자는 정상적인 모노레포 경로도 거절하므로 Evidence file_path와 같은 상한을 쓴다.
ALTER TABLE "technology_candidate"
    ALTER COLUMN "scope" TYPE VARCHAR(1024);

ALTER TABLE "technology_candidate_observation"
    ALTER COLUMN "scope" TYPE VARCHAR(1024);

COMMENT ON COLUMN "technology_candidate"."scope" IS
    'Manifest scope label or repository-relative requirements path; up to 1024 characters.';
COMMENT ON COLUMN "technology_candidate_observation"."scope" IS
    'Scope observed in the analysis event; may be a repository-relative requirements path.';
