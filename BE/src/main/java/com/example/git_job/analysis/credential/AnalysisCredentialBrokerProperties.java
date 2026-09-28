package com.example.git_job.analysis.credential;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("gitjob.analysis.credential-broker")
public record AnalysisCredentialBrokerProperties(
        @DefaultValue("false") boolean enabled,
        @DefaultValue("") String serviceToken
) {
    public AnalysisCredentialBrokerProperties {
        serviceToken = serviceToken == null ? "" : serviceToken;
        if (enabled && serviceToken.isBlank()) {
            throw new IllegalArgumentException(
                    "serviceToken is required when the analysis credential broker is enabled"
            );
        }
    }
}
