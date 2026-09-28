package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * What the run saw. Operational rather than user facing: a sudden drop in
 * filesParsed across analyses means an extractor broke, and without these
 * numbers that looks the same as repositories getting simpler.
 *
 * <h2>왜 전부 박스 타입인가</h2>
 *
 * <p>계약에서 이 블록의 숫자는 <b>하나도 필수가 아니다</b>. v1 스키마의
 * {@code AnalysisStats} 에는 {@code required} 가 없고, v2·v3 는 모든 항목에 기본값을
 * 달아 두었다({@code AI/analysis/results.py}). 즉 어느 항목이든 빠진 채로 도착할 수
 * 있다.</p>
 *
 * <p>여기가 {@code int} 였을 때 실제로 무슨 일이 일어났는지가 이 주석의 이유다.
 * {@code syntax_node_count} 는 v3 부터 생긴 필드인데 primitive 로 선언돼 있었고,
 * Jackson 3 는 빠진 값을 primitive 에 넣지 못해 <b>이벤트 전체를 거절</b>했다. 읽는
 * 곳이 한 군데도 없는 숫자 하나 때문에 저장소 분석 결과 전체가 버려졌고, 분석은
 * QUEUED 에 남았다.</p>
 *
 * <p>그래서 계약이 "선택"이라고 말하는 것은 타입도 선택으로 둔다. {@code null} 은
 * 0 이 아니라 <b>보고받지 못했다</b>는 뜻이다. 판정에 쓰는 값이 아니므로 그 구분이
 * 손해를 주지 않고, 새 계약이 숫자를 하나 더 늘려도 여기서 막히지 않는다.</p>
 *
 * <p>반대로 {@link EvidenceItem} 의 줄 번호나 {@link TechnologyCandidate} 의 출현
 * 횟수는 계약이 필수로 두고 실제로 읽는 값이라 primitive 로 남는다 -- 그쪽은 빠지면
 * 거절되는 것이 맞다.</p>
 */
public record AnalysisStats(
        @JsonProperty("files_parsed") Integer filesParsed,
        @JsonProperty("files_skipped") Integer filesSkipped,
        @JsonProperty("import_count") Integer importCount,
        @JsonProperty("dependency_count") Integer dependencyCount,
        @JsonProperty("bytes_on_disk") Long bytesOnDisk,
        @JsonProperty("duration_ms") Long durationMs,
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
        /**
         * v3 의 구조 근거 노드 수.
         *
         * <p>{@code null} 이면 보고받지 못한 것이다 -- v1·v2 계약에는 이 필드가
         * 아예 없다. 0 으로 채우지 않는 이유는 {@code skippedReasons} 와 같다:
         * "구조 근거를 0개 봤다"와 "구조 근거를 셀 수 없는 계약이었다"는 다른
         * 사실이고, 합쳐 놓으면 v3 로 넘어갔는지 되짚을 방법이 없어진다.</p>
         */
        @JsonProperty("syntax_node_count") Integer syntaxNodeCount
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
     * 구조 근거 노드 수를 받았는지.
     *
     * <p>거짓이면 v1·v2 계약으로 판정된 분석이다. 거절하지 않고 기록만 하는 이유는
     * 이 값을 아무도 읽지 않기 때문이다 -- 읽지 않는 값을 필수로 만들면 결과 전체가
     * 버려지고, 그것이 이 필드가 처음 일으킨 장애다.</p>
     */
    public boolean reportedSyntaxNodes() {
        return syntaxNodeCount != null;
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
