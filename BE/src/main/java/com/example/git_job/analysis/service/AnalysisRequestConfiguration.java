package com.example.git_job.analysis.service;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AnalysisRequestProperties.class)
class AnalysisRequestConfiguration {
}
