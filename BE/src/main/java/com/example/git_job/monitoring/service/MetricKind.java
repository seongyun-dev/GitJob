package com.example.git_job.monitoring.service;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.Arrays;

/**
 * 시계열로 조회할 수 있는 지표 (S15P21E102-209).
 *
 * <p>닫힌 목록인 것이 이 타입의 핵심이다. 클라이언트가 PromQL을 보내게 하면 이
 * 엔드포인트가 관리자망 Prometheus에 대한 임의 질의 창구가 된다. 화면이 고를 수 있는 것은
 * 여기 있는 이름뿐이고, 실제 질의는 {@link MonitoringQueries}가 만든다.</p>
 *
 * <p>세 개뿐인 이유는 확정 디자인 v2가 시계열로 그리는 것이 셋이기 때문이다 —
 * Resource Overview의 CPU·Memory 겹친 선 그래프와 Network IN/OUT 그래프. Disk는 시계열이
 * 아니라 용량 바로 표시되므로 {@code overview}의 현재값으로 충분하고, disk I/O는 화면에
 * 쓰는 자리가 없다. Prometheus가 수집하고 있다는 것과 이번 API가 제공해야 한다는 것은
 * 다른 문제다 — 쓰는 화면이 생기면 그때 추가한다.</p>
 */
public enum MetricKind {

    CPU("cpu", MetricUnit.PERCENT),
    MEMORY("memory", MetricUnit.PERCENT),
    /** receive·transmit 두 방향으로 나뉜다. */
    NETWORK("network", MetricUnit.BYTES_PER_SECOND);

    private final String wireName;
    private final MetricUnit unit;

    MetricKind(String wireName, MetricUnit unit) {
        this.wireName = wireName;
        this.unit = unit;
    }

    public String wireName() {
        return wireName;
    }

    public MetricUnit unit() {
        return unit;
    }

    /** 요청 파라미터를 해석한다. 목록에 없으면 400이며 기본값으로 바꾸지 않는다. */
    public static MetricKind from(String raw) {
        if (raw == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_PARAMETER);
        }
        String normalized = raw.strip().toLowerCase();
        return Arrays.stream(values())
                .filter(kind -> kind.wireName.equals(normalized))
                .findFirst()
                .orElseThrow(() -> new CustomException(ErrorCode.INVALID_REQUEST_PARAMETER));
    }
}
