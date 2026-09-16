package com.example.git_job.compute.service;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.compute.client.dto.EvidencePayload;
import com.example.git_job.compute.query.UserEvidenceStore;
import com.example.git_job.compute.query.UserEvidenceStore.EvidenceRow;
import com.example.git_job.compute.query.UserEvidenceStore.RepositoryAnalysis;
import com.example.git_job.compute.query.UserEvidenceStore.TechnologySupport;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * BE의 저장소별 근거를 C가 받는 사용자 단위 Evidence로 조립한다 (S15P21E102-279).
 *
 * <h2>왜 조립이 필요한가</h2>
 *
 * <p>BE의 분석 단위는 저장소 한 건이고 C의 입력 단위는 사용자 전체다. 저장소 완료마다
 * 그대로 C를 부르면 저장소 3개를 분석한 사용자에게 결과가 3개 생기고 마지막 것만 맞다.
 * 그래서 저장소별 최신 성공 분석을 하나로 묶어 한 번만 보낸다.</p>
 *
 * <h2>Rule Pack 계보를 보존한다</h2>
 *
 * <p>C가 근거를 받아들일지 결정할 때 보는 것은 Registry 버전이 아니라 <b>Rule Pack</b>
 * 버전이다({@code evidence_rule_version}). 그 자리에 Registry 버전을 넣으면 C가 모든
 * 근거를 범위 불일치로 버리고, 화면에는 "근거는 있는데 아무것도 보유가 아닌" 상태만
 * 남는다. 오류가 나지 않으므로 원인을 찾기도 어렵다.</p>
 *
 * <p>같은 이유로 판정 상한도 관측된 최고 Level에서 만들지 않는다. 규칙이 의존성 선언까지만
 * 보는 기술을 두고 관측치를 상한으로 삼으면, 규칙이 아예 볼 수 없었던 구간까지 "판정했는데
 * 없었다"로 단정하게 된다.</p>
 *
 * <h2>없음을 만들어내지 않는다</h2>
 *
 * <p>{@code Boolean} 필드에 {@code false}를 쓰지 않는다. BE가 아는 것은 "규칙이 걸렸다"
 * 까지이고, 규칙이 안 걸린 것이 "안 썼다"는 뜻은 아니다. {@code null}(미확인)과
 * {@code false}(없음을 확인)를 구분하는 것이 C 계약의 핵심이라, 여기서 뭉개면 화면이
 * 사용자에게 "이 기술을 쓰지 않는다"고 단정한다.</p>
 */
@Component
public class UserEvidenceAssembler {

    /** C의 {@code LEVEL_POLICY_VERSION}. 다르면 C가 모든 Level 판정을 미확인으로 돌린다. */
    public static final String LEVEL_POLICY_VERSION = "level-policy/v2";

    /** 직접 의존성 근거가 되는 fact. Rule Pack의 fact type 중 이것만 MANIFEST다. */
    private static final String DEPENDENCY_FACT = "DEPENDENCY";
    /** 설정 파일에서 나온 근거. C의 {@code source_kind=CONFIG}에 해당한다. */
    private static final String CONFIG_FACT = "CONFIG_KEY";
    /** 본인이 쓴 줄로 인정하는 기여. {@code PARTIAL_EDIT}는 그 줄을 본인이 쓰지 않았다. */
    private static final Set<String> SELF_CONTRIBUTIONS = Set.of("SOLE_AUTHOR", "CO_AUTHORED");
    private static final List<String> LEVELS = List.of("L0", "L1", "L2", "L3");

    /**
     * 귀속을 확인하지 못했을 때의 판정 상한.
     *
     * <p>직접 의존성(L1)은 누가 썼는지 몰라도 판정할 수 있다. 구현과 참여(L2·L3)는
     * 작성자를 알아야 하므로, 기여 판정이 끝나지 않은 기술에서 그 위를 "판정했다"고
     * 말할 수 없다.</p>
     */
    private static final String ATTRIBUTION_UNKNOWN_CEILING = "L1";

    private final UserEvidenceStore evidence;
    private final TechnologyProfileStore profiles;

    public UserEvidenceAssembler(UserEvidenceStore evidence, TechnologyProfileStore profiles) {
        this.evidence = evidence;
        this.profiles = profiles;
    }

