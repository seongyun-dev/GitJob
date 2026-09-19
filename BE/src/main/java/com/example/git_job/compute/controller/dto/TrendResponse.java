package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CTrend;
import java.util.List;

/**
 * 기술 하나의 출처별 Trend (화면 13) (S15P21E102-279).
 *
 * <h2>출처를 합치지 않는다</h2>
 *
 * <p>인수 조건이 "JOB Trend와 GitHub Trend를 하나의 합성 점수로 섞지 말 것"이다. 세 출처는
 * 세는 대상도 분모도 다르다 -- 주간 활동 저장소 수, 월별 commit 관측 수, 월별 공고 요구
 * 건수. 한 축에 겹쳐 그릴 수 없으므로 배열로 내려보내고 카드를 따로 그린다.</p>
 *
 * <h2>출처 하나가 비어도 요청은 성공이다</h2>
 *
 * <p>{@code dataStatus}가 응답 전체가 아니라 출처마다 붙는 이유다. 주간 데이터는 있는데
 * 역사 Archive가 아직 없는 것은 정상이고, 그때 전체를 오류로 만들면 있는 값도 못 본다.</p>
 */
public record TrendResponse(String techId, List<Source> sources) {

    public record Source(
            /** 화면이 카드를 구분하는 값. C의 source와 1:1이다. */
            String sourceId,
            String cSource,
            String dataStatus,
            String statusReason,
            /** 무엇을 세는지. 출처 간 비교를 막기 위해 반드시 표시한다. */
            String unit,
            String metric,
            String granularity,
            List<String> periods,
            List<Point> points,
            List<String> reasons
    ) {

        /** 아직 값이 없는 출처. 0으로 채우지 않고 비운다. */
        public static Source empty(String sourceId, String cSource, ComputeState state,
                                   String unit) {
            return new Source(sourceId, cSource, state.dataStatus(), state.statusReason(),
                    unit, null, null, List.of(), List.of(), List.of());
        }

        public static Source of(String sourceId, String cSource, ComputeState state,
                                CTrend.Payload payload) {
            List<CTrend.Point> points = payload.points() == null ? List.of() : payload.points();
            boolean github = CTrend.isGithubTrend(cSource);
            /*
             * GitHub 계열은 payload 가 선언한 unit 을 쓰지 않는다 · 티켓 S15P21E102-348.
             *
             * 그 값은 `EVENTS` 인데 그건 `event_count` 의 단위이고, 우리가 싣는 것은
             * 저장소 수다. 그대로 내보내면 화면이 저장소 수를 "GitHub 활동"이라고 읽는다.
             */
            String unit = github ? CTrend.GITHUB_TREND_UNIT : payload.unit();
            return new Source(sourceId, cSource, state.dataStatus(), state.statusReason(),
                    unit, payload.metric(), payload.granularity(),
                    points.stream().map(CTrend.Point::period).toList(),
                    points.stream().map(point -> Point.of(point, github)).toList(),
                    payload.reasons() == null ? List.of() : payload.reasons());
        }
    }

    /**
     * 기간 한 점.
     *
     * <p>{@code value}가 {@code null}일 수 있다. 미완료 기간을 0으로 채우지 않는 것이
     * 계약이고, 0으로 채우면 화면이 "그 달에는 아무 일도 없었다"고 말한다.</p>
     *
     * <p>출처 계열마다 값을 싣는 필드가 다르다. 하나의 {@code value}로 모으되 어느 필드를
     * 읽을지는 <b>stream 계약</b>이 정한다. 단위가 다르므로 {@code unit}을 반드시 함께
     * 표시한다.</p>
     */
    public record Point(String period, String status, Integer value, Integer denominator,
            Double ratio, Integer absoluteChange, Double relativeChange) {

        /**
         * 값을 어느 필드에서 읽을지는 계열이 정한다 · 티켓 S15P21E102-348.
         *
         * <p>GitHub 계열은 {@code active_repo_count} — 그 기간에 그 기술이 관측된 저장소
         * 수다. 같은 point 의 {@code event_count} 를 쓰지 않는다: 그것은 기술의 이벤트가
         * 아니라 <b>그 기술을 쓰는 저장소들의 전체 활동 합</b>이라, 한 저장소가 여러 기술을
         * 쓰면 그 활동량이 기술마다 통째로 다시 더해진다(운영 실측 주간 약 3.9배, 월별 약
         * 2.2배). 개요 순위가 저장소 수를 쓰므로(S15P21E102-346) 여기서 이벤트 수를 쓰면
         * 같은 기술·같은 주가 두 화면에서 다른 수로 보인다.</p>
         *
         * <p>{@code value → activeRepoCount → eventCount} 같은 일반 fallback 을 두지
         * 않는다. 그렇게 하면 어떤 payload 가 오느냐에 따라 단위가 조용히 바뀐다.
         * GitHub 계열에 저장소 수가 없으면 값이 없는 것이다 — 운영 point 793건에서 세
         * 필드는 언제나 함께 있거나 함께 없다.</p>
         */
        static Point of(CTrend.Point point, boolean githubTrend) {
            Integer value = githubTrend ? point.activeRepoCount() : point.value();
            Integer denominator = githubTrend ? point.sampleRepoCount() : point.denominator();
            return new Point(point.period(), point.status(), value, denominator,
                    point.ratio(), point.absoluteChange(), point.relativeChange());
        }
    }

    /**
     * 기술 교차 비교 (화면 12).
     *
     * <p>한 응답에 <b>한 출처만</b> 담는다. 여러 출처를 한 표에 섞으면 분모가 다른 값이 한
     * 축에 들어가고, 순위가 의미를 잃는다. 화면은 출처 카드마다 이 API를 따로 부른다.</p>
     */
    public record Compare(String sourceId, String cSource, String unit, List<Row> rows) {
    }

    /**
     * 비교 표의 한 줄.
     *
     * @param value {@code null}이면 그 기술에 아직 데이터가 없다는 뜻이다. 0으로 채우면
     *              "관측했더니 0이었다"가 되어 없는 순위가 생긴다.
     */
    public record Row(String techId, String dataStatus, String statusReason, String period,
            Integer value, Double ratio, Integer absoluteChange, Double relativeChange) {
    }
}
