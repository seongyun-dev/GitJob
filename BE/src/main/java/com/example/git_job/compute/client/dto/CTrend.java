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
     * GitHub Trend 계열 stream인지 (S15P21E102-348).
     *
     * <p>여기서 갈리는 것은 <b>값을 어느 필드에서 읽는가</b>다. GitHub 계열 payload는
     * {@code value}가 비어 있고 저장소 수({@code active_repo_count})와 이벤트 합
     * ({@code event_count})을 따로 싣는다. JOB은 {@code value}를 쓴다.</p>
     *
     * <p>판정 기준을 payload의 {@code source}(운영에서 {@code GITHUB_GH_ARCHIVE})가 아니라
     * <b>selector source</b>로 두는 이유는, 그것이 우리가 무엇을 물었는지를 말하는 계약
     * 값이기 때문이다. payload의 source는 저장한 쪽이 붙인 이름이고 두 namespace는 다르다
     * — 주간 head도 payload에는 {@code GITHUB_GH_ARCHIVE}로 적힌다.</p>
     */
    public static boolean isGithubTrend(String cSource) {
        return "WEEKLY_REPO_ACTIVITY".equals(cSource)
                || "GH_ARCHIVE".equals(cSource)
                || "GH_ARCHIVE_HISTORICAL".equals(cSource);
    }

    /** GitHub Trend 값의 단위. Ranking API와 같은 토큰이라 화면이 같은 말로 읽는다. */
    public static final String GITHUB_TREND_UNIT = "REPOSITORIES";

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

    public record BatchRequest(List<Selector> selectors) {
        public BatchRequest {
            selectors = List.copyOf(selectors);
        }
    }

    public record Batch(List<BatchItem> items) {
        public Batch {
            items = items == null ? List.of() : List.copyOf(items);
        }
    }

    public record BatchItem(String techId, String status, String code, Snapshot snapshot) {
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
     * @param eventCount GH Archive 가 싣는 이벤트 합. <b>화면에 값으로 내보내지 않는다</b>
     *                   (S15P21E102-348) — 기술의 이벤트가 아니라 그 기술을 쓰는 저장소들의
     *                   전체 활동 합이라 기술마다 중복 계산된다. 계약을 보이기 위해 남긴다.
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
            /** GitHub 계열의 값: 그 기간에 그 기술이 관측된 저장소 수. */
            Integer activeRepoCount,
            /** {@code activeRepoCount}의 분모. 주차마다 코호트 크기가 다르다. */
            Integer sampleRepoCount,
            List<String> reasons
    ) {
    }
}