    /**
     * 보낼 수 없는 이유.
     *
     * <p>{@code null}을 돌려주고 끝내면 호출부가 "계산 중"과 "보낼 수 없음"을 구분하지
     * 못한다. 그러면 재분석해야 풀리는 상태가 화면에서 영원히 준비 중으로 보인다.</p>
     */
    public enum Unavailable {
        /** 성공한 분석이 없다. 분석 전 상태다. */
        NO_ANALYSIS,
        /**
         * Rule Pack 계보를 아는 분석이 없다. v1 계약으로만 받은 결과다.
         *
         * <p>기다린다고 생기지 않는다. 재분석해야 v3 결과가 들어온다.</p>
         */
        NO_RULE_PACK_LINEAGE,
        /**
         * 저장소마다 다른 Rule Pack으로 판정됐다.
         *
         * <p>C는 하나의 {@code evidence_rule_version}으로 모든 근거를 검증하므로 섞으면
         * 옛 버전 근거가 전부 버려진다. 역시 재분석해야 풀린다.</p>
         */
        MIXED_RULE_PACK
    }

    /** 조립 결과. 값이 없으면 {@link Unavailable}이 이유를 말한다. */
    public record Assembled(String evidenceVersion, EvidencePayload payload,
            Unavailable unavailable) {

        public boolean isReady() {
            return payload != null;
        }

        static Assembled of(String evidenceVersion, EvidencePayload payload) {
            return new Assembled(evidenceVersion, payload, null);
        }

        static Assembled unavailable(Unavailable reason) {
            return new Assembled(null, null, reason);
        }
    }

    @Transactional(readOnly = true)
    public Assembled assemble(long userId) {
        List<RepositoryAnalysis> all = evidence.latestAnalyses(userId);
        if (all.isEmpty()) {
            return Assembled.unavailable(Unavailable.NO_ANALYSIS);
        }

        // 계보를 모르는 분석은 보내지 않는다. Registry 버전으로 대신 채우면 C 가 그
        // 저장소의 근거를 전부 버리는데, 오류가 아니라 조용한 0건으로 나타난다.
        List<RepositoryAnalysis> analyses = all.stream()
                .filter(RepositoryAnalysis::hasLineage)
                .toList();
        if (analyses.isEmpty()) {
            return Assembled.unavailable(Unavailable.NO_RULE_PACK_LINEAGE);
        }

        Set<String> rulePacks = analyses.stream()
                .map(RepositoryAnalysis::rulePackVersion)
                .collect(Collectors.toCollection(TreeSet::new));
        Set<String> registries = analyses.stream()
                .map(RepositoryAnalysis::registryVersion)
                .collect(Collectors.toCollection(TreeSet::new));
        if (rulePacks.size() != 1 || registries.size() != 1) {
            return Assembled.unavailable(Unavailable.MIXED_RULE_PACK);
        }
        String rulePackVersion = rulePacks.iterator().next();
        String registryVersion = registries.iterator().next();

        List<EvidenceRow> rows = evidence.evidence(userId);
        Map<String, List<EvidenceRow>> byRepository = rows.stream()
                .collect(Collectors.groupingBy(EvidenceRow::repositoryId,
                        TreeMap::new, Collectors.toList()));
        Map<String, List<TechnologySupport>> supportByAnalysis = evidence.technologySupport(userId)
                .stream()
                .collect(Collectors.groupingBy(TechnologySupport::analysisId,
                        TreeMap::new, Collectors.toList()));

        String userIdText = String.valueOf(userId);
        String version = evidenceVersion(userId, analyses, registryVersion, rulePackVersion);
        String analysisId = analysisId(userId, version);

        List<EvidencePayload.Repository> repositories = new ArrayList<>();
        for (RepositoryAnalysis analysis : analyses) {
            repositories.add(repository(userIdText, analysisId, analysis, rulePackVersion,
                    byRepository.getOrDefault(analysis.repositoryId(), List.of()),
                    supportByAnalysis.getOrDefault(analysis.analysisId(), List.of())));
        }

        List<String> dataGaps = new ArrayList<>();
        if (analyses.size() != all.size()) {
            // 계보를 모르는 저장소를 뺐다는 사실을 남긴다. 그 저장소의 기술은 미판정이
            // 되어야 하고, 판정 범위가 좁아졌다는 것을 C 가 알아야 한다.
            dataGaps.add("REPOSITORY_RULE_PACK_UNKNOWN");
        }
        if (evidence.failedRepositoryIds(userId).stream().findAny().isPresent()) {
            dataGaps.add("REPOSITORY_ANALYSIS_FAILED");
        }
        if (supportByAnalysis.isEmpty()) {
            dataGaps.add("RULE_SUPPORT_UNKNOWN");
        }

        boolean complete = analyses.size() == all.size()
                && analyses.stream().allMatch(RepositoryAnalysis::coverageComplete)
                && evidence.failedRepositoryIds(userId).isEmpty();

        EvidencePayload payload = new EvidencePayload(
                EvidencePayload.SCHEMA_VERSION,
                userIdText,
                analysisId,
                registryVersion,
                LEVEL_POLICY_VERSION,
                // C 가 근거의 범위를 검사하는 값이다. Registry 버전이 아니다.
                rulePackVersion,
                complete ? "COMPLETE" : "PARTIAL",
                repositories,
                personalAssessments(userId, rows, supportByAnalysis),
                dataGaps);
        return Assembled.of(version, payload);
    }

