package com.example.git_job.support;

import org.testcontainers.DockerClientFactory;

/**
 * 실제 인프라가 필요한 테스트의 실행 조건.
 *
 * <p>{@code @EnabledIf("com.example.git_job.support.DockerAvailable#check")}로 건다.
 * 환경변수 플래그를 쓰지 않는 이유는, 플래그를 잊으면 CDC 파이프라인과 스키마 정합성이
 * <b>조용히 검증되지 않은 채</b> 빌드가 초록색으로 끝나기 때문이다. Docker가 떠 있는
 * 개발 환경에서는 항상 돌고, 없는 환경에서는 알아서 건너뛴다.</p>
 *
 * <p>Testcontainers의 {@code @Testcontainers(disabledWithoutDocker = true)}가 같은 일을
 * 하지만 {@code testcontainers-junit-jupiter} 의존성이 더 필요하다. 이 테스트들은
 * {@code @Container} 필드 없이 컨테이너를 직접 관리하므로 그 확장의 나머지 기능은
 * 쓰지 않는다.</p>
 */
public final class DockerAvailable {

    /** Docker가 있어도 느린 테스트를 건너뛰고 싶을 때의 탈출구. */
    public static final String OPT_OUT = "DOCKER_TESTS";

    private DockerAvailable() {
    }

    public static boolean check() {
        if ("false".equalsIgnoreCase(System.getenv(OPT_OUT))) {
            return false;
        }
        // 결과는 Testcontainers가 캐시하므로 클래스마다 다시 탐색하지 않는다.
        return DockerClientFactory.instance().isDockerAvailable();
    }
}
