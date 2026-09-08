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
    public static final String STAGE_WAITING_FOR_WORKER = "WAITING_FOR_WORKER";

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
            String branchName, String commitSha, Instant requestedAt) {
        this.analysisId = analysisId;
        this.userId = userId;
        this.repositoryId = repositoryId;
        this.branchName = branchName;
        this.commitSha = commitSha;
        this.requestedAt = requestedAt;
        this.status = STATUS_QUEUED;
        this.currentStage = STAGE_WAITING_FOR_WORKER;
    }

    /** Initial state of an accepted request. The worker owns every transition after this. */
    public static AnalysisJob queue(String analysisId, long userId, String repositoryId,
            String branchName, String commitSha, Instant requestedAt) {
        return new AnalysisJob(
                Objects.requireNonNull(analysisId, "analysisId must not be null"),
                userId,
                Objects.requireNonNull(repositoryId, "repositoryId must not be null"),
                Objects.requireNonNull(branchName, "branchName must not be null"),
                Objects.requireNonNull(commitSha, "commitSha must not be null"),
                Objects.requireNonNull(requestedAt, "requestedAt must not be null"));
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
