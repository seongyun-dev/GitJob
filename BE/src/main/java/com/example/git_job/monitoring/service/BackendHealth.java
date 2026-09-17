package com.example.git_job.monitoring.service;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.health.actuate.endpoint.HealthEndpoint;
import org.springframework.boot.health.contributor.Status;
import org.springframework.stereotype.Component;
import lombok.extern.slf4j.Slf4j;

/**
 * Backend 자신의 살아 있음 (S15P21E102-321).
 *
 * <h2>왜 Prometheus가 아닌가</h2>
 *
 * <p>Backend는 Prometheus scrape 대상이 아니다. micrometer exposition endpoint가 없고,
 * 운영 nginx는 {@code /actuator/*}를 라우팅하지 않아 밖에서 두드릴 주소도 없다. 대신 같은
 * 값을 이미 컨테이너 healthcheck가 쓰고 있다 — compose의 backend healthcheck가
 * {@code curl /actuator/health}다. 그 판정을 밖에서 한 번 더 HTTP로 가져오는 대신 같은
 * 프로세스 안에서 직접 읽는다. 새 포트도, 새 컨테이너도, 새 heartbeat 저장소도 필요 없다.</p>
 *
 * <h2>이것은 동어반복이 아니다</h2>
 *
 * <p>"응답했으니 살아 있다"를 말하는 것이 아니다. Actuator 집계는 등록된 contributor —
 * DataSource·디스크 여유 등 — 의 상태를 합친 값이다. 프로세스는 떠 있는데 DB에 닿지
 * 못하는 상태가 {@code DOWN}으로 나온다. 화면이 알고 싶은 것이 정확히 그것이다.</p>
 *
 * <h2>세 가지 상태</h2>
 *
 * <p>{@code UP}만 {@code true}, {@code DOWN}·{@code OUT_OF_SERVICE}만 {@code false}다.
 * Actuator가 스스로 {@code UNKNOWN}이라고 한 것은 {@code null}로 옮긴다 — 모른다는 말을
 * 죽었다는 말로 바꾸지 않는다. Actuator가 아예 없는 구성(테스트 슬라이스 등)에서도
 * {@link ObjectProvider}가 비어 {@code null}이 되고, 판정하지 않는다.</p>
 */
@Slf4j
@Component
public class BackendHealth {

    private final ObjectProvider<HealthEndpoint> healthEndpoint;

    public BackendHealth(ObjectProvider<HealthEndpoint> healthEndpoint) {
        this.healthEndpoint = healthEndpoint;
    }

    /** 살아 있으면 {@code true}, 죽었으면 {@code false}, 판정할 수 없으면 {@code null}. */
    public Boolean upOrNull() {
        HealthEndpoint endpoint = healthEndpoint.getIfAvailable();
        if (endpoint == null) {
            return null;
        }
        try {
            Status status = endpoint.health().getStatus();
            if (Status.UP.equals(status)) {
                return true;
            }
            if (Status.DOWN.equals(status) || Status.OUT_OF_SERVICE.equals(status)) {
                return false;
            }
            return null;
        } catch (RuntimeException e) {
            // health 집계가 터진 것은 "죽었다"가 아니라 "재지 못했다"다.
            log.warn("Backend health 집계 실패: {}", e.getMessage());
            return null;
        }
    }
}
