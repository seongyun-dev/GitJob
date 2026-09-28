package com.example.git_job.analysis.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PostLoad;
import jakarta.persistence.PostPersist;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
import java.time.Instant;
import java.util.Objects;
import java.util.Set;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import org.springframework.data.domain.Persistable;

/**
 * One repository analysis job. The analysis ID is assigned by the server before the
 * job exists, so it is never generated here.
 *
 * <p>Status and stage stay plain strings on purpose: the Python worker also writes
 * them, and an enum that does not cover a value the worker sends would fail on read.
 * Narrow them once that contract is fixed.</p>
 */
@Entity
@Table(name = "analysis_job")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AnalysisJob implements Persistable<String> {

    public static final String STATUS_QUEUED = "QUEUED";
    /**
     * 워커가 이 분석을 집어 일하고 있다.
     *
     * <p>새 값이 아니다. {@link #IN_PROGRESS_STATUSES} 와 응답 경계의
     * {@code normalize()} 가 이미 알고 있던 값이고, 여태 아무도 쓰지 않았을 뿐이다.
     * 그래서 이 상태를 쓰기 시작해도 중복 요청 판정과 FE 계약은 그대로다 --
     * 화면에는 {@code RUNNING} 으로 나간다.</p>
     *
     * <p>세부 단계는 여기가 아니라 {@code currentStage} 가 나른다. 상태를 늘리면
     * 응답 계약의 다섯 값을 넘게 되고, 계약 밖 값은 화면에서 실패로 접힌다.</p>
     */
    public static final String STATUS_ANALYZING = "ANALYZING";
    /** Terminal. docs/fe/shared-api-contract.md §JobStatus. */
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STAGE_WAITING_FOR_WORKER = "WAITING_FOR_WORKER";
    public static final String STAGE_COMPLETED = "COMPLETED";
    public static final String STAGE_FAILED = "FAILED";

    /**
     * 워커가 끝내지 못한 채 유효시간을 넘겨 서버가 종료시킨 분석
     * ({@code StaleAnalysisReaper}).
     *
     * <p>{@code ErrorCode} enum의 {@code AN-404-1} 계열이 아니라 워커가 쓰는
     * {@code REPOSITORY_TOO_LARGE}·{@code GITHUB_RECONNECT_REQUIRED}와 같은 어휘다.
     * 이 값은 API 오류 코드가 아니라 {@code analysis_job.error_code}에 저장돼
     * 화면의 실패 사유로 나간다.</p>
     */
    public static final String ERROR_ANALYSIS_TIMED_OUT = "ANALYSIS_TIMED_OUT";

    /**
     * Statuses that mean a job still owns its repository, so a second request for the
     * same repository must not create another one. The two vocabularies below both
     * appear in the API spec; unifying them into one enum is a separate ticket, and
     * listing both here is what keeps the duplicate check correct until then.
     */
    public static final Set<String> IN_PROGRESS_STATUSES = Set.of(
            "QUEUED", "COLLECTING", "RUNNING", "ANALYZING", "RATE_LIMITED", "CANCEL_REQUESTED");

    @Id
    @Column(name = "analysis_id", length = 80)
    private String analysisId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    /** GitHub numeric repository ID stored as text, matching the existing schema. */
    @Column(name = "repository_id", nullable = false, length = 80)
    private String repositoryId;

    /**
     * 분석 당시의 {@code owner/repo}. 표시와 permalink 전용이다.
     *
     * <p>저장소 이름은 바뀔 수 있으므로 동일성은 {@code repositoryId}로 본다.
     * 여기에 그때의 이름을 박아 두는 것은, 이름이 바뀐 뒤에도 그때 만든 근거
     * 링크가 그 커밋을 가리켜야 하기 때문이다.</p>
     *
     * <p>V13 이전에 만들어진 행은 {@code null}이다. 받아 적지 않았던 값이라
     * 되살릴 수 없고, 조회 쪽이 permalink 없는 근거로 다룬다.</p>
     */
    @Column(name = "repository_full_name", length = 255)
    private String repositoryFullName;

    @Column(name = "branch_name", nullable = false, length = 255)
    private String branchName;

    /** The column is CHAR(40), not VARCHAR; ddl-auto=validate compares the JDBC type. */
    @JdbcTypeCode(SqlTypes.CHAR)
    @Column(name = "commit_sha", nullable = false, length = 40)
    private String commitSha;

    @Column(name = "status", nullable = false, length = 16)
    private String status;

    @Column(name = "current_stage", nullable = false, length = 40)
    private String currentStage;

    @Column(name = "requested_at", nullable = false)
    private Instant requestedAt;

    @Column(name = "started_at")
    private Instant startedAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    @Column(name = "error_code", length = 64)
    private String errorCode;

    /**
     * 한 번의 배치 요청으로 함께 접수된 분석의 묶음 ID (V27).
     *
     * <p>이 컬럼이 생기기 전 단건 요청은 {@code null}이다. 그 행들도 진행 중이면
     * 여전히 제출을 막지만 -- 차단 판정은 잡 단위라 {@code batchId}를 보지 않는다 --
     * 배치 조회에서는 제외된다. 없는 묶음을 지어내지 않기 위해서다.</p>
     */
    @Column(name = "batch_id", length = 80)
    private String batchId;

    /** GitHub 기여 판정 시도가 끝나 C 계산이 이 분석을 읽어도 되는 시각. */
    @Column(name = "compute_ready_at")
    private Instant computeReadyAt;

    /**
     * With an assigned ID Spring Data would treat every instance as detached and call
     * merge(), costing a SELECT before each insert. Persistable states the truth instead.
     */
    @Transient
    private boolean isNew = true;

    private AnalysisJob(String analysisId, Long userId, String repositoryId,
            String repositoryFullName, String branchName, String commitSha,
            Instant requestedAt, String batchId) {
        this.analysisId = analysisId;
        this.userId = userId;
        this.repositoryId = repositoryId;
        this.repositoryFullName = repositoryFullName;
        this.branchName = branchName;
        this.commitSha = commitSha;
        this.requestedAt = requestedAt;
        this.batchId = batchId;
        this.status = STATUS_QUEUED;
        this.currentStage = STAGE_WAITING_FOR_WORKER;
    }

    /**
     * Initial state of an accepted request. The worker owns every transition after this.
     *
     * @param batchId 함께 접수된 분석들의 묶음. 단건 경로에서 넘어오면 {@code null}이고,
     *                그때 이 분석은 배치 조회에 잡히지 않는다
     */
    public static AnalysisJob queue(String analysisId, long userId, String repositoryId,
            String repositoryFullName, String branchName, String commitSha,
            Instant requestedAt, String batchId) {
        return new AnalysisJob(
                Objects.requireNonNull(analysisId, "analysisId must not be null"),
                userId,
                Objects.requireNonNull(repositoryId, "repositoryId must not be null"),
                // 이름은 없어도 분석은 성립한다. 없으면 근거 링크만 만들지 못한다.
                repositoryFullName,
                Objects.requireNonNull(branchName, "branchName must not be null"),
                Objects.requireNonNull(commitSha, "commitSha must not be null"),
                Objects.requireNonNull(requestedAt, "requestedAt must not be null"),
                batchId);
    }

    /**
     * 워커가 알려 온 단계로 옮긴다.
     *
     * <p>진행 이벤트는 표시용이다. 옮기지 못했다고 해서 잘못된 것은 없고, 화면이
     * 한 단계 늦게 움직일 뿐이다. 그래서 예외 대신 {@code false} 를 돌려준다.</p>
     *
     * <h2>움직이지 않는 세 경우</h2>
     *
     * <ol>
     *   <li><b>이미 종료됐다.</b> 진행 토픽과 결과 토픽은 서로 다른 토픽이라 순서가
     *       보장되지 않는다. 결과가 먼저 닿으면 완료된 분석에 진행 이벤트가 뒤늦게
     *       도착하는데, 그때 상태를 되돌리면 끝난 분석이 다시 도는 것처럼 보인다.</li>
     *   <li><b>뒤로 가는 단계다.</b> 클레임 테이크오버로 같은 분석이 처음부터 다시
     *       돌면 1단계 이벤트가 다시 온다. 실제로 다시 돌고 있는 것은 맞지만, 화면이
     *       거꾸로 가면 사용자는 앞서 본 진행이 취소됐다고 읽는다.</li>
     *   <li><b>같은 단계다.</b> at-least-once 전달이라 같은 이벤트가 두 번 온다.
     *       위의 순서 비교가 이것도 함께 막는다.</li>
     * </ol>
     *
     * <p>모르는 {@code currentStage} 위에서는 옮기는 쪽을 고른다. 여기에 도달하는
     * 미지의 값은 이 코드보다 새로운 워커가 쓴 것이고, 그때는 멈춰 있는 화면보다
     * 한 칸 건너뛴 화면이 낫다.</p>
     *
     * @param at 이 서비스가 이벤트를 받은 시각. 워커의 시계를 쓰지 않는 것은
     *           {@code completedAt} 과 같은 이유다 -- 두 호스트의 시차가 진행을
     *           요청보다 앞서게 만들 수 있다.
     * @return 실제로 옮겼으면 {@code true}, 무시했으면 {@code false}
     */
    public boolean progress(AnalysisStage next, Instant at) {
        Objects.requireNonNull(next, "next must not be null");
        Objects.requireNonNull(at, "at must not be null");
        if (!next.reportableByWorker() || !IN_PROGRESS_STATUSES.contains(status)) {
            return false;
        }
        int current = AnalysisStage.parse(currentStage).map(AnalysisStage::order).orElse(-1);
        if (next.order() <= current) {
            return false;
        }
        this.status = STATUS_ANALYZING;
        this.currentStage = next.name();
        // 두 번째 단계로 곧장 들어온 분석도 시작 시각을 갖는다. 이미 있으면 덮지
        // 않는다 -- 처음 움직인 시각이 사용자가 기다린 시간의 기준이다.
        if (this.startedAt == null) {
            this.startedAt = at;
        }
        return true;
    }

    /**
     * The worker finished and the evidence has been written.
     *
     * <p>Only an in-progress job moves. A duplicate result event finds the job
     * already terminal and must not reopen it, and neither must a result that
     * arrives after the user cancelled.</p>
     *
     * @return false when the job was not in progress, so the caller can skip
     */
    public boolean succeed(Instant completedAt) {
        return finish(STATUS_SUCCEEDED, STAGE_COMPLETED, null, completedAt);
    }

    /** The analysis cannot be produced. {@code errorCode} is what the UI switches on. */
    public boolean fail(String errorCode, Instant completedAt) {
        return finish(STATUS_FAILED, STAGE_FAILED,
                Objects.requireNonNull(errorCode, "errorCode must not be null"), completedAt);
    }

    /**
     * 기여 판정 성공·실패와 무관하게 시도가 끝난 뒤 호출한다.
     *
     * <p>중복 event가 이 경계를 다시 지나도 처음 기록한 시각을 보존한다.</p>
     */
    public boolean markComputeReady(Instant readyAt) {
        if (!STATUS_SUCCEEDED.equals(status) || computeReadyAt != null) {
            return false;
        }
        computeReadyAt = Objects.requireNonNull(readyAt, "readyAt must not be null");
        return true;
    }

    private boolean finish(String status, String stage, String errorCode, Instant completedAt) {
        if (!IN_PROGRESS_STATUSES.contains(this.status)) {
            return false;
        }
        this.status = status;
        this.currentStage = stage;
        this.errorCode = errorCode;
        this.completedAt = Objects.requireNonNull(completedAt, "completedAt must not be null");
        return true;
    }

    @Override
    public String getId() {
        return analysisId;
    }

    @Override
    public boolean isNew() {
        return isNew;
    }

    @PostPersist
    @PostLoad
    void markPersisted() {
        this.isNew = false;
    }
}
