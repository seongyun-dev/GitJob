package com.example.git_job.compute.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/** C 계산의 저장된 backoff를 처리하는 scheduler를 활성화한다. */
@Configuration(proxyBeanMethods = false)
@EnableScheduling
public class ComputeRetryConfiguration {
}
