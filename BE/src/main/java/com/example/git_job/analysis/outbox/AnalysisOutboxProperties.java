package com.example.git_job.analysis.outbox;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("gitjob.analysis.outbox")
public record AnalysisOutboxProperties(
        @DefaultValue("CDC") Mode mode,
        @DefaultValue("true") boolean enabled,
        @DefaultValue("20") int batchSize,
        @DefaultValue("10") int maxAttempts,
        @DefaultValue("10s") Duration sendTimeout,
        @DefaultValue("5s") Duration retryDelay,
        @DefaultValue("5m") Duration maxRetryDelay
) {
    public enum Mode { CDC, POLLING }

    public AnalysisOutboxProperties {
        if (mode == null) {
            throw new IllegalArgumentException("Outbox mode is required");
        }
        if (batchSize < 1 || maxAttempts < 1 || maxAttempts > 1000) {
            throw new IllegalArgumentException("Invalid outbox batch size or attempt limit");
        }
        for (Duration duration : new Duration[]{sendTimeout, retryDelay, maxRetryDelay}) {
            if (duration == null || duration.toMillis() < 1) {
                throw new IllegalArgumentException("Outbox durations must be at least 1ms");
            }
        }
        if (maxRetryDelay.compareTo(retryDelay) < 0) {
            throw new IllegalArgumentException("maxRetryDelay must be >= retryDelay");
        }
    }

    public Duration delayAfter(int attempts) {
        long millis = retryDelay.toMillis();
        long maximum = maxRetryDelay.toMillis();
        for (int i = 1; i < attempts && millis < maximum; i++) {
            millis = millis > maximum / 2 ? maximum : millis * 2;
        }
        return Duration.ofMillis(Math.min(millis, maximum));
    }
}
