package com.example.git_job.analysis.controller.dto;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.controller.dto.TechnologyEvidenceResponse.LevelGroup;
import com.example.git_job.analysis.outbox.TechnologyProfileStore.EvidenceLine;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Level → 파일 → 라인으로 접는 규칙을 고정한다.
 *
 * <p>실제 데이터가 이 변환의 이유다. Spring Security 한 기술이 저장소 하나에서
 * 82 건을 내고, 그 중 40 건이 파일 16 개에 흩어진 import 다. 평평하게 두면
 * 화면이 "왜 L2 인가"가 아니라 로그가 된다.</p>
 */
class TechnologyEvidenceResponseTest {

    private static final String REPO = "cseongbo/Tripplannerz";
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";

    private static EvidenceLine line(String ruleType, String ruleName, String path,
            int start, String factType, int totalInLevel) {
        return new EvidenceLine(REPO, SHA, path, start, start, factType,
                "spring-security." + ruleType.toLowerCase() + ".rule", ruleType, ruleName,
                totalInLevel);
    }

    @Test
    @DisplayName("같은 파일의 여러 라인은 한 줄로 접힌다")
    void linesInTheSameFileCollapseIntoOneEntry() {
        // 화면에서 SecurityConfig.java 가 세 번 반복되던 것이 이 변환의 계기다.
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(
                line("L2", "필터 체인 구성", "config/SecurityConfig.java", 10, "IMPORT", 3),
                line("L2", "필터 체인 구성", "config/SecurityConfig.java", 11, "IMPORT", 3),
                line("L2", "필터 체인 구성", "config/SecurityConfig.java", 30, "API_CALL", 3)), 40);

        LevelGroup l2 = response.levels().getFirst();

        assertEquals(1, l2.files().size());
        assertEquals(3, l2.files().getFirst().lines().size());
        assertEquals("config/SecurityConfig.java", l2.files().getFirst().filePath());
    }

    @Test
    @DisplayName("저장소와 파일 경계가 문자열 구분자에 의존하지 않는다")
    void repositoryAndPathAreGroupedBySeparateValues() {
        var first = new EvidenceLine("owner", SHA, "repo\u0000src/App.java", 1, 1,
                "IMPORT", "spring-security.l1.import", "L1", "import", 2);
        var second = new EvidenceLine("owner\u0000repo", SHA, "src/App.java", 2, 2,
                "IMPORT", "spring-security.l1.import", "L1", "import", 2);

        var files = TechnologyEvidenceResponse.of("spring-security", List.of(first, second), 40)
                .levels().getFirst().files();

        assertEquals(2, files.size());
        assertEquals(List.of("owner", "owner\u0000repo"),
                files.stream().map(TechnologyEvidenceResponse.FileGroup::repository).toList());
    }

    @Test
    @DisplayName("Level 은 높은 것이 먼저 온다")
    void levelsAreOrderedHighestFirst() {
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(
                line("L0", "의존성 선언", "build.gradle", 56, "DEPENDENCY", 1),
                line("L2", "필터 체인 구성", "config/SecurityConfig.java", 30, "API_CALL", 1),
                line("L1", "import", "service/LoginService.java", 7, "IMPORT", 1)), 40);

        assertEquals(List.of("L2", "L1", "L0"),
                response.levels().stream().map(LevelGroup::level).toList());
        // 판정은 근거가 있는 Level 중 가장 높은 것이다.
        assertEquals("L2", response.level());
    }

    @Test
    @DisplayName("잘렸으면 잘렸다고 말한다")
    void truncationIsReported() {
        // 감추면 화면이 "근거는 이게 전부"라고 말하게 된다.
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(
                line("L1", "import", "A.java", 1, "IMPORT", 40),
                line("L1", "import", "B.java", 1, "IMPORT", 40)), 2);

        LevelGroup l1 = response.levels().getFirst();

        assertTrue(l1.truncated());
        assertEquals(40, l1.evidenceCount());
        assertEquals(2, l1.shownCount());
    }

    @Test
    @DisplayName("다 담겼으면 잘렸다고 하지 않는다")
    void nothingIsReportedAsTruncatedWhenItFits() {
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(
                line("L1", "import", "A.java", 1, "IMPORT", 1)), 40);

        assertFalse(response.levels().getFirst().truncated());
    }

    @Test
    @DisplayName("한 Level 을 여러 규칙이 냈으면 이름을 모두 보여준다")
    void everyRuleThatProducedTheLevelIsNamed() {
        // "왜 이 Level 인가"의 답이 규칙 이름이다. 하나만 보여주면 나머지 근거가
        // 어디서 왔는지 화면에서 설명되지 않는다.
        var response = TechnologyEvidenceResponse.of("spring-boot", List.of(
                line("L2", "자동 설정 사용", "A.java", 1, "API_CALL", 2),
                line("L2", "액추에이터 노출", "B.java", 1, "API_CALL", 2)), 40);

        assertEquals(List.of("자동 설정 사용", "액추에이터 노출"),
                response.levels().getFirst().rules());
    }

    @Test
    @DisplayName("permalink 는 커밋을 고정한다")
    void thePermalinkPinsTheCommit() {
        // 브랜치로 걸면 그 줄이 밀렸을 때 링크가 엉뚱한 코드를 가리킨다.
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(
                line("L1", "import", "src/App.java", 7, "IMPORT", 1)), 40);

        assertEquals("https://github.com/" + REPO + "/blob/" + SHA + "/src/App.java#L7",
                response.levels().getFirst().files().getFirst().permalink());
    }

    @Test
    @DisplayName("저장소 이름이 없으면 링크를 만들지 않는다")
    void aRowWithoutARepositoryNameHasNoLink() {
        // V13 이전 분석이다. 근거는 남기되 링크는 지어내지 않는다.
        var line = new EvidenceLine(null, SHA, "src/App.java", 7, 7, "IMPORT",
                "spring-security.l1.import", "L1", "import", 1);

        var file = TechnologyEvidenceResponse.of("spring-security", List.of(line), 40)
                .levels().getFirst().files().getFirst();

        assertNull(file.permalink());
        assertNull(file.lines().getFirst().permalink());
    }

    @Test
    @DisplayName("근거가 없으면 판정도 비운다")
    void noEvidenceMeansNoLevel() {
        var response = TechnologyEvidenceResponse.of("spring-security", List.of(), 40);

        assertEquals("INSUFFICIENT_DATA", response.dataStatus());
        assertNull(response.level());
        assertTrue(response.levels().isEmpty());
    }
}
