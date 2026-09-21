package com.example.git_job.analysis.store;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.stream.Stream;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * 배치 단위로 {@code analysis_job}을 읽고, 같은 사용자의 동시 제출을 직렬화한다.
 *
 * <p>{@code AnalysisHistoryStore}와 섞지 않는다. 그쪽은 마이페이지 이력 읽기 모델이고
 * 근거 집계를 JOIN해 온다 -- 여기는 진행 중 배치 하나를 그리는 것이 전부다.</p>
 */
@Repository
public class AnalysisBatchStore {

    /**
     * advisory lock의 네임스페이스. 'anb' = analysis batch.
     *
     * <p>PostgreSQL advisory lock은 전역 정수 공간 하나를 공유하므로, 다른 기능이
     * 우연히 같은 키를 쓰면 서로를 막는다. 네임스페이스를 앞에 두는 두 정수 형태가
     * 그 충돌을 막는 표준적인 방법이다.</p>
     */
    private static final int BATCH_LOCK_NAMESPACE = 0x616E62;

    private static final RowMapper<Row> ROW = (rs, index) -> new Row(
            rs.getString("analysis_id"),
            rs.getString("batch_id"),
            rs.getString("repository_id"),
            rs.getString("repository_full_name"),
            rs.getString("branch_name"),
            rs.getString("commit_sha"),
            rs.getString("status"),
            rs.getString("current_stage"),
            rs.getString("error_code"),
            rs.getTimestamp("requested_at").toInstant(),
            rs.getTimestamp("completed_at") == null
                    ? null : rs.getTimestamp("completed_at").toInstant());

    private final JdbcTemplate jdbc;

    public AnalysisBatchStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** 배치 조회가 필요한 컬럼만. 진행 화면이 그리는 값이 그대로 여기 있다. */
    public record Row(
            String analysisId,
            String batchId,
            String repositoryId,
            String repositoryFullName,
            String branchName,
            String commitSha,
            String status,
            String currentStage,
            String errorCode,
            Instant requestedAt,
            Instant completedAt) {
    }

    /**
     * 이 사용자의 배치 제출을 직렬화한다. 호출한 트랜잭션이 끝날 때 자동으로 풀린다.
     *
     * <p>검사와 INSERT는 별개의 문장이라, 잠금이 없으면 동시에 들어온 두 제출이 둘 다
     * "진행 중 없음"을 보고 통과한다. {@code uq_analysis_job_active}는
     * {@code (user_id, repository_id)} 단위라 이 경합을 판정해 주지 못한다 -- 서로 다른
     * 저장소를 고른 두 배치는 인덱스를 위반하지 않기 때문이다.</p>
     *
     * <p>{@code "user"} 행을 {@code FOR UPDATE}로 잠그지 않는 이유가 둘이다. 이
     * 코드베이스에는 비관적 잠금이 하나도 없고, {@code "user"}는 인증과 토큰 갱신이
     * 함께 쓰는 업무 행이라 분석 제출이 세션 유지와 잠금 순서로 얽힌다. 트랜잭션 범위
     * advisory lock은 커밋·롤백 어느 쪽으로 끝나도 해제돼 누수가 없고, 행이 아니라
     * 의도로 키가 매겨진다.</p>
     */
    public void lockUserBatchGate(long userId) {
        /*
         * 두 정수 형태는 키가 32비트뿐이라 userId 의 상위 32비트를 버린다. user_id 는
         * BIGINT 지만 sequence 로 증가하므로 int 범위를 넘으려면 21억 개의 계정이 필요하고,
         * 그때는 두 사용자가 같은 잠금을 공유해 제출이 서로를 기다리게 된다 -- 틀린 답을
         * 주지는 않고 느려질 뿐이다.
         *
         * 그 전에 알아차리도록 단언을 둔다. 조용히 겹치는 것보다 낫다.
         */
        if (userId > Integer.MAX_VALUE) {
            throw new IllegalStateException(
                    "user_id가 int 범위를 넘었습니다. advisory lock 키를 bigint 한 개짜리"
                            + " 형태로 바꿔야 합니다: " + userId);
        }
        jdbc.queryForObject("SELECT pg_advisory_xact_lock(?, ?)", Object.class,
                BATCH_LOCK_NAMESPACE, (int) userId);
    }

    /**
     * 이 사용자의 가장 최근 배치와 그 구성원 전부.
     *
     * <p>{@code batch_id IS NOT NULL}이 핵심이다. 빼면 V27 이전에 만들어진 모든 행이
     * 하나의 유령 NULL 배치로 묶여, 몇 달 전 단건 분석들이 "지금 진행 중인 배치"로
     * 올라온다.</p>
     *
     * <p>집계는 하지 않고 행만 돌려준다. 여기서 세려면 상태 목록을 SQL에 또 한 벌
     * 적어야 하고, 그 사본은 {@code DatabaseScriptConsistencyTest}가 지키지 않는다.
     * 배치는 {@code maxBatchSize}건 이하라 Java에서 세도 비용이 없다.</p>
     */
    public List<Row> latestBatch(long userId) {
        return jdbc.query("""
                SELECT j.analysis_id, j.batch_id, j.repository_id, j.repository_full_name,
                       j.branch_name, j.commit_sha, j.status, j.current_stage,
                       j.error_code, j.requested_at, j.completed_at
                  FROM analysis_job j
                 WHERE j.user_id = ?
                   AND j.batch_id = (
                        SELECT batch_id FROM analysis_job
                         WHERE user_id = ? AND batch_id IS NOT NULL
                         ORDER BY requested_at DESC, analysis_id DESC
                         LIMIT 1)
                 ORDER BY j.requested_at, j.analysis_id
                """, ROW, userId, userId);
    }

    /**
     * 유효시간을 넘긴 채 아직 진행 중인 분석 수. 관리자 모니터링이 읽는다.
     *
     * <p>0이 아니면 워커가 죽었거나 요청이 Kafka에 닿지 못하고 있다는 뜻이다. 이 숫자를
     * 내보내는 이유는 2026-09 장애에서 분석이 49시간 멈춰 있는 것을 아무도 몰랐기 때문이다.</p>
     *
     * <p>상태 목록은 SQL에 적지 않고 파라미터로 받는다. 그 사본은
     * {@code DatabaseScriptConsistencyTest}가 지키지 않아 조용히 어긋난다.</p>
     */
    public long countStaleSince(Collection<String> inProgressStatuses, Instant threshold) {
        String placeholders = String.join(",",
                Collections.nCopies(inProgressStatuses.size(), "?"));
        Object[] args = Stream.concat(
                inProgressStatuses.stream(),
                Stream.of(Timestamp.from(threshold))).toArray();
        Long count = jdbc.queryForObject(
                "SELECT count(*) FROM analysis_job WHERE status IN (" + placeholders + ")"
                        + " AND requested_at < ?", Long.class, args);
        return count == null ? 0L : count;
    }
}
