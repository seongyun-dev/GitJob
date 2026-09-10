package com.example.git_job.analysis.service;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 분석 요청에 박아 넣을 Registry 버전을 DB에서 읽는다.
 *
 * <p>예전에는 설정값이었고, 기본값이 {@code technology-registry/v1}이었다. 그것은
 * schema_version이지 registry_version이 아니다. 실재하지 않는 버전으로 규칙을
 * 조회하면 0행이 나오고, 0행은 "매칭된 기술 없음"과 구분되지 않는다. 아직 판정
 * 단계가 없어 증상이 없었을 뿐, 붙이는 순간 조용히 틀린 결과를 낸다.</p>
 *
 * <p>버전을 발행하는 곳과 사용하는 곳이 같은 테이블을 보면 어긋날 자리가 없다.
 * {@code CURRENT}는 부분 유니크 인덱스가 하나로 강제한다(V5).</p>
 *
 * <p>캐시하지 않는다. 분석 요청은 사람이 누르는 빈도이고, 조회는 한 행짜리
 * 인덱스 조회다. 캐시를 두면 새 버전을 발행해도 TTL이 지나야 반영되거나 재기동이
 * 필요해지는데, 그 대가를 낼 만큼 잦은 경로가 아니다.</p>
 */
@Component
public class CurrentRegistryVersion {

    private final JdbcTemplate jdbc;

    public CurrentRegistryVersion(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * @throws IllegalStateException CURRENT 버전이 없을 때. 마이그레이션이 하나를
     *         보장하므로, 없다는 것은 누군가 손으로 상태를 바꿨다는 뜻이다. 임의의
     *         버전을 골라 분석을 진행하면 잘못된 기준으로 판정한 결과가 남는다.
     */
    public String resolve() {
        List<String> found = jdbc.queryForList(
                "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                String.class);
        if (found.isEmpty()) {
            throw new IllegalStateException(
                    "technology_registry에 CURRENT 버전이 없다. 분석 요청은 판정 기준 없이 만들 수 없다");
        }
        return found.getFirst();
    }
}
