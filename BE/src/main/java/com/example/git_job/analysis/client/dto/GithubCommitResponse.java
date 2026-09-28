package com.example.git_job.analysis.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.time.OffsetDateTime;

/**
 * {@code GET /repos/{owner}/{repo}/commits/{sha}} 중 기여 판정에 쓰는 부분.
 *
 * <h2>{@code author}가 두 군데 있다</h2>
 *
 * <p>최상위 {@code author}는 <b>GitHub 계정</b>이고, {@code commit.author}는 git
 * 객체에 박힌 <b>이름과 이메일</b>이다. 둘은 다르다 -- GitHub이 커밋의 이메일을
 * 등록된 계정과 맞춰 본 결과가 전자이고, 맞출 수 없으면 {@code null}이다.</p>
 *
 * <p>우리가 쓰는 것은 전자다. 이메일을 직접 비교하면 사용자의 주소 목록이 필요한데
 * 지금 scope로는 받을 수 없고({@code user:email} 없음), 받더라도 남의 이메일까지
 * 다루게 된다. GitHub이 이미 아는 답을 물어보는 편이 정확하고 안전하다.</p>
 *
 * <p>{@code author}가 {@code null}인 커밋은 "본인이 아니다"가 아니라 "알 수 없다"로
 * 다뤄야 한다. 계정에 등록하지 않은 이메일로 커밋하면 본인 코드여도 여기가 비고,
 * 그때는 기여가 <b>과소평가</b>된다. 없는 기여를 주장하는 것보다 낫다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubCommitResponse(
        String sha,
        Author author,
        Commit commit
) {

    /** 커밋에 연결된 GitHub 계정. 연결되지 않았으면 이 객체 자체가 없다. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Author(Long id, String login) {
    }

    /** git 객체의 내용. 작성 시각은 사용 기간 계산에 쓴다. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Commit(GitIdentity author, String message) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record GitIdentity(String name, String email, OffsetDateTime date) {
    }

    /** 연결된 계정의 GitHub 숫자 id. 연결이 없으면 {@code null}. */
    public Long githubUserId() {
        return author == null ? null : author.id();
    }

    public String githubLogin() {
        return author == null ? null : author.login();
    }

    public String authorName() {
        return commit == null || commit.author() == null ? null : commit.author().name();
    }

    public OffsetDateTime authoredAt() {
        return commit == null || commit.author() == null ? null : commit.author().date();
    }
}
