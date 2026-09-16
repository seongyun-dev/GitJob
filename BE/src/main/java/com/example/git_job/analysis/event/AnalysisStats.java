package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * What the run saw. Operational rather than user facing: a sudden drop in
 * filesParsed across analyses means an extractor broke, and without these
 * numbers that looks the same as repositories getting simpler.
 */
public record AnalysisStats(
        @JsonProperty("files_parsed") int filesParsed,
        @JsonProperty("files_skipped") int filesSkipped,
        @JsonProperty("import_count") int importCount,
        @JsonProperty("dependency_count") int dependencyCount,
        @JsonProperty("bytes_on_disk") long bytesOnDisk,
        @JsonProperty("duration_ms") long durationMs,
        /**
         * 사유별 건너뛴 파일 수. {@code repository-analysis-result/v2} 부터 실린다.
         *
         * <p>운영 지표가 아니라 <b>판정 입력</b>이다. 파일을 건너뛴 분석은 저장소
         * 전체를 본 것이 아니므로 {@code coverage_complete} 를 참으로 만들 수 없다.
         * 비어 있으면 건너뛴 것이 없다는 뜻이고, v1 결과에는 이 필드가 없어 역시
         * 비어 있다 -- 그때는 "건너뛰지 않았다"가 아니라 "모른다"이므로 호출부가
         * 계약 버전을 함께 본다.</p>
         */
        @JsonProperty("skipped_reasons") Map<String, Integer> skippedReasons,
        /** v3 의 구조 근거 노드 수. 없으면 0이다. */
        @JsonProperty("syntax_node_count") int syntaxNodeCount
) {

    public AnalysisStats {
        // null 을 빈 Map 으로 바꾸지 않는다. v1 결과에는 이 필드가 아예 없고, 그것은
        // "건너뛴 것이 없다"가 아니라 "모른다"이다. 바꿔 버리면 두 상태가 같아지고
        // coverage_complete 를 잘못 참으로 만든다.
        skippedReasons = skippedReasons == null ? null : Map.copyOf(skippedReasons);
    }

    /** 건너뛴 사유를 받았는지. 받지 못한 계약(v1)과 받았는데 0건인 것을 구분한다. */
    public boolean reportedSkips() {
        return skippedReasons != null;
    }

    /**
     * 건너뛴 파일이 하나라도 있었는지.
     *
     * <p>받지 못했으면 참으로 본다 -- 모르는 것을 "없었다"로 읽으면 저장소 전체를 본
     * 적 없는 분석이 완전 판정으로 나간다.</p>
     */
    public boolean skippedAnything() {
        if (skippedReasons == null) {
            return true;
        }
        return skippedReasons.values().stream().anyMatch(count -> count != null && count > 0);
    }
}
