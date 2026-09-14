package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.query.TechnologyProfileStore.EvidenceLine;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 한 기술을 무엇으로 판정했는지, Level 로 묶어서.
 *
 * <h2>왜 평평한 목록이 아닌가</h2>
 *
 * <p>Spring Security 한 기술이 저장소 하나에서 82 건을 낸다. 그대로 나열하면
 * 같은 파일의 연속된 import 세 줄이 세 행을 차지하고, 화면은 "왜 L2 인가"가
 * 아니라 로그가 된다. 사람이 답을 얻으려면 <b>Level → 파일 → 라인</b> 순으로
 * 좁혀 들어가야 한다.</p>
 *
 * <h2>Level 마다 따로 자른다</h2>
 *
 * <p>{@code truncated} 는 그 Level 이 상한에 걸렸다는 뜻이다. 잘렸다는 사실을
 * 감추면 화면이 "근거는 이게 전부"라고 말하게 된다.</p>
 */
public record TechnologyEvidenceResponse(
        String techId,
        String dataStatus,
        /** 이 기술의 판정. 근거가 있는 Level 중 가장 높은 것이다. */
        String level,
        List<LevelGroup> levels
) {

    private static final String READY = "READY";

    /** 레지스트리에는 있는 기술인데 이 사람의 저장소에서는 안 나온 경우다. */
    private static final String INSUFFICIENT_DATA = "INSUFFICIENT_DATA";

    public static TechnologyEvidenceResponse of(String techId, List<EvidenceLine> lines,
            int perLevelLimit) {
        List<LevelGroup> levels = group(lines, perLevelLimit);
        return new TechnologyEvidenceResponse(
                techId,
                levels.isEmpty() ? INSUFFICIENT_DATA : READY,
                levels.isEmpty() ? null : levels.getFirst().level(),
                levels);
    }

    /**
     * Level → 파일 → 라인.
     *
     * <p>{@link LinkedHashMap} 인 것은 스토어가 이미 정렬해서 주기 때문이다
     * (Level 내림차순, 파일명, 라인). 여기서 다시 정렬하면 두 곳이 순서를 정하게
     * 되고, 한쪽만 바뀌었을 때 어긋난다.</p>
     */
    private static List<LevelGroup> group(List<EvidenceLine> lines, int perLevelLimit) {
        Map<String, List<EvidenceLine>> byLevel = new LinkedHashMap<>();
        for (EvidenceLine line : lines) {
            byLevel.computeIfAbsent(line.ruleType(), key -> new ArrayList<>()).add(line);
        }

        List<LevelGroup> groups = new ArrayList<>();
        byLevel.forEach((level, rows) -> {
            int total = rows.getFirst().totalInLevel();
            groups.add(new LevelGroup(
                    level,
                    total,
                    rows.size(),
                    total > rows.size(),
                    // 같은 Level 을 여러 규칙이 낼 수 있다. 어떤 규칙이 충족됐는지가
                    // 곧 "왜 이 Level 인가"의 답이라 이름을 그대로 보여준다.
                    rows.stream().map(EvidenceLine::ruleName).distinct().toList(),
                    files(rows)));
        });
        groups.sort(Comparator.comparing(LevelGroup::level).reversed());
        return groups;
    }

    private static List<FileGroup> files(List<EvidenceLine> rows) {
        Map<FileKey, List<EvidenceLine>> byFile = new LinkedHashMap<>();
        for (EvidenceLine line : rows) {
            byFile.computeIfAbsent(
                    new FileKey(line.repositoryFullName(), line.filePath()),
                    key -> new ArrayList<>()).add(line);
        }
        return byFile.values().stream().map(FileGroup::from).toList();
    }

    /**
     * 한 파일을 가리키는 키.
     *
     * <p>문자열을 이어 붙여 키를 만들지 않는다. 구분자를 골라야 하고, 그 구분자가
     * 경로에 나타날 수 있으며, 소스에 눈에 안 보이는 문자를 넣게 된다 -- 실제로
     * 이 자리에 NUL 바이트가 박혀 파일 전체가 바이너리로 취급된 적이 있다.
     * 레코드를 쓰면 그 선택 자체가 없어진다.</p>
     *
     * <p>{@code repository} 는 null 일 수 있다. V13 이전 분석이 그렇고, 레코드의
     * equals/hashCode 가 null 을 그대로 다룬다.</p>
     */
    private record FileKey(String repository, String filePath) {
    }

    /** 한 파일에서 나온 근거. 라인 목록으로 접힌다. */
    public record FileGroup(String repository, String filePath, String permalink,
            List<Line> lines) {

        static FileGroup from(List<EvidenceLine> rows) {
            EvidenceLine first = rows.getFirst();
            return new FileGroup(
                    first.repositoryFullName(),
                    first.filePath(),
                    permalink(first),
                    rows.stream().map(Line::from).toList());
        }

        /**
         * 커밋을 고정한 GitHub 링크.
         *
         * <p>브랜치가 아니라 SHA 를 쓴다. 브랜치로 걸면 그 줄이 나중에 밀리거나
         * 지워졌을 때 링크가 엉뚱한 코드를 가리키고, 근거가 조용히 거짓이 된다.</p>
         *
         * <p>저장소 이름이 없으면 만들지 않는다. V13 이전 분석이 그렇다.</p>
         */
        static String permalink(EvidenceLine line) {
            if (line.repositoryFullName() == null || line.commitSha() == null) {
                return null;
            }
            String fragment = line.startLine() == line.endLine()
                    ? "#L" + line.startLine()
                    : "#L" + line.startLine() + "-L" + line.endLine();
            return "https://github.com/" + line.repositoryFullName()
                    + "/blob/" + line.commitSha() + "/" + line.filePath() + fragment;
        }
    }

    public record Line(int startLine, int endLine, String factType, String ruleId,
            String permalink) {
        static Line from(EvidenceLine line) {
            return new Line(line.startLine(), line.endLine(), line.factType(), line.ruleId(),
                    FileGroup.permalink(line));
        }
    }

    /**
     * 한 Level 의 근거 묶음.
     *
     * @param evidenceCount 잘리기 전 전체 건수
     * @param shownCount    실제로 내려보낸 건수
     * @param truncated     상한에 걸려 잘렸는지
     * @param rules         이 Level 에서 충족된 규칙 이름
     */
    public record LevelGroup(String level, int evidenceCount, int shownCount, boolean truncated,
            List<String> rules, List<FileGroup> files) {
    }
}
