package com.example.git_job.analysis.summary;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import java.time.Duration;

/**
 * 나가는 JSON 의 모양을 고정한다.
 *
 * <p>받는 쪽은 <b>모르는 필드를 422 로 거절한다</b>({@code extra="forbid"}). 필드
 * 이름을 하나 잘못 쓰면 요약이 통째로 안 되는데, 그 실패는 "요약이 아직 없음"과
 * 화면에서 구별되지 않는다. 그래서 이름과 형태를 여기서 직접 본다.</p>
 *
 * <p>이 테스트는 요약 서비스를 부르지 않는다. 계약은 이름과 형태의 문제이고,
 * 그것은 노트북이 꺼져 있어도 확인할 수 있어야 한다.</p>
 */
class FactPackWireFormatTest {

    /**
     * 클라이언트가 실제로 보내는 바이트를 만든다.
     *
     * <p>주소를 비워 두면 호출은 하지 않지만 직렬화는 그대로다. 여기서 따로 만든
     * mapper 로 검사하면 Spring 이 설정한 것과 다를 수 있어, 통과해도 실제 요청이
     * 422 를 받을 수 있다.</p>
     */
    private final TechnologySummaryClient client =
            new TechnologySummaryClient("", Duration.ofSeconds(1));

    private String wire(FactPack pack) {
        return client.requestBody(7L, pack);
    }

    private static FactPack sample() {
        return new FactPack(
                FactPack.SCHEMA_VERSION,
                FactPack.LOCALE,
                new FactPack.Technology("spring-security", "Spring Security", "L2", "L2",
                        "registry-20260910.2"),
                "MOSTLY_MINE",
                List.of(new FactPack.LevelEvidence("L2", List.of("인증 필터 체인 구성"), true)),
                new FactPack.NextLevel("L3", "메서드 보안 활성화",
                        List.of("@EnableMethodSecurity")),
                List.of(new FactPack.Highlight(0, "API_CALL", "SecurityFilterChain",
                        "config/SecurityConfig.java", true)),
                List.of(new FactPack.RepositoryRef("octocat/app", true)),
                new FactPack.Period(java.time.LocalDate.parse("2025-08-11"),
                        java.time.LocalDate.parse("2025-08-19"), 1));
    }

    @Test
    @DisplayName("user_id 는 fact_pack 밖에 있다")
    void userIdSitsOutsideTheFactPack() {
        // 캐시 키는 사람을 갈라야 하지만 프롬프트는 그럴 이유가 없다. 안에 넣으면
        // 사람을 지목하는 값이 모델에 들어간다.
        String json = wire(sample());

        assertTrue(json.startsWith("{\"user_id\":\"7\",\"fact_pack\":{"), json);
    }

    @Test
    @DisplayName("필드 이름이 전부 snake_case 계약 그대로다")
    void fieldNamesMatchTheContract() {
        String json = wire(sample());

        for (String required : List.of(
                "\"schema_version\":\"technology-summary-request/v1\"",
                "\"locale\":\"ko-KR\"",
                "\"tech_id\":", "\"display_name\":",
                "\"repository_level\":", "\"personal_level\":", "\"registry_version\":",
                "\"authorship\":", "\"levels\":", "\"next_level\":",
                "\"highlights\":", "\"repositories\":", "\"period\":",
                "\"fact_type\":", "\"full_name\":")) {
            assertTrue(json.contains(required), required + " 가 없다: " + json);
        }
        // camelCase 가 새어 나가면 받는 쪽이 422 로 거절한다.
        for (String forbidden : List.of("schemaVersion", "techId", "displayName",
                "repositoryLevel", "personalLevel", "registryVersion", "nextLevel",
                "factType", "fullName")) {
            assertTrue(!json.contains(forbidden), forbidden + " 가 새어 나갔다: " + json);
        }
    }

    @Test
    @DisplayName("날짜는 배열이 아니라 ISO 문자열이다")
    void datesAreIsoStrings() {
        // 기본 설정이면 LocalDate 가 [2025,8,11] 로 나가고, 계약의 date 타입과
        // 맞지 않아 422 가 된다.
        String json = wire(sample());

        assertTrue(json.contains("\"first\":\"2025-08-11\""), json);
        assertTrue(json.contains("\"last\":\"2025-08-19\""), json);
    }

    @Test
    @DisplayName("비어 있는 자리는 null 로 나가고 사라지지 않는다")
    void absentFieldsTravelAsNull() {
        // next_level 과 period 는 없을 수 있다. 키 자체를 빼면 받는 쪽 기본값이
        // 적용되는데, 우리가 "없다"고 말한 것과 우연히 같다는 보장이 없다.
        FactPack pack = new FactPack(FactPack.SCHEMA_VERSION, FactPack.LOCALE,
                new FactPack.Technology("lombok", "Lombok", "L1", "L0",
                        "registry-20260910.2"),
                "NOT_VERIFIED", List.of(), null, List.of(), List.of(), null);

        String json = wire(pack);

        assertTrue(json.contains("\"next_level\":null"), json);
        assertTrue(json.contains("\"period\":null"), json);
    }

    @Test
    @DisplayName("highlights 의 index 는 배열 순서와 같다")
    void highlightIndexesAreDense() {
        // 받는 쪽이 0..n-1 인지 검사한다. 어긋나면 422 다.
        HighlightSelector selector = new HighlightSelector();
        List<FactPack.Highlight> highlights = selector.select(List.of(
                new com.example.git_job.analysis.query.TechnologySummaryFactStore.EvidenceFact(
                        "API_CALL", "{\"CALL\":\"a\"}", "x/A.java", 1, true),
                new com.example.git_job.analysis.query.TechnologySummaryFactStore.EvidenceFact(
                        "IMPORT", "{\"MODULE\":\"b\"}", "x/B.java", 2, false)));

        for (int i = 0; i < highlights.size(); i++) {
            assertEquals(i, highlights.get(i).index());
        }
    }
}
