package com.example.git_job.analysis.summary;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.query.TechnologySummaryFactStore.EvidenceFact;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 선별 규칙을 고정한다.
 *
 * <p>여기가 틀리면 요약이 아니라 <b>캐시</b>가 먼저 깨진다. 요약 서비스의 캐시
 * 키는 정규화된 Fact Pack 전체의 해시라, 같은 입력에 순서가 흔들리면 키가 매번
 * 달라져 같은 요약을 계속 다시 만든다. 그래서 "결과가 그럴듯한가"가 아니라
 * "결정적인가"를 본다.</p>
 */
class HighlightSelectorTest {

    private final HighlightSelector selector = new HighlightSelector();

    private static EvidenceFact fact(String type, String payload, String path, int line,
            Boolean mine) {
        return new EvidenceFact(type, payload, path, line, mine);
    }

    private static EvidenceFact call(String name, String path, int line, Boolean mine) {
        return fact("API_CALL", "{\"CALL\":\"" + name + "\"}", path, line, mine);
    }

    @Test
    @DisplayName("같은 값은 몇 번 나와도 하나다")
    void deduplicatesByValue() {
        // SecurityFilterChain 이 한 저장소에서 12번 나온다. 그대로 실으면 8칸이
        // 한 이름으로 가득 차고, 나머지 사실은 모델에 닿지도 않는다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                call("SecurityFilterChain", "config/SecurityConfig.java", 10, true),
                call("SecurityFilterChain", "config/SecurityConfig.java", 20, true),
                call("SecurityFilterChain", "config/WebConfig.java", 5, true),
                call("authorizeHttpRequests", "config/SecurityConfig.java", 12, true)));

        assertEquals(List.of("SecurityFilterChain", "authorizeHttpRequests"),
                highlights.stream().map(FactPack.Highlight::value).toList());
    }

    @Test
    @DisplayName("본인 근거가 먼저, 미확인은 남의 것보다 뒤")
    void ordersMineFirstAndUnknownLast() {
        // mine 이 null 인 것은 "본인이 안 썼다"가 아니라 "확인되지 않았다"이다.
        // false 보다 앞에 두면 미확인 근거가 본인 근거를 8칸 밖으로 밀어낸다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                call("unknownAuthor", "a/A.java", 1, null),
                call("teammate", "a/A.java", 2, false),
                call("mine", "a/A.java", 3, true)));

        assertEquals(List.of("mine", "teammate", "unknownAuthor"),
                highlights.stream().map(FactPack.Highlight::value).toList());
    }

    @Test
    @DisplayName("높은 종류가 먼저 컨텍스트를 차지한다")
    void ranksByFactType() {
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("DEPENDENCY", "{\"COORDINATE\":\"org.projectlombok:lombok\"}",
                        "build.gradle", 1, true),
                fact("IMPORT", "{\"MODULE\":\"org.springframework.security.web\"}",
                        "a/A.java", 1, true),
                fact("ANNOTATION", "{\"NAME\":\"@EnableMethodSecurity\"}", "a/A.java", 1, true),
                call("SecurityFilterChain", "a/A.java", 1, true)));

        assertEquals(
                List.of("API_CALL", "ANNOTATION", "IMPORT", "DEPENDENCY"),
                highlights.stream().map(FactPack.Highlight::factType).toList());
    }

    @Test
    @DisplayName("여덟 개에서 자르고 번호를 0부터 다시 매긴다")
    void capsAtEightAndRenumbers() {
        // index 는 모델이 세게 하지 않는다. 직접 넣어 줘야 응답의
        // used_highlights 를 범위로 검사할 수 있다.
        List<EvidenceFact> many = new java.util.ArrayList<>();
        for (int i = 0; i < 12; i++) {
            many.add(call("call" + i, "a/A.java", i, true));
        }

        List<FactPack.Highlight> highlights = selector.select(many);

        assertEquals(8, highlights.size());
        assertEquals(List.of(0, 1, 2, 3, 4, 5, 6, 7),
                highlights.stream().map(FactPack.Highlight::index).toList());
    }

    @Test
    @DisplayName("API_CALL 은 METHOD 가 아니라 CALL 을 쓴다")
    void prefersCallOverMethod() {
        // METHOD 는 마지막 조각이라 "run 을 호출했다" 같은 문장이 나온다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("API_CALL", "{\"CALL\":\"SpringApplication.run\",\"METHOD\":\"run\"}",
                        "a/A.java", 1, true)));

        assertEquals("SpringApplication.run", highlights.getFirst().value());
    }

    @Test
    @DisplayName("CALL 이 없으면 METHOD 로 떨어진다")
    void fallsBackToMethod() {
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("API_CALL", "{\"METHOD\":\"opsForValue\"}", "a/A.java", 1, true)));

        assertEquals("opsForValue", highlights.getFirst().value());
    }

    @Test
    @DisplayName("CONFIG_KEY 의 VALUE 는 절대 나가지 않는다")
    void neverReadsConfigValue() {
        // 설정 값은 파일에 적힌 그대로다. 접속 문자열과 비밀번호가 여기 있다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("CONFIG_KEY",
                        "{\"KEY\":\"spring.datasource.password\","
                                + "\"VALUE\":\"hunter2-secret\"}",
                        "src/application.yaml", 3, true)));

        assertEquals("spring.datasource.password", highlights.getFirst().value());
        assertFalse(highlights.toString().contains("hunter2"),
                "설정 값이 Fact Pack 에 실렸다 -- VALUE 를 읽는 경로가 생겼는지 확인할 것");
    }

    @Test
    @DisplayName("이름을 못 찾은 근거는 버린다")
    void dropsFactsWithoutAName() {
        // 빈 이름은 요약에서 아무것도 설명하지 못한다. 자리만 차지하느니 비운다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("IMPORT", "{}", "a/A.java", 1, true),
                fact("IMPORT", "{\"MODULE\":\"  \"}", "a/A.java", 2, true),
                fact("IMPORT", "{\"MODULE\":\"io.jsonwebtoken\"}", "a/A.java", 3, true)));

        assertEquals(1, highlights.size());
        assertEquals("io.jsonwebtoken", highlights.getFirst().value());
    }

    @Test
    @DisplayName("모르는 fact_type 은 맨 뒤로 가되 요약을 막지 않는다")
    void unknownFactTypeIsDroppedNotFatal() {
        // 레지스트리가 새 종류를 내기 시작해도 아는 것부터 채운다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("FUTURE_KIND", "{\"NAME\":\"whatever\"}", "a/A.java", 1, true),
                call("SecurityFilterChain", "a/A.java", 2, true)));

        assertEquals(List.of("SecurityFilterChain"),
                highlights.stream().map(FactPack.Highlight::value).toList());
    }

    @Test
    @DisplayName("깨진 payload 하나가 나머지를 버리지 않는다")
    void malformedPayloadIsSkipped() {
        List<FactPack.Highlight> highlights = selector.select(List.of(
                fact("IMPORT", "{not json", "a/A.java", 1, true),
                fact("IMPORT", "{\"MODULE\":\"io.jsonwebtoken\"}", "a/A.java", 2, true)));

        assertEquals(1, highlights.size());
    }

    @Test
    @DisplayName("같은 입력이면 순서가 언제나 같다")
    void isDeterministic() {
        // 캐시 키가 Fact Pack 전체의 해시다. 순서가 흔들리면 캐시가 영영 안 맞는다.
        List<EvidenceFact> facts = List.of(
                call("b", "z/Z.java", 1, true),
                call("a", "a/A.java", 9, true),
                call("c", "a/A.java", 1, true));

        List<String> first = selector.select(facts).stream()
                .map(FactPack.Highlight::value).toList();
        List<String> again = selector.select(facts.reversed()).stream()
                .map(FactPack.Highlight::value).toList();

        assertEquals(first, again, "입력 순서가 결과를 바꾸면 캐시가 매번 빗나간다");
        assertEquals(List.of("c", "a", "b"), first);
    }

    @Test
    @DisplayName("경로는 마지막 두 조각만 싣는다")
    void shortensPath() {
        assertEquals("config/SecurityConfig.java", HighlightSelector.shortenPath(
                "src/main/java/com/example/git_job/config/SecurityConfig.java"));
        assertEquals("build.gradle", HighlightSelector.shortenPath("build.gradle"));
        assertEquals("a/B.java", HighlightSelector.shortenPath("a/B.java"));
    }

    @Test
    @DisplayName("mine 이 null 이면 false 로 나간다")
    void unknownAuthorshipShipsAsFalse() {
        // 미확인과 남의 것의 구분은 authorship 이 싣는다. highlight 에서 true 로
        // 두면 요약이 "본인이 썼다"고 말하게 된다.
        List<FactPack.Highlight> highlights = selector.select(List.of(
                call("SecurityFilterChain", "a/A.java", 1, null)));

        assertFalse(highlights.getFirst().mine());
    }

    @Test
    @DisplayName("근거가 없으면 빈 목록")
    void emptyInputIsEmptyOutput() {
        assertTrue(selector.select(List.of()).isEmpty());
    }
}
