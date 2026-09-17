package com.example.git_job.analysis.summary;

import com.example.git_job.analysis.query.TechnologySummaryFactStore.EvidenceFact;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * 근거 수십 건을 사실 8개로 줄인다.
 *
 * <h2>왜 순서가 중요한가</h2>
 *
 * <p>요약 서비스의 캐시 키는 <b>정규화된 Fact Pack 전체의 sha256</b> 이다. 같은
 * 입력에 선별 결과가 흔들리면 키가 매번 달라지고, 그러면 캐시가 영영 맞지 않아
 * 같은 요약에 GPU 를 계속 태운다. 그래서 이 클래스는 결정적이어야 한다.</p>
 *
 * <p>{@code AI/llm/facts.py} 의 {@code select_highlights} 와 같은 규칙이다. 한쪽만
 * 바뀌면 조용히 어긋나므로, 고칠 일이 생기면 양쪽을 함께 본다.</p>
 */
@Component
public class HighlightSelector {

    /**
     * {@code fact_payload} 에서 이름을 꺼낼 키. {@code value} 라는 키는 없다.
     *
     * <p>{@code API_CALL} 이 {@code CALL} 을 먼저 읽는다. {@code METHOD} 는 마지막
     * 조각이라 {@code run}, {@code get}, {@code build} 처럼 혼자서는 아무것도
     * 가리키지 않는 값이 나오고, 요약이 "run 을 호출했다"가 된다. {@code CALL} 은
     * 수신자를 포함해 {@code SpringApplication.run} 이다.</p>
     *
     * <p>{@code CONFIG_KEY} 는 {@code KEY} 만 읽고 {@code VALUE} 는 읽지 않는다.
     * 설정 값은 파일에 적힌 그대로라 접속 문자열이나 비밀번호가 들어 있을 수
     * 있고, 그것이 프롬프트에도 카드 문장에도 실릴 이유가 없다.</p>
     */
    private static final Map<String, List<String>> VALUE_KEYS = Map.of(
            "IMPORT", List.of("MODULE"),
            "DEPENDENCY", List.of("COORDINATE"),
            "API_CALL", List.of("CALL", "METHOD"),
            "ANNOTATION", List.of("NAME"),
            "SYNTAX_NODE", List.of("NAME"),
            "CONFIG_KEY", List.of("KEY"),
            "SOURCE_FILE", List.of("FILE_PATH"));

    /**
     * 컨텍스트를 먼저 차지할 종류. 각 종류가 닿는 가장 높은 규칙 Level 순이다.
     *
     * <p>{@code SOURCE_FILE} 이 아래인 이유가 하나 더 있다 -- 그 값은 파일 경로이고,
     * highlight 의 {@code file} 이 이미 같은 것을 싣는다.</p>
     */
    private static final List<String> TYPE_RANK = List.of(
            "API_CALL", "ANNOTATION", "SYNTAX_NODE", "CONFIG_KEY",
            "IMPORT", "SOURCE_FILE", "DEPENDENCY");

    private final JsonMapper mapper = JsonMapper.builder().build();

    /** 값 기준으로 중복을 제거하고, 순위대로 잘라, 남은 것에 번호를 매긴다. */
    public List<FactPack.Highlight> select(List<EvidenceFact> facts) {
        Map<String, Candidate> bestByValue = new LinkedHashMap<>();
        for (EvidenceFact fact : facts) {
            String value = valueOf(fact);
            if (value == null) {
                // 이 종류의 키가 payload 에 없다. 이름 없이 보낼 수는 없으므로
                // 버린다 -- 빈 이름은 요약에서 아무것도 설명하지 못한다.
                continue;
            }
            Candidate candidate = new Candidate(fact, value);
            Candidate current = bestByValue.get(value);
            if (current == null || ORDER.compare(candidate, current) < 0) {
                bestByValue.put(value, candidate);
            }
        }

        List<Candidate> ranked = new ArrayList<>(bestByValue.values());
        ranked.sort(ORDER.thenComparing(Candidate::value));

        List<FactPack.Highlight> highlights = new ArrayList<>();
        for (Candidate candidate : ranked.subList(0,
                Math.min(ranked.size(), FactPack.MAX_HIGHLIGHTS))) {
            highlights.add(new FactPack.Highlight(
                    highlights.size(),
                    candidate.fact().factType(),
                    candidate.value(),
                    shortenPath(candidate.fact().filePath()),
                    Boolean.TRUE.equals(candidate.fact().mine())));
        }
        return List.copyOf(highlights);
    }

    /**
     * 본인 것 먼저, 높은 종류 먼저, 그다음은 파일과 줄 번호.
     *
     * <p>기여 판정이 없는 근거({@code mine == null})는 남이 쓴 것보다 <b>뒤</b>다.
     * PostgreSQL 의 {@code DESC} 가 {@code NULLS FIRST} 인 것과 맞춘 순서로,
     * 이렇게 하지 않으면 미확인 근거가 본인 근거를 밀어낸다.</p>
     */
    private static final Comparator<Candidate> ORDER = Comparator
            .comparingInt((Candidate candidate) -> mineRank(candidate.fact().mine()))
            .thenComparingInt(candidate -> typeRank(candidate.fact().factType()))
            .thenComparing(candidate -> candidate.fact().filePath())
            .thenComparingInt(candidate -> candidate.fact().startLine());

    private static int mineRank(Boolean mine) {
        if (Boolean.TRUE.equals(mine)) {
            return 0;
        }
        return Boolean.FALSE.equals(mine) ? 1 : 2;
    }

    private static int typeRank(String factType) {
        int rank = TYPE_RANK.indexOf(factType);
        // 모르는 종류는 맨 뒤. 레지스트리가 새 fact_type 을 내기 시작해도 요약이
        // 멈추지 않고, 아는 것부터 채운다.
        return rank < 0 ? TYPE_RANK.size() : rank;
    }

    private String valueOf(EvidenceFact fact) {
        List<String> keys = VALUE_KEYS.get(fact.factType());
        if (keys == null || fact.payloadJson() == null) {
            return null;
        }
        JsonNode payload;
        try {
            payload = mapper.readTree(fact.payloadJson());
        } catch (JacksonException malformed) {
            return null;
        }
        for (String key : keys) {
            JsonNode node = payload.get(key);
            if (node != null && node.isString() && !node.asString().isBlank()) {
                return node.asString().trim();
            }
        }
        return null;
    }

    /**
     * 경로의 마지막 두 조각.
     *
     * <p>{@code src/main/java/com/example/...} 를 그대로 보내면 토큰만 먹고 요약에
     * 기여하지 않는다. 받는 쪽도 똑같이 줄이므로 여기서 줄이지 않아도 값은 같지만,
     * 캐시 키는 우리가 보낸 것으로 계산되므로 보내기 전에 맞춰 둔다.</p>
     */
    static String shortenPath(String filePath) {
        String[] segments = filePath.split("/");
        if (segments.length <= 2) {
            return filePath;
        }
        return segments[segments.length - 2] + "/" + segments[segments.length - 1];
    }

    private record Candidate(EvidenceFact fact, String value) {
    }
}
