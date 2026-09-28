package com.example.git_job.analysis.summary;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.analysis.query.TechnologySummaryFactStore;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 개발 DB 의 실제 데이터로 Fact Pack 을 만들어 파일로 내보낸다.
 *
 * <p>검증용 도구다. 계약이 맞는지 보려면 우리가 만든 JSON 을 받는 쪽 모델에
 * 실제로 먹여 봐야 하는데, 그쪽은 Python 이다. 여기서 파일로 떨군 다음
 * {@code AI/llm/contracts.py} 의 {@code FactPack} 으로 읽으면 이름·형태·제약이
 * 한 번에 걸러진다.</p>
 *
 * <p>{@code DUMP_FACT_PACK} 이 있을 때만 돈다. 평소 테스트 실행에 개발 DB 를
 * 끌어들이지 않기 위해서다.</p>
 */
@EnabledIfEnvironmentVariable(named = "DUMP_FACT_PACK", matches = ".+")
class DumpRealFactPack {

    @Test
    void dump() throws IOException {
        String url = System.getenv().getOrDefault("DUMP_DB_URL",
                "jdbc:postgresql://localhost:5433/gitjob");
        var config = new HikariConfig();
        config.setJdbcUrl(url);
        config.setUsername(System.getenv("POSTGRES_USER"));
        config.setPassword(System.getenv("POSTGRES_PASSWORD"));
        config.setMaximumPoolSize(1);

        try (HikariDataSource dataSource = new HikariDataSource(config)) {
            JdbcTemplate jdbc = new JdbcTemplate(dataSource);
            var builder = new FactPackBuilder(new TechnologyProfileStore(jdbc),
                    new TechnologySummaryFactStore(jdbc), new HighlightSelector());
            var client = new TechnologySummaryClient("", Duration.ofSeconds(1));

            long userId = Long.parseLong(System.getenv().getOrDefault("DUMP_USER_ID", "2"));
            Path out = Path.of(System.getenv().getOrDefault("DUMP_OUT", "fact-packs"));
            Files.createDirectories(out);

            int written = 0;
            for (String techId : System.getenv()
                    .getOrDefault("DUMP_TECHS", "spring-security,lombok,redis,spring-boot")
                    .split(",")) {
                if (builder.build(userId, techId).isEmpty()) {
                    continue;
                }
                written++;
                builder.build(userId, techId).ifPresent(pack -> {
                    try {
                        Files.writeString(out.resolve(techId + ".json"),
                                client.requestBody(userId, pack), StandardCharsets.UTF_8);
                        System.out.println("wrote " + techId);
                    } catch (IOException failed) {
                        throw new IllegalStateException(failed);
                    }
                });
            }
            org.junit.jupiter.api.Assertions.assertTrue(written > 0,
                    "이 DB 에 그 사용자의 판정이 하나도 없다: userId=" + userId);
        }
    }
}
