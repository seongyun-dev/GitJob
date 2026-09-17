package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;

/**
 * A declared dependency that matched no registry technology, observed once in
 * one repository.
 *
 * <p>Dependencies only. An import path has no reliable package boundary in Java
 * or C# -- org.springframework.web and org.springframework.data.redis sit at
 * different depths, so no fixed truncation is correct -- while a manifest entry
 * is already the unit an administrator would promote.</p>
 *
 * <p>occurrenceCount counts declarations inside this one repository, for example
 * one per module of a multi-module build. Ranking for the admin screen uses
 * distinct users instead: the question is how many people a technology would
 * serve, not how many lines mention it.</p>
 */
public record TechnologyCandidate(
        @JsonProperty("ecosystem") Ecosystem ecosystem,
        @JsonProperty("coordinate") String coordinate,
        @JsonProperty("scope") String scope,
        @JsonProperty("occurrence_count") int occurrenceCount
) {

    /**
     * 워커가 의존성 선언을 읽어 낼 수 있는 생태계.
     *
     * <p>{@code GO}·{@code CARGO}·{@code COMPOSER} 는
     * {@code repository-analysis-result/v2} 부터 계약에 있었지만 여기에는 없었다. 이
     * enum 은 Jackson 이 읽는 자리라, 모르는 값 하나가 후보 하나를 버리는 것이 아니라
     * <b>결과 이벤트 전체</b>를 역직렬화 실패로 만든다 -- Go·Rust·PHP 저장소를 분석한
     * 사용자는 판정과 근거까지 통째로 잃고 QUEUED 에 남는다.</p>
     *
     * <p>목록을 늘릴 때는 {@code CK_TECHNOLOGY_CANDIDATE_ECOSYSTEM} 도 함께 늘려야
     * 한다. DB 에 같은 제약이 하나 더 있어서, 여기만 고치면 실패 지점이 역직렬화에서
     * 트랜잭션으로 옮겨갈 뿐이다.</p>
     */
    public enum Ecosystem { MAVEN, NPM, PYPI, NUGET, GO, CARGO, COMPOSER }

    public TechnologyCandidate {
        ecosystem = Objects.requireNonNull(ecosystem, "ecosystem must not be null");
        if (coordinate == null || coordinate.isBlank()) {
            throw new IllegalArgumentException("coordinate must be non-blank");
        }
        if (occurrenceCount < 1) {
            throw new IllegalArgumentException("occurrenceCount must be at least 1");
        }
    }
}
