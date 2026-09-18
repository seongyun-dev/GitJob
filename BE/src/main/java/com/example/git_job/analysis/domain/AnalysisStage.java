package com.example.git_job.analysis.domain;

import java.util.Optional;

/**
 * 분석이 지나는 단계와 그 순서.
 *
 * <p>{@code analysis_job.current_stage} 에 이름 그대로 저장된다. 컬럼이
 * {@code VARCHAR(40)} 이므로 새 단계를 더할 때 이름 길이를 먼저 본다.</p>
 *
 * <h2>왜 순서를 붙이는가</h2>
 *
 * <p>진행 이벤트는 at-least-once 로 오고, 클레임 테이크오버가 일어나면 같은 분석이
 * 처음부터 다시 돈다. 순서가 없으면 그때 화면이 "개인 기여도 분석중"에서
 * "저장소 분석중"으로 되돌아간다. 사용자에게는 분석이 실패하고 다시 시작한 것처럼
 * 보이지만 실제로는 아무 일도 일어나지 않았다.</p>
 *
 * <h2>{@link AnalysisJob} 은 여전히 문자열로 들고 있다</h2>
 *
 * <p>엔티티의 필드를 이 enum 으로 바꾸지 않는다. 읽기가 이름 하나로 깨지면 그
 * 분석은 화면에서 통째로 사라지는데, 단계는 표시용 값이라 그만한 위험을 질
 * 이유가 없다. 이 enum 은 <b>순서를 판정할 때만</b> 쓰고, 모르는 이름은
 * {@link #parse} 가 비어 있는 값으로 돌려준다.</p>
 */
public enum AnalysisStage {

    /** 접수 직후. 워커가 아직 이 분석을 집지 않았다. */
    WAITING_FOR_WORKER(0),

    /** 클론이 끝나고 의존성·설정 스캔과 Evidence 판정이 도는 구간. */
    ANALYZING_REPOSITORY(1),

    /** git blame 으로 근거를 쓴 사람을 가리는 구간. */
    ATTRIBUTING_CONTRIBUTION(2),

    /** 종료. 순서를 같이 두는 이유는 둘 다 더 나아갈 곳이 없기 때문이다. */
    COMPLETED(3),
    FAILED(3);

    private final int order;

    AnalysisStage(int order) {
        this.order = order;
    }

    public int order() {
        return order;
    }

    /**
     * 워커가 진행 이벤트로 알릴 수 있는 단계인가.
     *
     * <p>대기는 접수가 만들고 종료는 결과 이벤트가 만든다. 진행 토픽으로 그 둘이
     * 들어오면 결과 경로와 두 곳에서 같은 전이를 쓰게 되므로 받지 않는다.</p>
     */
    public boolean reportableByWorker() {
        return this == ANALYZING_REPOSITORY || this == ATTRIBUTING_CONTRIBUTION;
    }

    /** 모르는 이름은 비어 있는 값이다. 예외를 던지면 표시용 값이 분석을 멈춘다. */
    public static Optional<AnalysisStage> parse(String name) {
        if (name == null) {
            return Optional.empty();
        }
        for (AnalysisStage stage : values()) {
            if (stage.name().equals(name)) {
                return Optional.of(stage);
            }
        }
        return Optional.empty();
    }
}
