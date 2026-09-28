package com.example.git_job.analysis.service;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 분석 요청 설정과 {@link StaleAnalysisReaper} 스케줄러를 켠다.
 *
 * <p>{@code @EnableScheduling}이 {@code AnalysisOutboxPollingConfiguration}에도 있지만
 * 그 설정은 {@code ANALYSIS_OUTBOX_MODE=POLLING}에서만 활성화된다. 기본값 CDC 배포에서
 * reaper가 돌지 않으면 멈춘 분석이 그대로 남으므로 여기서 따로 켠다.</p>
 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AnalysisRequestProperties.class)
@EnableScheduling
class AnalysisRequestConfiguration {
}
