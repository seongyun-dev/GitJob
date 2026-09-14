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
        Map<String, String> commitLogins = resolve(job, owner[0], owner[1], refs);

        List<Authorship> rows = new ArrayList<>();
        for (EvidenceCommitRef ref : refs) {
            String commitLogin = commitLogins.get(ref.commitSha());
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
        log.info("authorship recorded: analysisId={}, evidence={}, commits={}",
                job.getAnalysisId(), written, commitLogins.size());
        return written;
    }

    /**
     * 고유 커밋마다 한 번씩만 묻고, 받은 답은 캐시에 남긴다.
     *
     * <p>{@code null} 값은 "GitHub 이 계정을 연결하지 못했다"는 뜻이다. 계정에
     * 등록하지 않은 이메일로 커밋하면 본인 코드여도 여기가 빈다. 그때 기여는
     * <b>과소평가</b>되는데, 없는 기여를 주장하는 것보다 낫다.</p>
     */
    private Map<String, String> resolve(AnalysisJob job, String owner, String repository,
            List<EvidenceCommitRef> refs) {
        Map<String, String> byCommit = new HashMap<>();
        String token = null;
        int looked = 0;

        for (EvidenceCommitRef ref : refs) {
            String sha = ref.commitSha();
            if (byCommit.containsKey(sha)) {
                continue;
            }
            CachedCommit cached = authorship.findCommit(job.getRepositoryId(), sha).orElse(null);
            if (cached != null) {
                byCommit.put(sha, cached.githubLogin());
                continue;
            }
            if (looked >= MAX_COMMIT_LOOKUPS) {
                // 남은 커밋은 미확인으로 둔다. 여기서 멈추지 않으면 한 분석이
                // 사용자의 시간당 한도를 다 쓰고 다음 분석을 전부 막는다.
                byCommit.put(sha, null);
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
        return byCommit;
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
     */
    private String contributionType(String commitLogin, String userLogin) {
        if (commitLogin == null) {
            return "UNVERIFIED";
        }
        return commitLogin.equalsIgnoreCase(userLogin) ? "SOLE_AUTHOR" : "UNVERIFIED";
    }

    private int matchedLines(String commitLogin, String userLogin, EvidenceCommitRef ref) {
        if (commitLogin == null || !commitLogin.equalsIgnoreCase(userLogin)) {
            return 0;
        }
        return Math.max(1, ref.endLine() - ref.startLine() + 1);
    }
}
