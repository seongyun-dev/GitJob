package com.example.git_job.analysis.summary;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.analysis.query.TechnologyProfileStore.TechnologyVerdict;
import com.example.git_job.analysis.query.TechnologySummaryFactStore;
import com.example.git_job.analysis.query.TechnologySummaryFactStore.LevelRules;
import com.example.git_job.analysis.query.TechnologySummaryFactStore.MissingClauses;
import com.example.git_job.analysis.query.TechnologySummaryFactStore.Span;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 한 사용자의 한 기술을 요약해 달라고 보낼 입력을 만든다.
 *
 * <h2>이 클래스가 요약을 만들지는 않는다</h2>
 *
 * <p>여기서 끝나는 것은 "무엇을 근거로 말할 수 있는가"까지다. 수준은 이미 규칙이
 * 정했고, 문장은 LLM 이 쓴다. 셋을 한 곳에 두지 않는 이유는 틀렸을 때 어디를 봐야
 * 하는지가 달라지기 때문이다.</p>
 *
 * <h2>없는 것을 지어내지 않는다</h2>
 *
 * <p>{@code next_level} 도 {@code period} 도 {@code null} 일 수 있다. 채워야 할 것
 * 같아 보여도 비워 둔다 -- 기간을 모르는데 저장소의 첫 커밋으로 채우면 합류하기
 * 전의 남의 작업이 본인 기간이 되고, 그 거짓은 카드에서 드러나지 않는다.</p>
 */
@Component
@RequiredArgsConstructor
public class FactPackBuilder {

    private static final List<String> LEVELS = List.of("L0", "L1", "L2", "L3");

    private final TechnologyProfileStore profiles;
    private final TechnologySummaryFactStore facts;
    private final HighlightSelector highlights;

    /**
     * @return 이 사용자에게 그 기술의 판정이 없으면 비어 있다. 오류가 아니라
     *         분석하지 않았거나 근거가 없는 상태다
     */
    @Transactional(readOnly = true)
    public Optional<FactPack> build(long userId, String techId) {
        // 기술 하나만 묻는다. 전체를 집계한 뒤 고르면 카드 열두 장에 전체 집계가
        // 열두 번 돌고, 저장된 요약을 쓰는 경우에도 지문 때문에 그대로 반복된다.
        Optional<TechnologyVerdict> verdict = profiles.verdict(userId, techId);
        if (verdict.isEmpty()) {
            return Optional.empty();
        }
        TechnologyVerdict tech = verdict.get();
        String personalLevel = profiles.personalLevel(userId, techId)
                // 기여 판정이 아직 없으면 "본인이 쓴 것으로 확인된 범위"가 없다.
                // L0 은 "선언은 했다"는 주장이라 여기 쓸 수 없고, 계약은 값을
                // 요구하므로 가장 낮은 단계로 보낸 뒤 authorship 이 그것이
                // 미확인임을 말하게 한다.
                .orElse("L0");

        return Optional.of(new FactPack(
                FactPack.SCHEMA_VERSION,
                FactPack.LOCALE,
                new FactPack.Technology(tech.techId(), tech.displayName(),
                        tech.repositoryLevel(), personalLevel, tech.registryVersion()),
                facts.authorship(userId, techId),
                levels(userId, techId),
                nextLevel(userId, techId, tech.registryVersion(), personalLevel).orElse(null),
                highlights.select(facts.facts(userId, techId)),
                repositories(userId, techId),
                period(userId, techId).orElse(null)));
    }

    private List<FactPack.LevelEvidence> levels(long userId, String techId) {
        return facts.levels(userId, techId).stream()
                .map(row -> new FactPack.LevelEvidence(row.level(), row.ruleNames(), row.mine()))
                .toList();
    }

    /**
     * 바로 위 Level 하나만 본다.
     *
     * <p>두 단계 위를 가리키면 "지금 할 수 있는 다음 일"이 아니라 먼 목표가 되고,
     * 카드 한 줄이 감당할 조언이 아니다. 규칙이 없는 Level 은 건너뛰지 않고 거기서
     * 멈춘다 -- 기술 29개 중 L3 규칙을 가진 것은 둘뿐이라, 건너뛰면 대부분의
     * 기술이 도달할 수 없는 목표를 달게 된다.</p>
     */
    private Optional<FactPack.NextLevel> nextLevel(long userId, String techId,
            String registryVersion, String personalLevel) {
        int current = LEVELS.indexOf(personalLevel);
        if (current < 0 || current + 1 >= LEVELS.size()) {
            return Optional.empty();
        }
        String next = LEVELS.get(current + 1);
        return facts.missingForLevel(userId, techId, registryVersion, next)
                .map(missing -> new FactPack.NextLevel(next, missing.ruleName(),
                        capped(missing.missing())));
    }

    /**
     * 기대값 목록의 상한.
     *
     * <p>한 절이 메서드 이름 다섯 개를 OR 로 묶는 일이 흔하다. 전부 보내면 요약이
     * 그것을 나열하다 200자를 넘겨 버려진다. 앞의 것이 규칙에 적힌 순서대로라
     * 대표성이 있다.</p>
     */
    private static List<String> capped(List<String> missing) {
        return missing.size() <= 4 ? missing : missing.subList(0, 4);
    }

    private List<FactPack.RepositoryRef> repositories(long userId, String techId) {
        return facts.repositories(userId, techId).stream()
                .map(row -> new FactPack.RepositoryRef(row.fullName(), row.mine()))
                .toList();
    }

    private Optional<FactPack.Period> period(long userId, String techId) {
        return facts.period(userId, techId).map(FactPackBuilder::toPeriod);
    }

    private static FactPack.Period toPeriod(Span span) {
        LocalDate first = LocalDate.ofInstant(span.first(), ZoneOffset.UTC);
        LocalDate last = LocalDate.ofInstant(span.last(), ZoneOffset.UTC);
        // 하루만 만졌어도 0 이 아니라 1 이다. 0 은 "쓴 적 없다"로 읽힌다.
        int months = (int) Math.max(1, ChronoUnit.MONTHS.between(
                first.withDayOfMonth(1), last.withDayOfMonth(1)) + 1);
        return new FactPack.Period(first, last, months);
    }

    /** 테스트가 정렬 규칙을 직접 확인할 수 있게 열어 둔다. */
    static Function<String, Integer> levelOrder() {
        return LEVELS::indexOf;
    }
}
