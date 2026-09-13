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
    /** Terminal. docs/fe/shared-api-contract.md §JobStatus. */
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STAGE_WAITING_FOR_WORKER = "WAITING_FOR_WORKER";
    public static final String STAGE_COMPLETED = "COMPLETED";
    public static final String STAGE_FAILED = "FAILED";

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
     * With an assigned ID Spring Data would treat every instance as detached and call
     * merge(), costing a SELECT before each insert. Persistable states the truth instead.
     */
    @Transient
    private boolean isNew = true;

    private AnalysisJob(String analysisId, Long userId, String repositoryId,
            String repositoryFullName, String branchName, String commitSha,
            Instant requestedAt) {
        this.analysisId = analysisId;
        this.userId = userId;
        this.repositoryId = repositoryId;
        this.repositoryFullName = repositoryFullName;
        this.branchName = branchName;
        this.commitSha = commitSha;
        this.requestedAt = requestedAt;
        this.status = STATUS_QUEUED;
        this.currentStage = STAGE_WAITING_FOR_WORKER;
    }

    /** Initial state of an accepted request. The worker owns every transition after this. */
    public static AnalysisJob queue(String analysisId, long userId, String repositoryId,
            String repositoryFullName, String branchName, String commitSha,
            Instant requestedAt) {
        return new AnalysisJob(
                Objects.requireNonNull(analysisId, "analysisId must not be null"),
                userId,
                Objects.requireNonNull(repositoryId, "repositoryId must not be null"),
                // 이름은 없어도 분석은 성립한다. 없으면 근거 링크만 만들지 못한다.
                repositoryFullName,
                Objects.requireNonNull(branchName, "branchName must not be null"),
                Objects.requireNonNull(commitSha, "commitSha must not be null"),
                Objects.requireNonNull(requestedAt, "requestedAt must not be null"));
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
