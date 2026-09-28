package com.example.git_job;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * The wiring check: every bean the application declares can be built.
 *
 * <p>Kafka listeners are not started. This test needs a database — Flyway and
 * {@code ddl-auto=validate} run at boot and that is half the point — but it has
 * no reason to need a broker, and CI only starts PostgreSQL for the backend
 * stage. Leaving auto-startup on made a broker a prerequisite for a test that
 * asserts nothing about messaging.</p>
 */
@SpringBootTest(properties = "spring.kafka.listener.auto-startup=false")
class GitJobApplicationTests {

	@Test
	void contextLoads() {
	}

}