    private EvidencePayload.Repository repository(String userId, String analysisId,
            RepositoryAnalysis analysis, String rulePackVersion, List<EvidenceRow> rows,
            List<TechnologySupport> support) {
        Map<String, List<EvidenceRow>> byTech = rows.stream()
                .collect(Collectors.groupingBy(EvidenceRow::techId, TreeMap::new,
                        Collectors.toList()));
        List<EvidencePayload.Technology> technologies = byTech.entrySet().stream()
                .map(entry -> technology(userId, analysisId, analysis, rulePackVersion,
                        entry.getKey(), entry.getValue()))
                .toList();

        List<String> dataGaps = new ArrayList<>();
        if (analysis.repositoryFullName() == null) {
            dataGaps.add("REPOSITORY_NAME_UNKNOWN");
        }
        if (!analysis.reportedSkips()) {
            // 건너뛴 파일이 있었는지조차 모른다. 완전 판정으로 보내지 않는 이유를 남긴다.
            dataGaps.add("SKIP_REPORT_UNAVAILABLE");
        } else if (analysis.skippedAnything()) {
            dataGaps.add("FILES_SKIPPED");
        }

        return new EvidencePayload.Repository(
                userId,
                analysis.repositoryId(),
                analysis.analysisId(),
                normalizeSha(analysis.commitSha()),
                "COMPLETE",
                // 성공만으로 참을 만들지 않는다. 파일을 건너뛰고도 완료로 끝날 수 있고,
                // 그 분석을 완전 판정으로 보내면 C 가 "이 기술을 쓰지 않는다"까지
                // 결론짓는다.
                analysis.coverageComplete(),
                // 판정 범위는 그 분석의 Rule Pack 이 실제로 본 기술이다. Registry 전체를
                // 넣으면 규칙조차 없는 기술을 "안 쓴다"고 단정하게 된다.
                support.stream()
                        .filter(TechnologySupport::evaluated)
                        .map(TechnologySupport::techId)
                        .sorted()
                        .toList(),
                technologies,
                dataGaps);
    }

    private EvidencePayload.Technology technology(String userId, String analysisId,
            RepositoryAnalysis analysis, String rulePackVersion, String techId,
            List<EvidenceRow> rows) {
        boolean hasDependency = rows.stream().anyMatch(row -> DEPENDENCY_FACT.equals(row.factType()));
        boolean hasImplementation = rows.stream()
                .anyMatch(row -> !DEPENDENCY_FACT.equals(row.factType()));
        boolean selfAuthored = rows.stream().anyMatch(UserEvidenceAssembler::isSelfAuthored);
        boolean selfImplementation = rows.stream()
                .filter(row -> !DEPENDENCY_FACT.equals(row.factType()))
                .anyMatch(UserEvidenceAssembler::isSelfAuthored);
        long attributed = rows.stream().filter(row -> row.contributionType() != null).count();

        List<EvidencePayload.Proof> proofs = rows.stream()
                .map(row -> proof(userId, analysisId, analysis, rulePackVersion, techId, row))
                .filter(java.util.Objects::nonNull)
                .toList();

        return new EvidencePayload.Technology(
                techId,
                rows.stream().map(row -> String.valueOf(row.evidenceId())).distinct().toList(),
                highestLevel(rows),
                // 세 값 모두 true 아니면 null이다. false는 "없음을 확인했다"는 뜻이고
                // BE는 그것을 증명할 수 없다.
                hasDependency ? Boolean.TRUE : null,
                hasImplementation ? Boolean.TRUE : null,
                selfAuthored ? Boolean.TRUE : null,
                selfImplementation ? "SELF" : "UNKNOWN",
                attributionStatus(attributed, rows.size()),
                List.of(),
                proofs);
    }

