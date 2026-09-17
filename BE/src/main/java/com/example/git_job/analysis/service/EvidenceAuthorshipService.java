package com.example.git_job.analysis.service;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.client.dto.GithubCommitResponse;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.Authorship;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.CachedCommit;
import com.example.git_job.analysis.store.EvidenceAuthorshipStore.EvidenceCommitRef;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 근거를 쓴 사람을 확정한다.
 *
 * <h2>왜 이메일을 비교하지 않는가</h2>
 *
 * <p>GitHub 이 커밋의 이메일을 등록된 계정과 이미 맞춰 두었다. 그 답을 받아 쓰면
 * 사용자의 주소 목록이 필요 없고({@code user:email} scope 없이도 된다), 저장소의
 * 다른 기여자 이메일을 우리 시스템이 다루지 않아도 된다.</p>
 *
 * <h2>실패해도 분석을 되돌리지 않는다</h2>
 *
 * <p>근거 적재와 <b>다른 트랜잭션</b>이다. GitHub 이 느리거나 한도에 걸렸다고 해서
 * 이미 판정된 근거 651건을 버리고 재배달을 기다릴 이유가 없다. 기여 판정이 없으면
 * Personal Level 만 비고, 다음 분석이나 재실행이 채운다.</p>
 */
@Service
@RequiredArgsConstructor
public class EvidenceAuthorshipService {

    private static final Logger log = LoggerFactory.getLogger(EvidenceAuthorshipService.class);

    /**
     * 한 분석에서 조회할 고유 커밋 수의 상한.
     *
     * <p>커밋 하나가 API 호출 하나다. 근거가 수백 건이어도 커밋은 보통 수십 개로
     * 수렴하지만, 파일마다 다른 커밋인 저장소도 있다. 한 분석이 사용자의 시간당
     * 한도를 다 쓰면 그 뒤의 저장소 분석이 전부 막힌다.</p>
     */
    private static final int MAX_COMMIT_LOOKUPS = 100;

    private final EvidenceAuthorshipStore authorship;
    private final GithubRepositoryClient github;
    private final GithubAccessTokenProvider accessTokens;
    private final UserRepository users;

    /**
     * 이 분석의 근거에 기여 판정을 붙인다.
     *
     * @return 기록된 근거 수. 0 이면 판정하지 못한 것이고 실패는 아니다.
     */
    @Transactional
    public int attribute(AnalysisJob job) {
        List<EvidenceCommitRef> refs = authorship.evidenceWithCommits(job.getAnalysisId());
        if (refs.isEmpty()) {
            // 워커가 기여 판정을 끄고 돌렸거나 얕은 체크아웃이었다. 정상 경로다.
            return 0;
        }
        String fullName = job.getRepositoryFullName();
        if (fullName == null || !fullName.contains("/")) {
            log.info("authorship skipped, repository name unknown: analysisId={}",
                    job.getAnalysisId());
            return 0;
        }
        String login = users.findById(job.getUserId())
                .map(user -> user.getGithubLogin())
                .orElse(null);
        if (login == null) {
            return 0;
        }

        String[] owner = fullName.split("/", 2);
        CommitAuthors authors = resolve(job, owner[0], owner[1], refs);

        List<Authorship> rows = new ArrayList<>();
        for (EvidenceCommitRef ref : refs) {
            String commitLogin = authors.byCommit().get(ref.commitSha());
            rows.add(new Authorship(
                    ref.analysisEvidenceId(),
                    job.getAnalysisId(),
                    job.getRepositoryId(),
                    ref.commitSha(),
                    job.getUserId(),
                    contributionType(commitLogin, login),
                    matchedLines(commitLogin, login, ref)));
        }
        int written = authorship.insertAll(rows);

        // 상한에 걸린 것은 경고로 올린다. 저장된 행만 보면 이 분석은 "미확인이 많은
        // 저장소"와 구분되지 않는다 -- 둘 다 UNVERIFIED 다. 기여가 과소평가됐다는
        // 사실이 남는 곳은 여기뿐이고, 남지 않으면 사용자가 왜 Personal Level 을 못
        // 받았는지 되짚을 방법이 없다.
        if (authors.skipped() > 0) {
            log.warn("authorship lookup budget exhausted: analysisId={}, userId={}, commits={},"
                            + " lookedUp={}, cached={}, skipped={}, limit={}."
                            + " 남은 커밋은 묻지 못해 미확인으로 남았고 기여가 과소평가된다.",
                    job.getAnalysisId(), job.getUserId(), authors.byCommit().size(),
                    authors.lookedUp(), authors.cached(), authors.skipped(),
                    MAX_COMMIT_LOOKUPS);
        }
        log.info("authorship recorded: analysisId={}, evidence={}, commits={}, lookedUp={},"
                        + " cached={}, skipped={}",
                job.getAnalysisId(), written, authors.byCommit().size(),
                authors.lookedUp(), authors.cached(), authors.skipped());
        return written;
    }

    /**
     * 커밋별 작성자와, 그 답을 어떻게 얻었는지.
     *
     * <p>{@code skipped} 가 0 이 아니면 그 분석의 기여는 <b>과소평가</b>된 것이다.
     * 묻지 못한 커밋은 {@code null} 로 남아 "GitHub 이 계정을 붙이지 못했다"와 같은
     * 값이 되는데, 실제로는 묻지도 않았다. 저장된 행으로는 그 둘을 나눌 수 없으므로
     * 호출부가 로그로 남긴다.</p>
     *
     * @param cached GitHub 대신 {@code repository_commit} 에서 답을 얻은 커밋 수
     */
    private record CommitAuthors(Map<String, String> byCommit, int lookedUp, int cached,
            int skipped) {
    }

