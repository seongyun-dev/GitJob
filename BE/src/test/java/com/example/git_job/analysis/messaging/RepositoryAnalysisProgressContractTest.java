package com.example.git_job.analysis.messaging;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.event.RepositoryAnalysisProgressEvent;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.support.serializer.JacksonJsonDeserializer;

/**
 * 워커가 발행할 JSON 을 운영 역직렬화기로 읽는다.
 *
 * <p>{@code RepositoryAnalysisResultContractTest} 와 같은 이유로 존재한다 -- record
 * 생성자만 부르는 테스트는 JSON 을 한 줄도 읽지 않아서, 필드 이름이 어긋나 있어도
 * 전부 통과한다. fixture 는 복사하지 않고 생산자 쪽 파일을 그대로 읽는다.</p>
 *
 * <p>진행 이벤트를 못 읽어도 분석은 결과 이벤트로 정상 종료된다. 그래서 이 계약이
 * 깨졌을 때의 증상은 "화면이 예전처럼 QUEUED 에 머문다" 뿐이고, 로그를 보지 않으면
 * 기능이 아직 배포되지 않은 것과 구분되지 않는다. 그 조용함이 이 테스트가 필요한
 * 이유다.</p>
 */
class RepositoryAnalysisProgressContractTest {

    private static final Path FIXTURES = Path.of("..", "AI", "tests", "fixtures");

    private static final String ANALYZING = "repository-analysis-progress-v1-analyzing.json";
    private static final String ATTRIBUTING = "repository-analysis-progress-v1-attributing.json";

    private final JacksonJsonDeserializer<RepositoryAnalysisProgressEvent> deserializer =
            RepositoryAnalysisKafkaConfiguration.progressValueDeserializer();

    @Test
    void readsBothStagesTheWorkerPublishes() {
        assertEquals("ANALYZING_REPOSITORY", read(ANALYZING).payload().stage());
        assertEquals("ATTRIBUTING_CONTRIBUTION", read(ATTRIBUTING).payload().stage());
        assertEquals("an_1", read(ANALYZING).payload().analysisId());
    }

    @Test
    void readsAContractThatGrewAFieldThisServiceDoesNotKnow() {
        // 워커가 단계에 진행률이나 파일 수를 덧붙이는 날이 온다. 그때 읽는 곳이 없는
        // 필드 하나로 단계 전환을 통째로 잃으면, 화면은 조용히 예전으로 돌아간다.
        String grown = json(ANALYZING).replaceFirst("\\{",
                "{\"a_field_from_a_later_contract\": \"whatever\",");

        assertDoesNotThrow(() -> deserialize(grown));
    }

    @Test
    void acceptsAStageThisVersionDoesNotKnowYet() {
        // 단계 이름을 enum 으로 받지 않기로 한 결정을 지킨다. 워커와 BE 는 따로
        // 배포되므로 새 단계가 먼저 도착하는 순서는 정상이고, 그때 거절하면 그
        // 분석의 <b>다른</b> 단계 전환까지 같은 배치에서 함께 흔들린다.
        String future = json(ANALYZING).replace("ANALYZING_REPOSITORY", "SUMMARIZING");

        assertEquals("SUMMARIZING", assertDoesNotThrow(() -> deserialize(future))
                .payload().stage());
    }

    @Test
    void stillRefusesAContractItCannotInterpret() {
        // 너그러움은 모르는 '필드'와 모르는 '단계'까지다. 모르는 '계약'은 기존 필드의
        // 뜻이 바뀌었을 수 있다.
        String v2 = json(ANALYZING).replace(
                "repository-analysis-progress/v1", "repository-analysis-progress/v2");

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> deserialize(v2));
        assertTrue(rootCause(thrown).getMessage().contains("schemaVersion"),
                () -> "unexpected failure: " + rootCause(thrown));
    }

    private RepositoryAnalysisProgressEvent read(String fixture) {
        return deserialize(json(fixture));
    }

    private RepositoryAnalysisProgressEvent deserialize(String json) {
        return deserializer.deserialize(
                "gitjob.repository-analysis.progress.v1", json.getBytes(StandardCharsets.UTF_8));
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
            throw new UncheckedIOException(
                    "worker fixture not readable at " + path.toAbsolutePath(), missing);
        }
    }
}