    /**
     * 근거 한 줄을 C의 근거 행으로 옮긴다.
     *
     * @return 경로가 저장소 상대 경로가 아니면 {@code null}. C가 거절할 값을 보내면 묶음
     *         전체가 422가 되므로, 그 한 줄만 뺀다.
     */
    private EvidencePayload.Proof proof(String userId, String analysisId,
            RepositoryAnalysis analysis, String rulePackVersion, String techId, EvidenceRow row) {
        String path = normalizePath(row.filePath());
        if (path == null) {
            return null;
        }
        boolean dependency = DEPENDENCY_FACT.equals(row.factType());
        String attribution = attribution(row);
        String blameSha = normalizeSha(row.blameCommitSha());
        // SELF인데 커밋이 없으면 C가 참여 근거로 인정하지 않는다. 그 조합을 보내는 것보다
        // 미확인으로 두는 편이 정확하다 -- blame을 못 읽은 것이지 남이 쓴 것이 아니다.
        if ("SELF".equals(attribution) && blameSha == null) {
            attribution = "UNKNOWN";
        }
        return new EvidencePayload.Proof(
                String.valueOf(row.evidenceId()),
                String.valueOf(row.evidenceId()),
                row.ruleId(),
                // 상위 evidence_rule_version 과 같아야 C 가 근거를 받아들인다.
                rulePackVersion,
                techId,
                userId,
                analysisId,
                analysis.repositoryId(),
                analysis.analysisId(),
                normalizeSha(analysis.commitSha()),
                dependency ? "DIRECT_DEPENDENCY" : "IMPLEMENTATION",
                sourceKind(row.factType()),
                path,
                row.startLine(),
                row.endLine(),
                sourceRef(analysis, path, row.startLine()),
                "ACCEPTED",
                null,
                "PROJECT",
                false,
                attribution,
                "SELF".equals(attribution) ? blameSha : null,
                dependency ? Boolean.TRUE : null);
    }

    /**
     * 사용자 단위 개인 판정.
     *
     * <p>{@code personalLevel}은 {@code TechnologyProfileStore}가 이미 계산한다. 여기서
     * 다시 계산하지 않는 이유는 화면의 Personal Level과 C가 보는 값이 달라지면 안 되기
     * 때문이다 -- 같은 질문에 답이 둘이면 어느 쪽도 근거가 되지 못한다.</p>
     */
    private List<EvidencePayload.PersonalAssessment> personalAssessments(long userId,
            List<EvidenceRow> rows, Map<String, List<TechnologySupport>> supportByAnalysis) {
        Map<String, String> personal = profiles.personalLevels(userId).stream()
                .collect(Collectors.toMap(TechnologyProfileStore.TechnologyLevel::techId,
                        TechnologyProfileStore.TechnologyLevel::level, (first, second) -> first));
        Map<String, String> supported = supportedCeilings(supportByAnalysis);

        Map<String, List<EvidenceRow>> byTech = rows.stream()
                .collect(Collectors.groupingBy(EvidenceRow::techId, TreeMap::new,
                        Collectors.toList()));
        List<EvidencePayload.PersonalAssessment> assessments = new ArrayList<>();
        for (Map.Entry<String, List<EvidenceRow>> entry : byTech.entrySet()) {
            List<EvidenceRow> techRows = entry.getValue();
            String level = personal.getOrDefault(entry.getKey(), "L0");
            long attributed = techRows.stream()
                    .filter(row -> row.contributionType() != null).count();
            String status = attributionStatus(attributed, techRows.size());
            assessments.add(new EvidencePayload.PersonalAssessment(
                    entry.getKey(), level,
                    ceiling(supported.get(entry.getKey()), status, level),
                    status,
                    "COMPLETE".equals(status) ? List.of() : missingScope(techRows)));
        }
        return assessments;
    }

