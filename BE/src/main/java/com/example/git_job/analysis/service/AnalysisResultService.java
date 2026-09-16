package com.example.git_job.analysis.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.event.RepositoryAnalysisResultPayload;
import com.example.git_job.analysis.store.AnalysisEvidenceStore;
import com.example.git_job.analysis.store.AnalysisLineageStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import java.time.Instant;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Applies one analysis result: writes the evidence and closes the job.
 *
 * <p>The worker cannot do this itself. {@code analysis_job} and
 * {@code analysis_evidence} are mapped here and every deployment boots with
 * {@code ddl-auto=validate}, so a second writer in another language would make
 * each column change a two-repository migration. The result travels as an
 * event and this is where it lands.</p>
 *
 * <h2>Idempotency</h2>
 *
 * <p>Delivery is at-least-once, so the same result arrives more than once. The
 * job's own status is the marker: only an in-progress job is finished, and a
 * repeat finds it terminal and stops. That needs no extra table and gives the
 * cancel case the right answer for free — a result that lands after the user
 * cancelled must not reopen the job.</p>
 *
 * <p>Evidence and status move in one transaction. A finished job with no
 * evidence reads as "this repository uses nothing", which is a normal result
 * and therefore indistinguishable from the bug.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisResultService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisResultService.class);

    private final AnalysisJobRepository jobs;
    private final AnalysisEvidenceStore evidence;
    private final AnalysisLineageStore lineage;
    private final TechnologyCandidateStore candidates;

    /**
     * @return what happened, so the caller can log it and tests can assert on it
     */
    @Transactional
    public Applied apply(RepositoryAnalysisResultEvent event) {
        RepositoryAnalysisResultPayload payload = event.payload();
        AnalysisJob job = jobs.findById(payload.analysisId()).orElse(null);
        if (job == null) {
            // The worker analyzed something this service has no record of. Retrying
            // will not create it, so the message is consumed rather than replayed.
            log.warn("Result for unknown analysis: analysisId={}, eventId={}",
                    payload.analysisId(), event.eventId());
            return Applied.UNKNOWN_JOB;
        }

        Instant now = Instant.now();
        boolean moved = payload.failed()
                ? job.fail(payload.errorCode(), now)
                : job.succeed(now);
        if (!moved) {
            log.info("Result ignored, job already {}: analysisId={}, eventId={}",
                    job.getStatus(), payload.analysisId(), event.eventId());
            return Applied.ALREADY_TERMINAL;
        }

        // 판정 기준을 먼저 남긴다. 근거가 0건이어도 남아야 하는 값이라
        // 근거 저장과 분리했다 -- 근거 행에만 두면 "분석했지만 아는 기술이 없었다"가
        // "분석하지 않았다"와 구분되지 않고, 그 사용자는 C 계산에서 통째로 빠진다.
        int supported = lineage.record(payload.analysisId(), event.schemaVersion(), payload);

        int written = evidence.insertAll(payload.analysisId(), job.getUserId(),
                payload.registryVersion(), payload.evidence(), now);
        // The worker can only say what this repository declared. How many people
        // a candidate would serve is an aggregate across every user, so it is
        // computed here from the observations rather than sent in the event.
        int observed = candidates.record(payload.analysisId(), job.getUserId(),
                job.getRepositoryId(), payload.candidates(), now);
        jobs.save(job);

        log.info("Analysis closed: analysisId={}, status={}, schema={}, rulePack={},"
                        + " technologies={}, evidence={}, candidates={}, support={}, traceId={}",
                payload.analysisId(), job.getStatus(), event.schemaVersion(),
                payload.rulePackVersion(), payload.technologies().size(),
                written, observed, supported, event.traceId());
        return payload.failed() ? Applied.FAILED : Applied.SUCCEEDED;
    }

    public enum Applied { SUCCEEDED, FAILED, ALREADY_TERMINAL, UNKNOWN_JOB }

    /**
     * 기여 판정을 붙일 대상. {@link Applied#SUCCEEDED} 일 때만 값이 있다.
     *
     * <p>이 서비스가 직접 붙이지 않는 이유는 트랜잭션 경계 때문이다. 기여 판정은
     * GitHub 을 호출하는데, 그것이 느리거나 한도에 걸렸다고 이미 판정된 근거를
     * 되돌릴 이유가 없다.</p>
     */
    public AnalysisJob attributionTarget(RepositoryAnalysisResultEvent event, Applied applied) {
        if (applied != Applied.SUCCEEDED) {
            return null;
        }
        return jobs.findById(event.payload().analysisId()).orElse(null);
    }
}
