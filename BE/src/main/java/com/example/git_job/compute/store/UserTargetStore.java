package com.example.git_job.compute.store;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * 사용자의 목표 직무와 공고 필터 (S15P21E102-279).
 *
 * <p>화면 파라미터가 아니라 서버에 두는 이유는 분석 완료 처리가 브라우저 없이 돌기
 * 때문이다. 저장소 분석이 끝난 순간 어떤 직무로 계산할지 서버가 알고 있어야 한다.</p>
 *
 * <p>지역·경력을 표가 아니라 쉼표 문자열로 두는 것은 이 값이 검색 대상이 아니라 C에
 * 그대로 넘기는 선택자이기 때문이다. 조인할 일이 없고, 순서와 공백을 정규화해 두면
 * 같은 조건이 같은 {@link Target#targetKey()}를 만든다.</p>
 */
@Repository
public class UserTargetStore {

    private final JdbcTemplate jdbc;

    public UserTargetStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Target> find(long userId) {
        return jdbc.query("""
                SELECT target_role, regions, career_levels, updated_at
                FROM user_target WHERE user_id = ?
                """, (rs, row) -> new Target(
                        rs.getString("target_role"),
                        split(rs.getString("regions")),
                        split(rs.getString("career_levels")),
                        rs.getTimestamp("updated_at").toInstant()),
                userId).stream().findFirst();
    }

    /** 전량 교체. 필터를 지우는 것도 선택이므로 부분 갱신을 두지 않는다. */
    public Target save(long userId, String targetRole, List<String> regions,
                       List<String> careerLevels, Instant now) {
        Target target = new Target(targetRole.strip(), normalize(regions),
                normalize(careerLevels), now);
        jdbc.update("""
                INSERT INTO user_target (user_id, target_role, regions, career_levels, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    target_role = EXCLUDED.target_role,
                    regions = EXCLUDED.regions,
                    career_levels = EXCLUDED.career_levels,
                    updated_at = EXCLUDED.updated_at
                """, userId, target.targetRole(), join(target.regions()),
                join(target.careerLevels()), java.sql.Timestamp.from(now));
        return target;
    }

    /**
     * 빈 값과 공백을 걸러 정렬한다.
     *
     * <p>정규화가 없으면 {@code ["서울"]}과 {@code [" 서울 "]}이 다른 캐시 키를 만들고,
     * 화면은 같은 조건인데 결과가 두 벌 생긴다.</p>
     */
    private static List<String> normalize(List<String> values) {
        if (values == null) {
            return List.of();
        }
        return values.stream()
                .filter(value -> value != null && !value.isBlank())
                .map(String::strip)
                .distinct()
                .sorted()
                .toList();
    }

    private static List<String> split(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        return Arrays.stream(value.split(",")).filter(part -> !part.isBlank()).toList();
    }

    private static String join(List<String> values) {
        return String.join(",", values);
    }

    /**
     * @param targetKey FE의 캐시 키이자 결과 pointer의 구분자. FE가 사용자 ID나 Snapshot
     *                  ID를 들고 다니지 않게 하려고 서버가 만들어 내려준다.
     */
    public record Target(String targetRole, List<String> regions, List<String> careerLevels,
            Instant updatedAt) {

        public String targetKey() {
            return targetRole + "|" + String.join(",", regions) + "|" + String.join(",", careerLevels);
        }
    }
}
