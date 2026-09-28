package com.example.git_job.analysis.outbox;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AnalysisOutboxProperties.class)
@Import(AnalysisOutboxPollingConfiguration.class)
class AnalysisOutboxConfiguration {
}
