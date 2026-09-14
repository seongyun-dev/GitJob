package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.query.TechnologyProfileStore.AnalyzedRepository;
import com.example.git_job.analysis.query.TechnologyProfileStore.ProfileSummary;
import com.example.git_job.analysis.query.TechnologyProfileStore.TechnologyVerdict;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * "내 GitHub 에서 확인된 기술" 화면 한 장.
 *
 * <p>지표·기술 목록·판정에 쓰인 저장소를 한 번에 내려준다. 셋이 같은 집합(저장소별
 * 최신 성공 분석)에서 나오므로 따로 부르면 그 사이 분석이 끝났을 때 서로 어긋난
 * 화면이 된다.</p>
 *
 * <p>{@code dataStatus} 는 오류가 아니라 상태다. 분석한 적이 없는 것과 분석했는데
 * 아는 기술이 없었던 것은 다르며, 화면은 그 둘에 다른 말을 해야 한다.</p>
 */
public record TechnologyProfileResponse(
        String dataStatus,
        Summary summary,
        List<Technology> technologies,
        List<Repository> repositories
) {

    /** FE {@code DATA_STATUSES} 와 같은 값이다. */
    private static final String READY = "READY";
    private static final String NO_DATA = "NO_DATA";
    private static final String INSUFFICIENT_DATA = "INSUFFICIENT_DATA";

    public static TechnologyProfileResponse of(ProfileSummary summary,
            List<TechnologyVerdict> verdicts, List<AnalyzedRepository> repositories,
            Map<String, String> personalLevels) {
        return new TechnologyProfileResponse(
                status(verdicts, repositories),
                new Summary(summary.technologyCount(), summary.advancedCount(),
                        summary.repositoryCount(), summary.analyzedAt()),
                verdicts.stream()
                        .map(verdict -> Technology.from(verdict,
                                personalLevels.get(verdict.techId())))
                        .toList(),
                repositories.stream().map(Repository::from).toList());
    }

    private static String status(List<TechnologyVerdict> verdicts,
            List<AnalyzedRepository> repositories) {
        if (repositories.isEmpty()) {
            return NO_DATA;
        }
        // 분석은 했는데 아는 기술이 하나도 안 나온 경우다. 레지스트리가 모르는
        // 스택일 수도 있으므로 "없다"가 아니라 "판정할 근거가 부족하다"로 말한다.
        return verdicts.isEmpty() ? INSUFFICIENT_DATA : READY;
    }

    public record Summary(int technologyCount, int advancedCount, int repositoryCount,
            Instant analyzedAt) {
    }

    /**
     * 기술 한 줄.
     *
     * <p>{@code personalLevel} 은 본인이 쓴 근거만으로 같은 규칙을 다시 판정한
     * 결과다. 기여 판정이 아직 없는 기술은 {@code null} 인데, 그것은 "본인이 안
     * 썼다"가 아니라 "확인되지 않았다"는 뜻이다 -- 화면이 그 둘을 구분해야 한다.
     * Repository Level 을 대신 채우면 화면이 "본인이 썼다"고 말하게 된다.</p>
     */
    public record Technology(
            String techId,
            String displayName,
            String personalLevel,
            String repositoryLevel,
            int evidenceCount,
            int repositoryCount,
            String registryVersion
    ) {
        public static Technology from(TechnologyVerdict verdict, String personalLevel) {
            return new Technology(verdict.techId(), verdict.displayName(), personalLevel,
                    verdict.repositoryLevel(), verdict.evidenceCount(),
                    verdict.repositoryCount(), verdict.registryVersion());
        }
    }

    /** 판정에 쓰인 저장소. 근거 0건도 포함한다. */
    public record Repository(String repositoryId, String fullName, String commitSha,
            Instant analyzedAt, int evidenceCount) {
        public static Repository from(AnalyzedRepository row) {
            return new Repository(row.repositoryId(), row.repositoryFullName(),
                    row.commitSha(), row.completedAt(), row.evidenceCount());
        }
    }
}
