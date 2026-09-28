package com.example.git_job.analysis.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 브랜치 목록·단건 조회 공통 응답. 단건 조회는 필드가 훨씬 많지만
 * 우리에게 필요한 것은 이름과 tip commit SHA뿐이다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubBranchResponse(
        String name,
        Commit commit,
        // 'protected'는 Java 예약어라 필드명을 바꾸고 JSON 이름을 명시한다.
        @JsonProperty("protected") Boolean isProtected
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Commit(String sha) {
    }

    /** 요청 시점의 tip commit. 분석은 브랜치가 아니라 이 SHA에 고정된다. */
    public String commitSha() {
        return commit == null ? null : commit.sha();
    }
}
