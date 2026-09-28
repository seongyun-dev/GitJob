package com.example.git_job.analysis.messaging;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.event.TechnologyCandidate;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.support.serializer.JacksonJsonDeserializer;

/**
 * 워커가 실제로 발행한 JSON 을 운영 역직렬화기로 읽는다.
 *
 * <h2>왜 이 테스트가 따로 있는가</h2>
 *
 * <p>{@code RepositoryAnalysisResultEventTest} 는 record 생성자를 직접 부른다. 계약을
 * 검사하는 것처럼 보이지만 실제로는 생성자만 검사하고, JSON 은 한 줄도 읽지 않는다.
 * 그래서 {@code AnalysisStats.syntaxNodeCount} 가 primitive {@code int} 로 선언됐을 때
 * 전부 통과했다 -- 테스트는 항상 값을 넘겨 주니까. 운영에서는 v1 결과에 그 필드가
 * 아예 없었고, Jackson 은 빠진 값을 primitive 에 넣지 못해 <b>결과 이벤트 전체</b>를
 * 거절했다. 저장소 4개의 판정과 근거가 사라졌고 분석은 QUEUED 에 남았다.</p>
 *
 * <p>여기서는 fixture 를 복사하지 않고 생산자 쪽 파일을 그대로 읽는다. 복사본은 반드시
 * 갈라지고, 갈라진 순간 이 테스트는 계약이 아니라 과거의 기억을 검사하게 된다.
 * 생산자 쪽 검증은 {@code AI/tests/test_analysis_results.py} 와 그 v2·v3 짝이다.</p>
 */
class RepositoryAnalysisResultContractTest {

    /**
     * 워커 fixture 의 위치. Gradle 은 프로젝트 디렉터리({@code BE/})에서 테스트를 돌리고
     * CI 도 {@code cd BE && ./gradlew test} 로 실행한다. 이미지 빌드는 {@code bootJar}
     * 만 돌려 테스트를 타지 않으므로 {@code BE/} 만 복사돼도 문제가 없다.
     */
    private static final Path FIXTURES = Path.of("..", "AI", "tests", "fixtures");

    private static final String V1 = "repository-analysis-result-v1-base-3a4c57c.json";
    private static final String V2 = "repository-analysis-result-v2-base-c43f76d.json";
    private static final String V3 = "repository-analysis-result-v3-base-c43f76d.json";

    private final JacksonJsonDeserializer<RepositoryAnalysisResultEvent> deserializer =
            RepositoryAnalysisKafkaConfiguration.resultValueDeserializer();

    @Test
    void readsEveryContractTheWorkerCanPublish() {
        // 워커는 Registry 버전에 따라 하나를 골라 발행하고 v1 을 함께 보내지 않는다.
        // 하나라도 못 읽으면 그 Registry 를 쓰는 모든 분석이 통째로 도달하지 않는다.
        assertEquals("repository-analysis-result/v1", read(V1).schemaVersion());
        assertEquals("repository-analysis-result/v2", read(V2).schemaVersion());
        assertEquals("repository-analysis-result/v3", read(V3).schemaVersion());
    }

    @Test
    void readsV1EvenThoughItHasNoSyntaxNodeCount() {
        // 이것이 실제로 터진 것이다. 이 필드는 v3 부터 생겼고, 읽는 곳은 한 군데도 없다.
        var stats = read(V1).payload().stats();

        assertNotNull(stats);
        assertNull(stats.syntaxNodeCount());
        assertFalse(stats.reportedSyntaxNodes());
    }

    @Test
    void keepsNotReportedApartFromZero() {
        // v1 은 건너뛴 사유를 싣지 않는다. 그것은 "건너뛴 것이 없다"가 아니라 "모른다"다.
        // 빈 Map 으로 바꾸면 저장소 전체를 본 적 없는 분석이 완전 판정으로 C 에 나간다.
        var v1 = read(V1).payload();
        assertFalse(v1.stats().reportedSkips());
        assertTrue(v1.stats().skippedAnything());
        assertFalse(v1.coverageComplete());

        var v3 = read(V3).payload();
        assertTrue(v3.stats().reportedSkips());
        assertEquals(3, v3.stats().skippedReasons().size());
    }

