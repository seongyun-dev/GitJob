package com.example.git_job.monitoring.service;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Duration;
import java.util.Arrays;

/**
 * 시계열 조회 범위와 그에 맞는 step (S15P21E102-209).
 *
 * <p>지금은 값이 하나다. 확정 디자인 v2의 Resource Overview가 "최근 60분 · 5분 간격"
 * 하나만 그리고, 화면에 범위 선택 컨트롤이 없다. 6시간·24시간을 미리 넣어 두지 않은 이유는
 * 그것을 고를 화면이 아직 없기 때문이다 — 범위 선택이 화면에 생기면 여기 한 줄을 더한다.</p>
 *
 * <p>범위와 step을 한 값에 묶어 둔 이유는 둘이 따로 오면 24시간을 1분 step으로 요청해
 * 1440점을 뽑는 일이 생기기 때문이다. 그건 화면에서 구분되지 않고 Prometheus만 갈린다.</p>
 */
public enum TimeRange {

    LAST_60M("60m", Duration.ofMinutes(60), Duration.ofMinutes(5));

    public static final TimeRange DEFAULT = LAST_60M;

    private final String wireName;
    private final Duration window;
    private final Duration step;

    TimeRange(String wireName, Duration window, Duration step) {
        this.wireName = wireName;
        this.window = window;
        this.step = step;
    }

    public String wireName() {
        return wireName;
    }

    public Duration window() {
        return window;
    }

    public Duration step() {
        return step;
    }

    /**
     * 값이 없으면 기본 범위다. 값이 있는데 목록에 없으면 400이며, 조용히 기본값으로
     * 바꾸지 않는다 — 화면이 요청한 것과 다른 범위를 그리면 눈으로는 구분되지 않는다.
     */
    public static TimeRange from(String raw) {
        if (raw == null || raw.isBlank()) {
            return DEFAULT;
        }
        String normalized = raw.strip().toLowerCase();
        return Arrays.stream(values())
                .filter(range -> range.wireName.equals(normalized))
                .findFirst()
                .orElseThrow(() -> new CustomException(ErrorCode.INVALID_REQUEST_PARAMETER));
    }
}
