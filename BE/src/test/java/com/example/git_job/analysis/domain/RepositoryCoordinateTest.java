package com.example.git_job.analysis.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** These values become GitHub URL path segments, so the format check is a security boundary. */
class RepositoryCoordinateTest {

    @Test
    void splitsOwnerAndRepositoryAndKeepsSlashesInsideBranchNames() {
        var coordinate = RepositoryCoordinate.of("octocat/git-job.api", "feature/cdc");

        assertEquals("octocat", coordinate.owner());
        assertEquals("git-job.api", coordinate.repository());
        assertEquals("feature/cdc", coordinate.branch());
        assertEquals("octocat/git-job.api", coordinate.fullName());
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "../../user/repos",   // 다른 엔드포인트로 빠져나가려는 시도
            "octocat",            // 슬래시 없음
            "octocat/a/b",        // 슬래시 둘
            "/octocat/repo",      // 빈 owner
            "octocat/",           // 빈 repository
            "oct at/repo",        // 공백
            "octocat/re po",
    })
    @DisplayName("owner/repo 형식이 어긋나면 GitHub을 호출하기 전에 거절한다")
    void rejectsMalformedFullNames(String fullName) {
        var failure = assertThrows(CustomException.class,
                () -> RepositoryCoordinate.of(fullName, "main"));
        assertEquals(ErrorCode.INVALID_REQUEST_BODY, failure.getErrorCode());
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "../main",            // 경로 탈출
            "feature/../../x",
            "/main",              // 슬래시로 시작
            "main/",              // 슬래시로 끝
            "ma in",              // Git이 금지하는 문자들
            "main~1",
            "main^",
            "refs:main",
            "main?x=1",
            "main#fragment",
            "main*",
            "-main",
            "",
    })
    @DisplayName("Git이 허용하지 않거나 URL을 벗어나는 브랜치 이름을 거절한다")
    void rejectsUnsafeBranchNames(String branch) {
        var failure = assertThrows(CustomException.class,
                () -> RepositoryCoordinate.of("octocat/repo", branch));
        assertEquals(ErrorCode.INVALID_REQUEST_BODY, failure.getErrorCode());
    }

    @Test
    void rejectsControlCharactersInBranchNames() {
        var failure = assertThrows(CustomException.class,
                () -> RepositoryCoordinate.of("octocat/repo", "main\nHost: evil"));
        assertEquals(ErrorCode.INVALID_REQUEST_BODY, failure.getErrorCode());
    }

    @Test
    void rejectsNullFullName() {
        assertThrows(CustomException.class, () -> RepositoryCoordinate.of(null, "main"));
    }
}
