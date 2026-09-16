package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * 공용 Trend의 resolve 요청·응답과 Snapshot payload (S15P21E102-279).
 *
 * <p>{@code trends/resolve}는 저장할 때 쓴 stream identity를 그대로 계산해 완료 head를
 * 찾는다. 계산을 새로 만들지 않는 순수 조회이고, 일치하는 head가 없으면 404
 * {@code TREND_NOT_PREPARED}다. 그 404는 오류가 아니라 "그 출처에 아직 데이터가 없다"이며
 * 화면은 해당 출처 카드만 비운다.</p>
 *
 * <p>네 source는 서로 다른 series다. 같은 기술이라도 목표 직무별 채용 수요·주간 누적·
 * 현재 Evidence Archive·역사 commit Archive는 분모와 세는 대상이 다르므로 한 축에
 * 겹쳐 그리지 않는다.</p>
 */
public final class CTrend {

    private CTrend() {
    }

    /**
     * resolve 요청.
     *
     * @param periods      {@code WEEKLY_REPO_ACTIVITY}는 받지 않는다(주차를 누적하는 head다).
     *                     JOB·Archive 계열은 명시한 기간만 받는다.
     * @param granularity  JOB·Archive 계열에만 쓴다.
     */
    public record Selector(String source, String techId, List<String> periods,
            String granularity, boolean includePartial, String targetRole,
            List<String> sources, List<String> regions, List<String> careerLevels,
            Integer minJobs) {

        /** 주간 누적. 기간을 보내면 C가 422로 거절한다. */
        public static Selector weekly(String techId) {
            return new Selector("WEEKLY_REPO_ACTIVITY", techId, List.of(), null, false,
                    null, null, List.of(), List.of(), null);
        }

        /** 고정 월별 역사 Archive. 미완료 월을 넣으면 그 월이 head에서 빠진다. */
        public static Selector historical(String techId, List<String> months) {
            return new Selector("GH_ARCHIVE_HISTORICAL", techId, List.copyOf(months),
                    "MONTH", false, null, null, List.of(), List.of(), null);
        }

        /** 목표 직무와 동일한 필터의 월별 채용 수요. */
        public static Selector job(String techId, List<String> months, String targetRole,
                                   List<String> regions, List<String> careerLevels) {
            return new Selector("JOB", techId, List.copyOf(months), "MONTH", false,
                    targetRole, List.of(), List.copyOf(regions), List.copyOf(careerLevels), 1);
        }
    }

    /** resolve 응답. 수치는 없고 {@code snapshotId}로 다시 조회한다. */
    public record Resolved(
            String snapshotId,
            String schemaVersion,
            String status,
            String registryVersion,
            String algorithmVersion,
            String granularity,
            List<String> periods,
            boolean includePartial
    ) {
    }

    /**
     * Trend Snapshot 하나.
     *
     * <p>payload의 모양이 source마다 다르다. 공고·GitHub 공통 형식은
     * {@code c-source-trend/v1}이고 Archive는 {@code c-gharchive-trend/v1}인데, 후자는
     * {@code value} 대신 {@code event_count}를 센다. 두 값을 같은 필드로 받으면 단위가
     * 다른 수치가 한 축에 섞인다.</p>
     */
    public record Snapshot(String snapshotId, String kind, Payload payload) {
    }

    public record Payload(
            String schemaVersion,
            String source,
            String techId,
            String metric,
            String unit,
            String granularity,
            /** {@code READY} · {@code PREPARING} · {@code INSUFFICIENT_DATA} · {@code NOT_SUPPORTED} · {@code FAILED}. */
            String status,
            List<String> reasons,
            List<Point> points
    ) {
    }

    /**
     * 기간 한 점.
     *
     * <p>모든 수치가 {@code null}일 수 있다. 미완료 기간을 0으로 채우지 않는 것이 계약이라,
     * 값이 없는 점은 값이 없는 채로 화면까지 간다.</p>
     *
     * @param value      {@code c-source-trend/v1}의 값
     * @param eventCount {@code c-gharchive-trend/v1}의 값. 단위가 다르므로 별도 필드다.
     */
    public record Point(
            String period,
            String status,
            Integer value,
            Integer denominator,
            Double ratio,
            Integer absoluteChange,
            Double relativeChange,
            Integer eventCount,
            Integer activeRepoCount,
            List<String> reasons
    ) {
    }
}
