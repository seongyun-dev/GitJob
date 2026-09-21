package com.example.git_job.analysis.repository;

import com.example.git_job.analysis.domain.AnalysisJob;
import jakarta.persistence.LockModeType;
import jakarta.persistence.QueryHint;
import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.QueryHints;

/** The analysis ID is a server-assigned string, so it is also the JPA identifier type. */
public interface AnalysisJobRepository extends JpaRepository<AnalysisJob, String> {

    /**
     * Backs the "no duplicate job while one is already running" rule. Ordering by
     * requested_at keeps the answer stable if older rows were left behind by a crash.
     */
    Optional<AnalysisJob> findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
            Long userId, String repositoryId, Collection<String> statuses);

    /**
     * 같은 분석에 쓰는 두 컨슈머가 공유하는 잠금 조회.
     *
     * <p>진행 이벤트와 결과 이벤트는 서로 다른 리스너 컨테이너에서 동시에 처리된다. 둘
     * 다 읽고-고치고-쓰기라, 잠금 없이는 나중에 커밋한 쪽이 상대의 변경을 통째로 덮는다.
     * 실제로 결과가 {@code SUCCEEDED} 로 닫은 잡을 0.008초 뒤 도착한 진행 이벤트가
     * {@code ANALYZING} 으로 되돌리고 {@code completed_at} 을 지웠다(2026-09-21 e2e).
     * {@code AnalysisJob.progress()} 의 "종료된 잡은 옮기지 않는다" 가드는 그 시점에
     * 이미 낡은 스냅샷을 보고 있어 막지 못한다.</p>
     *
     * <p>그 잡은 결과가 이미 소비돼 다시 닫히지 않으므로 유효시간이 지날 때까지
     * 진행 중으로 남고, 묶음 진행률이 거기서 멈추며 사용자는 계속 차단된다 -- 이 티켓이
     * 없애려던 바로 그 고장이다.</p>
     *
     * <p>{@code @Version} 대신 행 잠금을 쓰는 것은 컬럼을 늘리지 않기 위해서다. 경합하는
     * 것은 한 분석의 두 이벤트뿐이고 잠금 구간도 짧다.</p>
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    Optional<AnalysisJob> findWithLockByAnalysisId(String analysisId);

    /**
     * 제출 차단 판정. "이 사용자에게 유효시간 안의 진행 중 분석이 하나라도 있는가".
     *
     * <p>{@code batchId}를 보지 않는 것이 핵심이다. 배치 이전에 만들어진 행
     * ({@code batch_id IS NULL})도 진행 중이면 저장소를 점유하고 있으므로 똑같이 막아야
     * 한다. 배치 범위로 판정하면 그런 사용자가 "제출 가능"을 보고 눌렀다가 409를 맞는다.</p>
     *
     * <p>상태 목록은 언제나 {@link AnalysisJob#IN_PROGRESS_STATUSES}를 넘긴다. SQL에
     * 상태를 적는 자리를 새로 만들지 않기 위해서다 -- 그 사본은
     * {@code DatabaseScriptConsistencyTest}가 지키지 않는다.</p>
     */
    boolean existsByUserIdAndStatusInAndRequestedAtAfter(
            Long userId, Collection<String> statuses, Instant threshold);

    /**
     * 유효시간을 넘긴 진행 중 분석. {@code StaleAnalysisReaper}가 종료시킬 대상이다.
     *
     * <p>사용자를 가리지 않는다. 한 번의 tick에서 처리할 수를 {@link Pageable}로 묶어
     * 오래 밀린 상태에서도 한 트랜잭션이 비대해지지 않게 한다.</p>
     *
     * <p>{@code SKIP LOCKED}로 잠근다. backend를 두 개 이상 띄우면 두 인스턴스가 같은
     * 행들을 읽어 같은 값을 두 번 쓰게 되는데, 데이터가 깨지지는 않지만 정리 로그가
     * 겹쳐 무엇이 실제로 일어났는지 읽을 수 없다. {@code AnalysisOutboxStore.lockNext()}가
     * 같은 이유로 같은 방식을 쓴다.</p>
     *
     * <p>잠금 타임아웃 {@code -2}가 Hibernate의 {@code SKIP_LOCKED}다.</p>
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints(@QueryHint(name = "jakarta.persistence.lock.timeout", value = "-2"))
    List<AnalysisJob> findByStatusInAndRequestedAtBefore(
            Collection<String> statuses, Instant threshold, Pageable page);
}