    /** 기술별 Rule Pack 상한. 여러 분석이 같은 기술을 봤으면 가장 높은 상한을 쓴다. */
    private Map<String, String> supportedCeilings(
            Map<String, List<TechnologySupport>> supportByAnalysis) {
        Map<String, String> ceilings = new TreeMap<>();
        supportByAnalysis.values().stream()
                .flatMap(List::stream)
                .filter(TechnologySupport::evaluated)
                .forEach(item -> ceilings.merge(item.techId(), item.maxSupportedLevel(),
                        UserEvidenceAssembler::higher));
        return ceilings;
    }

    /**
     * 판정 상한 -- "BE의 규칙이 배제할 수 있는 최고 Level".
     *
     * <p>관측된 최고 Level에서 만들지 않는다. 관측치는 "무엇을 봤는가"이고 상한은
     * "무엇까지 볼 수 있었는가"라, 관측치를 상한으로 삼으면 규칙이 아예 볼 수 없었던
     * 구간까지 판정했다고 주장하게 된다.</p>
     *
     * <p>귀속을 확인하지 못했으면 L1로 내린다. 구현과 참여는 작성자를 알아야 판정할 수
     * 있기 때문이다. 다만 개인 판정 자체가 그보다 높으면 그 아래로 내리지 않는다 --
     * C는 {@code personal_level <= assessment_ceiling}을 요구하고, 이미 판정된 값을
     * 상한이 부정하면 묶음 전체가 거절된다.</p>
     *
     * <p>Rule Pack 상한을 모르는 기술(지원 표가 없는 분석)은 개인 판정을 그대로 상한으로
     * 둔다. 모르는 것을 높게 잡으면 판정하지 않은 구간을 판정했다고 말하게 된다.</p>
     */
    private static String ceiling(String maxSupported, String attributionStatus,
                                  String personalLevel) {
        String bound = maxSupported;
        if (!"COMPLETE".equals(attributionStatus)) {
            bound = bound == null
                    ? ATTRIBUTION_UNKNOWN_CEILING
                    : lower(bound, ATTRIBUTION_UNKNOWN_CEILING);
        }
        return bound == null ? personalLevel : higher(bound, personalLevel);
    }

    /** 기여 판정이 없는 저장소. 불완전 판정은 무엇을 못 봤는지 함께 적어야 C가 받는다. */
    private List<String> missingScope(List<EvidenceRow> rows) {
        List<String> scope = rows.stream()
                .filter(row -> row.contributionType() == null)
                .map(row -> "repository:" + row.repositoryId())
                .distinct()
                .sorted()
                .collect(Collectors.toCollection(ArrayList::new));
        if (scope.isEmpty()) {
            scope.add("ATTRIBUTION_UNKNOWN");
        }
        return scope;
    }

    /**
     * 이 Evidence 묶음의 정체성.
     *
     * <p>재료는 판정 범위를 정하는 값뿐이다 -- 저장소·분석 ID·커밋·Registry·Rule Pack.
     * Rule Pack을 넣는 이유는 같은 커밋이라도 Rule Pack이 바뀌면 판정이 달라지기
     * 때문이다. 넣지 않으면 재분석해도 같은 event ID가 나와 C가 옛 결과를 그대로 준다.</p>
     *
     * <p>시각을 넣지 않는 것이 핵심이다. 넣으면 호출할 때마다 다른 event ID가 되어
     * 멱등이 깨지고, 재시작할 때마다 C가 같은 계산을 다시 한다.</p>
     */
    private String evidenceVersion(long userId, List<RepositoryAnalysis> analyses,
            String registryVersion, String rulePackVersion) {
        StringBuilder canonical = new StringBuilder()
                .append(userId).append('')
                .append(registryVersion).append('')
                .append(rulePackVersion).append('')
                .append(LEVEL_POLICY_VERSION);
        analyses.stream()
                .sorted(Comparator.comparing(RepositoryAnalysis::repositoryId))
                .forEach(analysis -> canonical.append('')
                        .append(analysis.repositoryId()).append('')
                        .append(analysis.analysisId()).append('')
                        .append(normalizeSha(analysis.commitSha())));
        return sha256(canonical.toString());
    }

