package com.example.git_job.compute.service;

import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/** 관리자에게만 노출되는 FAILED compute attempt dry-run/exact-CAS rearm 경계. */
@Service
public class AdminComputeAttemptService {

    private final ComputeSnapshotStore attempts;
    private final UserTargetStore targets;
    private final UserEvidenceAssembler evidence;

    public AdminComputeAttemptService(ComputeSnapshotStore attempts, UserTargetStore targets,
                                      UserEvidenceAssembler evidence) {
        this.attempts = attempts;
        this.targets = targets;
        this.evidence = evidence;
    }

    public RearmCheck dryRun(long userId, String targetKey, String evidenceVersion,
                             UUID expectedRunToken) {
        validateIdentity(userId, targetKey, evidenceVersion, expectedRunToken);
        return check(userId, targetKey, evidenceVersion, expectedRunToken,
                targets.find(userId));
    }

    private RearmCheck check(long userId, String targetKey, String evidenceVersion,
                             UUID expectedRunToken, Optional<Target> target) {
        Optional<ComputeAttempt> attempt = attempts.findAttempt(userId, targetKey,
                evidenceVersion);
        Assembled assembled = evidence.assemble(userId);
        boolean targetCurrent = target.map(value -> value.targetKey().equals(targetKey))
                .orElse(false);
        boolean evidenceCurrent = assembled.isReady()
                && evidenceVersion.equals(assembled.evidenceVersion());
        boolean tokenCurrent = attempt.map(value -> value.runToken().equals(expectedRunToken))
                .orElse(false);
        boolean terminal = attempt.map(ComputeAttempt::failed).orElse(false);
        return new RearmCheck(userId, targetKey, evidenceVersion, expectedRunToken,
                attempt.map(ComputeAttempt::status).orElse(null),
                attempt.map(ComputeAttempt::reason).orElse(null),
                attempt.map(ComputeAttempt::attemptCount).orElse(null),
                targetCurrent, evidenceCurrent, tokenCurrent, terminal,
                targetCurrent && evidenceCurrent && tokenCurrent && terminal,
                assembled.isReady() ? null : String.valueOf(assembled.unavailable()));
    }

    @Transactional(isolation = Isolation.SERIALIZABLE)
    public ComputeAttempt rearm(long userId, String targetKey, String evidenceVersion,
                                UUID expectedRunToken, long actorUserId, String reason) {
        if (reason == null || reason.isBlank() || reason.length() > 500) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "operator reason is required and must be at most 500 characters");
        }
        validateIdentity(userId, targetKey, evidenceVersion, expectedRunToken);
        // The target row lock and serializable evidence reads define one current-state
        // boundary for validation, attempt CAS, and audit insertion. A concurrent target
        // update waits; a concurrent evidence publication is ordered on one side of this
        // transaction instead of slipping between the validation and the CAS.
        RearmCheck check = check(userId, targetKey, evidenceVersion, expectedRunToken,
                targets.findForUpdate(userId));
        if (!check.eligible()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "FAILED attempt identity is stale or no longer current");
        }
        return attempts.rearmFailedAttempt(userId, targetKey, evidenceVersion,
                        expectedRunToken, actorUserId, reason, Instant.now())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.CONFLICT,
                        "FAILED attempt changed before rearm"));
    }

    private static void validateIdentity(long userId, String targetKey,
                                         String evidenceVersion, UUID expectedRunToken) {
        if (userId <= 0 || targetKey == null || targetKey.isBlank()
                || targetKey.length() > 200 || evidenceVersion == null
                || !evidenceVersion.matches("[0-9a-f]{64}") || expectedRunToken == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "exact attempt identity is invalid");
        }
    }

    public record RearmCheck(long userId, String targetKey, String evidenceVersion,
            UUID expectedRunToken, String status, String attemptReason, Integer attemptCount,
            boolean targetCurrent, boolean evidenceCurrent, boolean tokenCurrent,
            boolean terminal, boolean eligible, String unavailableReason) {
    }
}
