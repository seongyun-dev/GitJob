package com.example.git_job.analysis.service;

import com.example.git_job.analysis.outbox.TechnologyProfileStore;
import com.example.git_job.analysis.outbox.TechnologyProfileStore.EvidenceLine;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 분석 결과를 읽는 쪽.
 *
 * <p>지금까지의 코드는 전부 쓰기 경로였다 -- 요청을 받아 판정해서 저장하는 데까지.
 * 이 서비스가 그것을 화면으로 되돌린다.</p>
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class TechnologyProfileService {

    /**
     * Level 하나가 내려보낼 근거의 상한.
     *
     * <p>전체가 아니라 Level 마다다. 전체에 걸면 L2 가 상한을 채우는 순간 L0 와
     * L1 이 통째로 사라지고, 화면은 "의존성 선언이 없다"로 읽힌다.</p>
     *
     * <p>파일 단위로 접히므로 40 이면 화면에서는 그보다 훨씬 적은 줄이 된다.
     * 잘린 경우 응답이 {@code truncated} 로 그 사실을 함께 알린다.</p>
     */
    public static final int EVIDENCE_PER_LEVEL = 40;

    private final TechnologyProfileStore profiles;

    /** 화면 한 장에 필요한 것 전부. 지표·기술·저장소가 같은 집합에서 나온다. */
    public Profile profile(long userId) {
        return new Profile(
                profiles.summary(userId),
                profiles.verdicts(userId),
                profiles.repositories(userId));
    }

    /**
     * 한 기술의 근거.
     *
     * <p>레지스트리에 없는 기술이면 404 다. 근거가 0건인 것과 구분해야 한다 --
     * 오타 난 URL 과 "아직 안 나온 기술"은 화면이 다르게 말해야 하고, 후자는 오류가
     * 아니라 정상적인 빈 결과다.</p>
     */
    public List<EvidenceLine> evidence(long userId, String techId) {
        if (!profiles.isKnownTechnology(techId)) {
            throw new CustomException(ErrorCode.TECHNOLOGY_NOT_IN_REGISTRY);
        }
        return profiles.evidence(userId, techId, EVIDENCE_PER_LEVEL);
    }

    public record Profile(
            TechnologyProfileStore.ProfileSummary summary,
            List<TechnologyProfileStore.TechnologyVerdict> technologies,
            List<TechnologyProfileStore.AnalyzedRepository> repositories
    ) {
    }
}