    /**
     * C에 보낼 사용자 단위 분석 ID.
     *
     * <p>C의 {@code Identifier}는 {@code ^[A-Za-z0-9][A-Za-z0-9._:-]*$}, 128자 이하다.
     * 앞의 {@code u}는 그 첫 글자 조건을 맞추면서 이 값이 저장소 분석 ID가 아니라는 것을
     * 드러낸다.</p>
     */
    private String analysisId(long userId, String evidenceVersion) {
        return "u" + userId + "-" + evidenceVersion.substring(0, 32);
    }

    private static boolean isSelfAuthored(EvidenceRow row) {
        return row.contributionType() != null && SELF_CONTRIBUTIONS.contains(row.contributionType());
    }

    private static String attributionStatus(long attributed, int total) {
        if (attributed == 0) {
            return "UNKNOWN";
        }
        return attributed == total ? "COMPLETE" : "PARTIAL";
    }

    /** {@code SOLE_AUTHOR}·{@code CO_AUTHORED}만 본인이다. 나머지는 그 줄을 본인이 쓰지 않았다. */
    private static String attribution(EvidenceRow row) {
        if (row.contributionType() == null) {
            return "UNKNOWN";
        }
        if (SELF_CONTRIBUTIONS.contains(row.contributionType())) {
            return "SELF";
        }
        return "PARTIAL_EDIT".equals(row.contributionType()) ? "OTHER" : "UNKNOWN";
    }

    private static String sourceKind(String factType) {
        if (DEPENDENCY_FACT.equals(factType)) {
            return "MANIFEST";
        }
        return CONFIG_FACT.equals(factType) ? "CONFIG" : "SOURCE";
    }

    /** {@code rule_type}은 L0..L3 문자열이라 사전순 최대가 곧 최고 Level이다. */
    private static String highestLevel(List<EvidenceRow> rows) {
        return rows.stream().map(EvidenceRow::ruleType)
                .filter(LEVELS::contains)
                .max(Comparator.naturalOrder())
                .orElse(null);
    }

    private static String higher(String left, String right) {
        if (left == null) {
            return right;
        }
        if (right == null) {
            return left;
        }
        return LEVELS.indexOf(left) >= LEVELS.indexOf(right) ? left : right;
    }

    private static String lower(String left, String right) {
        if (left == null) {
            return right;
        }
        if (right == null) {
            return left;
        }
        return LEVELS.indexOf(left) <= LEVELS.indexOf(right) ? left : right;
    }

    /**
     * 저장소 상대 경로인지 확인한다. C가 같은 검사를 하고, 걸리면 묶음 전체가 실패한다.
     *
     * @return 안전하지 않으면 {@code null}
     */
    private static String normalizePath(String path) {
        if (path == null || path.isBlank()) {
            return null;
        }
        String normalized = path.replace('\\', '/');
        if (normalized.startsWith("/") || normalized.contains(":")) {
            return null;
        }
        for (String part : normalized.split("/", -1)) {
            if (part.isEmpty() || ".".equals(part) || "..".equals(part)) {
                return null;
            }
        }
        for (int index = 0; index < normalized.length(); index++) {
            if (normalized.charAt(index) < 32) {
                return null;
            }
        }
        return normalized;
    }

    /** {@code CHAR(40)}은 공백으로 채워질 수 있고, C는 40자 소문자 hex만 받는다. */
    private static String normalizeSha(String sha) {
        if (sha == null) {
            return null;
        }
        String trimmed = sha.trim().toLowerCase(java.util.Locale.ROOT);
        return trimmed.matches("[0-9a-f]{40}") ? trimmed : null;
    }

    /** 근거의 출처 표기. 이름을 모르는 옛 분석은 저장소 ID로 적는다. */
    private static String sourceRef(RepositoryAnalysis analysis, String path, int line) {
        String repository = analysis.repositoryFullName() == null
                ? "repository:" + analysis.repositoryId()
                : analysis.repositoryFullName();
        return repository + "@" + analysis.commitSha().trim() + ":" + path + "#L" + line;
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256을 사용할 수 없습니다.", e);
        }
    }
}
