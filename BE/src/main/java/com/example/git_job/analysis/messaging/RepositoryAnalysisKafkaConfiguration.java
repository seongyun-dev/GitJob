package com.example.git_job.analysis.messaging;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(RepositoryAnalysisKafkaProperties.class)
class RepositoryAnalysisKafkaConfiguration {
}
