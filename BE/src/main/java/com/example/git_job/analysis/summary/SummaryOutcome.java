package com.example.git_job.analysis.summary;

import java.util.Optional;

/**
 * 요약 한 건을 만들어 보고 나온 결과.
 *
 * <p>{@code Optional} 하나로는 부족해서 만들었다. "지금은 자리가 없다"와 "서비스가
 * 없다"는 부르는 쪽이 할 일이 정반대인데, 빈 {@code Optional} 로 합치면 둘이 같아
 * 보인다. 앞쪽은 곧 다시 물으면 채워지고, 뒤쪽은 다시 물어도 같다.</p>
 *
 * <p>이 구분이 필요한 이유는 GPU 가 한 대이기 때문이다. 카드 열두 장이 한꺼번에
 * 들어오면 대부분은 자리를 못 받는데, 그것을 "요약 없음"으로 내리면 화면은 새로
 * 고칠 때마다 같은 자리가 비는 것을 보게 된다 -- 사실은 조금 기다리면 되는
 * 상태인데도.</p>
 */
public record SummaryOutcome(Kind kind, TechnologySummaryResponse response) {

    public enum Kind {
        /** 문장을 받았다. {@code FALLBACK} 도 여기다 -- 모델이 못 썼을 뿐 결과는 있다. */
        GENERATED,
        /** 동시 실행 자리가 없어 보내지 못했다. 잠시 뒤 다시 물으면 된다. */
        BUSY,
        /** 서비스가 꺼졌거나 미설정이거나 응답이 쓸 수 없는 모양이었다. */
        UNAVAILABLE
    }

    public static SummaryOutcome generated(TechnologySummaryResponse response) {
        return new SummaryOutcome(Kind.GENERATED, response);
    }

    public static SummaryOutcome busy() {
        return new SummaryOutcome(Kind.BUSY, null);
    }

    public static SummaryOutcome unavailable() {
        return new SummaryOutcome(Kind.UNAVAILABLE, null);
    }

    public boolean isBusy() {
        return kind == Kind.BUSY;
    }

    /** 응답이 있을 때만 채워진다. {@code GENERATED} 라도 본문이 비었으면 비어 있다. */
    public Optional<TechnologySummaryResponse> body() {
        return Optional.ofNullable(response);
    }
}
