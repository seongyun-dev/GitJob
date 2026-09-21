package com.example.git_job.monitoring.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.service.AnalysisRequestProperties;
import com.example.git_job.analysis.store.AnalysisBatchStore;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.DataStoreStatus;
import java.time.Instant;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * DB에 실제로 적재된 데이터 건수 (S15P21E102-261 Phase 4).
 *
 * <p>Data Platform의 "데이터 적재" 카드가 쓴다. HDFS·Spark·Kafka는 exporter를 Prometheus가
 * scrape 하지만, 수집 파이프라인의 산출물(기술 레지스트리·후보·분석)은 <em>배치가 만들어
 * Postgres에 쌓는 값</em>이라 scrape 대상이 없다. 그래서 이 카드만 Prometheus가 아니라 BE가
 * 자기 DB를 직접 세어 실수치를 낸다.</p>
 *
 * <p>세는 대상은 코드에 고정된 테이블 이름뿐이라(사용자 입력 없음) SQL 주입 위험이 없다.
 * 개별 count가 실패하면 그 값만 {@code null}로 접고 나머지는 그대로 낸다 — 한 테이블 오류가
 * 카드 전체를 비우지 않게 한다. {@code null}과 0은 다르다(0은 실제로 0건).</p>
 */
@Slf4j
@Component
public class DataStoreMetrics {

    private final JdbcTemplate jdbc;
    private final AnalysisBatchStore batches;
    private final AnalysisRequestProperties analysisRequest;

    public DataStoreMetrics(JdbcTemplate jdbc, AnalysisBatchStore batches,
            AnalysisRequestProperties analysisRequest) {
        this.jdbc = jdbc;
        this.batches = batches;
        this.analysisRequest = analysisRequest;
    }

    public DataStoreStatus current() {
        return new DataStoreStatus(
                count("technology"),
                count("technology_candidate"),
                count("analysis_job"),
                staleAnalysisJobs());
    }

    /**
     * 유효시간을 넘긴 채 아직 진행 중인 분석 수.
     *
     * <p>세는 창은 {@code StaleAnalysisReaper}가 정리 기준으로 쓰는 것과 같은 값이다.
     * 다르면 화면의 숫자와 실제로 정리되는 대상이 어긋난다.</p>
     */
    private Long staleAnalysisJobs() {
        try {
            return batches.countStaleSince(AnalysisJob.IN_PROGRESS_STATUSES,
                    Instant.now().minus(analysisRequest.activeWindow()));
        } catch (DataAccessException e) {
            log.warn("멈춘 분석 count 실패: {}", e.getMessage());
            return null;
        }
    }

    private Long count(String table) {
        try {
            // table은 이 클래스가 고정한 상수 문자열이다(외부 입력 아님).
            return jdbc.queryForObject("SELECT count(*) FROM " + table, Long.class);
        } catch (DataAccessException e) {
            log.warn("데이터 적재 count 실패 (table={}): {}", table, e.getMessage());
            return null;
        }
    }
}