    @Test
    void readsTheRulePackLineageThatCIsScoredAgainst() {
        // v1 에는 없고 v2 부터 실린다. 없으면 C 가 근거의 범위를 검사할 수 없어
        // 그 분석은 추천까지 이어지지 못한다.
        assertFalse(read(V1).payload().hasRulePackLineage());
        assertTrue(read(V2).payload().hasRulePackLineage());

        var v3 = read(V3).payload();
        assertTrue(v3.hasRulePackLineage());
        assertEquals("rule-pack-20260911.3", v3.rulePackVersion());
        assertEquals("L1", v3.technologySupport().getFirst().maxSupportedLevel());
    }

    @Test
    void readsDependencyEcosystemsOutsideTheJvm() {
        // GO·CARGO·COMPOSER 는 v2 계약에 있었지만 BE enum 에는 없었다. enum 은 Jackson 이
        // 읽는 자리라, 모르는 값 하나가 후보 하나가 아니라 결과 전체를 무효로 만든다 --
        // Go·Rust·PHP 저장소를 분석한 사용자는 판정과 근거까지 함께 잃는다.
        assertEquals(Set.of(TechnologyCandidate.Ecosystem.CARGO,
                        TechnologyCandidate.Ecosystem.COMPOSER),
                ecosystems(read(V2)));
        assertEquals(Set.of(TechnologyCandidate.Ecosystem.GO), ecosystems(read(V3)));
    }

    @Test
    void readsAContractThatGrewAFieldThisServiceDoesNotKnow() {
        // v3 의 stats 에는 이미 BE 가 모르는 숫자가 넷 있다(source_file_count 등).
        // 지금은 Jackson 3 의 기본값 덕분에 읽히고 있어서, 전역 설정이 바뀌면 조용히
        // 같은 장애가 돌아온다. 역직렬화기에 못 박아 둔 설정을 여기서 지킨다.
        String grown = json(V1).replaceFirst("\\{",
                "{\"a_field_from_a_later_contract\": \"whatever\",");

        assertDoesNotThrow(() -> deserialize(grown));
    }

    @Test
    void stillRefusesAContractItCannotInterpret() {
        // 너그러움은 모르는 '필드'까지다. 모르는 '계약'은 기존 필드의 뜻이 바뀌었을 수
        // 있어서, 반쯤 해석해 저장하면 그 사실이 어디에도 남지 않는다.
        String v4 = json(V1).replace(
                "repository-analysis-result/v1", "repository-analysis-result/v4");

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> deserialize(v4));
        assertTrue(rootCause(thrown).getMessage().contains("schemaVersion"),
                () -> "unexpected failure: " + rootCause(thrown));
    }

    private RepositoryAnalysisResultEvent read(String fixture) {
        return deserialize(json(fixture));
    }

    private RepositoryAnalysisResultEvent deserialize(String json) {
        return deserializer.deserialize(
                "gitjob.repository-analysis.results.v1", json.getBytes(StandardCharsets.UTF_8));
    }

    private static Set<TechnologyCandidate.Ecosystem> ecosystems(
            RepositoryAnalysisResultEvent event) {
        List<TechnologyCandidate> candidates = event.payload().candidates();
        return candidates.stream().map(TechnologyCandidate::ecosystem)
                .collect(Collectors.toUnmodifiableSet());
    }

    private static Throwable rootCause(Throwable thrown) {
        Throwable cause = thrown;
        while (cause.getCause() != null && cause.getCause() != cause) {
            cause = cause.getCause();
        }
        return cause;
    }

    private static String json(String fixture) {
        Path path = FIXTURES.resolve(fixture);
        try {
            return Files.readString(path, StandardCharsets.UTF_8);
        } catch (IOException missing) {
            // 조용히 건너뛰지 않는다. 읽히지 않는 계약 테스트는 통과한 계약 테스트처럼
            // 보이고, 그것이 이 파일이 존재하는 이유다.
            throw new UncheckedIOException(
                    "worker fixture not readable at " + path.toAbsolutePath(), missing);
        }
    }
}
