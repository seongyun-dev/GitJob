package com.example.git_job.analysis.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.domain.AnalysisStage;
import com.example.git_job.analysis.event.RepositoryAnalysisProgressEvent;
import com.example.git_job.analysis.event.RepositoryAnalysisProgressPayload;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import java.time.Instant;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 진행 이벤트 하나를 {@code analysis_job} 에 반영한다.
 *
 * <p>{@link AnalysisResultService} 와 나눠 둔 이유는 트랜잭션의 크기가 다르기
 * 때문이다. 결과 적용은 근거 수천 건을 쓰지만 여기는 한 행의 두 컬럼이다. 같은
 * 서비스에 두면 표시용 갱신이 결과 트랜잭션의 잠금 시간을 물려받는다.</p>
 *
 * <p>판단은 전부 {@link AnalysisJob#progress} 에 있다. 여기는 이벤트를 풀어
 * 넘기고 무슨 일이 있었는지 남기는 일만 한다.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisProgressService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisProgressService.class);

    private final AnalysisJobRepository jobs;

    /** 무슨 일이 있었는지. 호출부가 로그로 남기고 테스트가 단언한다. */
    public enum Applied {
        /** 단계가 실제로 바뀌었다. */
        MOVED,
        /** 잡은 찾았지만 옮기지 않았다 -- 이미 종료됐거나 뒤로 가는 단계다. */
        IGNORED,
        /** 이 서비스가 모르는 분석이다. */
        UNKNOWN_JOB,
        /** 이 코드가 모르는 단계이거나, 진행 토픽으로 올 수 없는 단계다. */
        UNKNOWN_STAGE
    }

    @Transactional
    public Applied apply(RepositoryAnalysisProgressEvent event) {
        RepositoryAnalysisProgressPayload payload = event.payload();

        // 단계부터 본다. 모르는 단계면 잡을 읽을 이유가 없다.
        Optional<AnalysisStage> parsed = AnalysisStage.parse(payload.stage());
        if (parsed.isEmpty() || !parsed.get().reportableByWorker()) {
            // 워커가 우리보다 새 버전이면 정상적으로 일어나는 일이다. 배포 순서를
            // 강제하지 않기로 했으므로 경고가 아니라 정보로 남긴다.
            log.info("Progress stage not handled here: stage={}, analysisId={}, eventId={}",
                    payload.stage(), payload.analysisId(), event.eventId());
            return Applied.UNKNOWN_STAGE;
        }

        AnalysisJob job = jobs.findById(payload.analysisId()).orElse(null);
        if (job == null) {
            // 재시도해도 생기지 않는다. 결과 경로와 같은 판단으로 메시지를 소비한다.
            log.warn("Progress for unknown analysis: analysisId={}, eventId={}",
                    payload.analysisId(), event.eventId());
            return Applied.UNKNOWN_JOB;
        }

        if (!job.progress(parsed.get(), Instant.now())) {
            // 흔한 일이다 -- 중복 배달과 순서 역전은 이 토픽의 정상 동작에 속한다.
            log.debug("Progress ignored: analysisId={}, status={}, stage={}, incoming={}",
                    job.getAnalysisId(), job.getStatus(), job.getCurrentStage(), payload.stage());
            return Applied.IGNORED;
        }

        jobs.save(job);
        log.info("Analysis progressed: analysisId={}, stage={}, traceId={}",
                job.getAnalysisId(), job.getCurrentStage(), event.traceId());
        return Applied.MOVED;
    }
}