    /**
     * 고유 커밋마다 한 번씩만 묻고, 받은 답은 캐시에 남긴다.
     *
     * <p>{@code null} 값은 "GitHub 이 계정을 연결하지 못했다"는 뜻이다. 계정에
     * 등록하지 않은 이메일로 커밋하면 본인 코드여도 여기가 빈다. 그때 기여는
     * <b>과소평가</b>되는데, 없는 기여를 주장하는 것보다 낫다.</p>
     */
    private CommitAuthors resolve(AnalysisJob job, String owner, String repository,
            List<EvidenceCommitRef> refs) {
        Map<String, String> byCommit = new HashMap<>();
        String token = null;
        int looked = 0;
        int cachedHits = 0;
        int skipped = 0;

        for (EvidenceCommitRef ref : refs) {
            String sha = ref.commitSha();
            if (byCommit.containsKey(sha)) {
                continue;
            }
            CachedCommit cached = authorship.findCommit(job.getRepositoryId(), sha).orElse(null);
            if (cached != null) {
                byCommit.put(sha, cached.githubLogin());
                cachedHits++;
                continue;
            }
            if (looked >= MAX_COMMIT_LOOKUPS) {
                // 남은 커밋은 미확인으로 둔다. 여기서 멈추지 않으면 한 분석이
                // 사용자의 시간당 한도를 다 쓰고 다음 분석을 전부 막는다.
                //
                // 세어 두는 이유는 저장된 행이 이 사실을 담지 못하기 때문이다.
                // 묻지 못한 커밋과 물었는데 계정이 없던 커밋이 같은 UNVERIFIED 가 된다.
                byCommit.put(sha, null);
                skipped++;
                continue;
            }
            if (token == null) {
                token = accessTokens.accessTokenOf(job.getUserId());
            }
            looked++;
            GithubCommitResponse commit = github.fetchCommit(token, owner, repository, sha);
            if (commit == null) {
                // force push 로 사라진 커밋이 근거에 남아 있을 수 있다.
                byCommit.put(sha, null);
                continue;
            }
            byCommit.put(sha, commit.githubLogin());
            authorship.cacheCommit(job.getRepositoryId(), sha, commit.githubLogin(),
                    commit.authorName(), commit.commit() == null ? null
                            : commit.commit().author() == null ? null
                                    : commit.commit().author().email(),
                    commit.authoredAt() == null
                            ? OffsetDateTime.now(ZoneOffset.UTC)
                            : commit.authoredAt());
        }
        return new CommitAuthors(byCommit, looked, cachedHits, skipped);
    }

    /**
     * 근거 한 줄의 기여 라벨.
     *
     * <p>지금은 근거 하나에 커밋 하나가 붙는다 -- 워커가 근거의 시작 줄을 blame 해
     * 그 커밋을 싣기 때문이다. 그래서 본인 것이면 {@code SOLE_AUTHOR}, 아니면
     * {@code UNVERIFIED} 둘로 갈린다.</p>
     *
     * <p>{@code CO_AUTHORED} 와 {@code PARTIAL_EDIT} 는 근거가 여러 줄에 걸치고 그
     * 줄들의 커밋이 갈릴 때 쓸 값이다. 지금 근거는 한 줄짜리라 나오지 않지만, 값
     * 집합을 미리 좁히면 나중에 마이그레이션이 필요해진다.</p>
     *
     * <h2>못 물어본 것과 물어봐서 아닌 것은 다르다</h2>
     *
     * <p>둘 다 {@code UNVERIFIED} 로 쓰던 때가 있었다. Level 판정만 보면 어차피 둘 다
     * 제외되니 결과가 같았기 때문인데, 그 뒤 두 값을 실제로 구분해야 하는 곳이
     * 생겼다 -- 기술 요약 계약의 {@code authorship} 은 "본인 근거가 소수다"
     * ({@code MOSTLY_OTHERS})와 "판정 자체가 없다"({@code NOT_VERIFIED})를 다른
     * 값으로 요구한다. 저장할 때 합쳐 두면 나중에 되살릴 수 없다.</p>
     *
     * <p>{@code PARTIAL_EDIT} 를 재사용하지 않는다. 그 값은 "근거 줄은 남이 썼지만
     * 그 파일을 본인이 건드린 적 있다"는 더 좁은 뜻이고(V14), 우리는 파일을 건드린
     * 적이 있는지 확인하지 않았다. 확인하지 않은 것을 주장하지 않는다.</p>
     */
    private String contributionType(String commitLogin, String userLogin) {
        if (commitLogin == null) {
            // GitHub 이 커밋을 계정에 붙이지 못했다. 등록하지 않은 이메일로 커밋하면
            // 본인 코드여도 여기로 온다 -- "본인이 아니다"가 아니라 "모른다"이다.
            return "UNVERIFIED";
        }
        return commitLogin.equalsIgnoreCase(userLogin) ? "SOLE_AUTHOR" : "OTHER_AUTHOR";
    }

    private int matchedLines(String commitLogin, String userLogin, EvidenceCommitRef ref) {
        if (commitLogin == null || !commitLogin.equalsIgnoreCase(userLogin)) {
            return 0;
        }
        return Math.max(1, ref.endLine() - ref.startLine() + 1);
    }
}
