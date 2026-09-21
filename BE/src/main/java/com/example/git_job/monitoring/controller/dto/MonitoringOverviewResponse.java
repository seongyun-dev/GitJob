package com.example.git_job.monitoring.controller.dto;

import java.time.Instant;
import java.util.List;

/**
 * Admin Monitoring 화면의 현재값 한 묶음 (S15P21E102-209).
 *
 * <p>엔드포인트를 {@code /servers}·{@code /targets}로 쪼개지 않았다. 화면이 한 번에 다
 * 그리는 값이라 나누면 요청만 늘고, 화면 어느 부분은 갱신됐고 어느 부분은 아닌 상태가
 * 생긴다. Server Detail 표와 Infrastructure Map의 상태 점은 모두 {@link #servers()}에서 나온다.</p>
 *
 * <p>수치가 {@code null}인 것과 0인 것은 다르다. {@code null}은 그 값을 아직 얻지 못했다는
 * 뜻이고, 화면은 숫자 대신 값 없음으로 그려야 한다. 0으로 채우면 "측정했더니 0"이라는
 * 거짓이 된다.</p>
 */
public record MonitoringOverviewResponse(
        Instant updatedAt,
        PrometheusStatus prometheus,
        List<ServerMetrics> servers,
        KafkaStatus kafka,
        HdfsStatus hdfs,
        SparkStatus spark,
        ServicesStatus services,
        DataStoreStatus dataStore,
        Coverage coverage,
        Links links
) {

    /**
     * Prometheus 자체의 상태.
     *
     * <p>실패도 200으로 내린다. 모니터링이 끊긴 것은 요청 실패가 아니라 운영자가 봐야 하는
     * 사실이고, 500으로 던지면 화면은 "모니터링이 끊겼다"와 "서버가 죽었다"를 구분할 수
     * 없다.</p>
     *
     * <p>{@code reachable} 하나로 끝내지 않고 {@link #state}를 함께 싣는다. 주소가 없는
     * 것과 닿지 않는 것과 응답이 이상한 것은 고칠 사람이 다르다.</p>
     *
     * <p>연결되지 않았으면 {@code targetsUp}·{@code targetsTotal}은 {@code null}이다.
     * 0으로 채우면 "target이 하나도 없다"는 다른 사실이 된다.</p>
     */
    public record PrometheusStatus(
            boolean reachable,
            PrometheusState state,
            Integer targetsUp,
            Integer targetsTotal,
            Integer scrapeIntervalSeconds
    ) {
        public static PrometheusStatus connected(int up, int total, int scrapeIntervalSeconds) {
            return new PrometheusStatus(
                    true, PrometheusState.CONNECTED, up, total, scrapeIntervalSeconds);
        }

        /** {@code state}는 CONNECTED가 아닌 값이어야 한다. */
        public static PrometheusStatus disconnected(PrometheusState state) {
            return new PrometheusStatus(false, state, null, null, null);
        }
    }

    /**
     * 서버 한 대의 현재 지표.
     *
     * <p>{@code instance}가 식별자다. {@code role}·{@code node}·{@code host}는 Prometheus
     * target 라벨에서 그대로 온다. 이 목록의 길이가 곧 서버 대수이며, 서버가 늘면 라벨만
     * 추가되고 이 계약은 바뀌지 않는다.</p>
     */
    public record ServerMetrics(
            String instance,
            String role,
            String node,
            String host,
            boolean up,
            Double cpuPercent,
            /** 확정 디자인 Server Detail의 "4 vCPU". */
            Integer cpuCores,
            Double memoryPercent,
            /** "6.6 / 16 GB"를 그리려면 비율만으로는 부족하다. */
            Long memoryUsedBytes,
            Long memoryTotalBytes,
            Double diskPercent,
            Long diskUsedBytes,
            Long diskTotalBytes,
            Double networkReceiveBytesPerSecond,
            Double networkTransmitBytesPerSecond
    ) {
    }

    /**
     * Kafka 처리 현황 (S15P21E102-261 Phase 1).
     *
     * <p>{@code up}은 kafka-exporter 도달 여부다. 붙어 있으면 topic 수·초당 유입 메시지·
     * consumer lag 합계를 함께 싣는다 — 이 값들이 있어 Data Platform의 Kafka 카드가
     * COLLECTED로 실수치를 그린다.</p>
     *
     * <p>{@code null}과 0은 다르다. exporter가 없으면 시계열이 없어 {@code null}이고("아직
     * 재보지 않음"), 값이 왔는데 0이면 실제로 0이다("밀린 메시지 없음"). 그래서 미도달 시
     * 값 자리를 {@code null}로 비운다.</p>
     */
    public record KafkaStatus(
            Boolean up,
            Integer topicCount,
            Double messagesInPerSecond,
            Long consumerLagTotal
    ) {
        public static KafkaStatus unknown() {
            return new KafkaStatus(null, null, null, null);
        }
    }

    /**
     * HDFS 현황 (S15P21E102-261 Phase 2).
     *
     * <p>{@code up}은 NameNode /jmx 를 옮기는 json-exporter 도달 여부다. 붙어 있으면 용량
     * (사용/전체/잔여 바이트)·전체 Block 수·Under-replicated Block 수·DataNode Live/Dead 수를
     * 함께 싣는다 — 이 값들이 있어 Data Platform의 HDFS 카드가 COLLECTED로 실수치를 그린다.</p>
     *
     * <p>{@code null}과 0은 다르다. exporter가 없으면 시계열이 없어 {@code null}이고, 값이
     * 왔는데 0이면 실제로 0이다(예: 방금 포맷한 클러스터의 Block 0). 미도달 시 값 자리를
     * {@code null}로 비운다.</p>
     */
    public record HdfsStatus(
            Boolean up,
            Long capacityUsedBytes,
            Long capacityTotalBytes,
            Long blocksTotal,
            Integer liveDataNodes,
            Integer deadDataNodes,
            Long capacityRemainingBytes,
            Long underReplicatedBlocks
    ) {
        public static HdfsStatus unknown() {
            return new HdfsStatus(null, null, null, null, null, null, null, null);
        }
    }

    /**
     * Spark 현황 (S15P21E102-261 Phase 3).
     *
     * <p>{@code up}은 Spark Master /json/ 을 옮기는 json-exporter 도달 여부다. 붙어 있으면
     * 살아 있는 Worker 수·Core(사용/전체)·Memory(사용/전체, MB)를 함께 싣는다 — 이 값들이
     * 있어 Data Platform의 Spark 카드가 COLLECTED로 실수치를 그린다.</p>
     *
     * <p>Application·실패율은 Master /json/의 배열이라 exporter 스칼라로 옮기지 않는다. 값을
     * 만들지 않고, 후속 작업(Spark PrometheusServlet)이 붙으면 그때 채운다. 미도달 시 값
     * 자리는 {@code null}이다.</p>
     */
    public record SparkStatus(
            Boolean up,
            Integer aliveWorkers,
            Integer coresTotal,
            Integer coresUsed,
            Long memoryTotalMb,
            Long memoryUsedMb
    ) {
        public static SparkStatus unknown() {
            return new SparkStatus(null, null, null, null, null, null);
        }
    }

    /**
     * 자체 exporter 지표가 없던 서비스들의 살아 있음 (S15P21E102-321).
     *
     * <p>{@code servers}·{@code kafka}·{@code hdfs}·{@code spark}가 수치를 싣는 것과 달리 이
     * 둘은 화면이 물어보는 것이 "지금 살아 있는가" 하나뿐이다. 수치가 없어 카드가 아니라
     * Infrastructure Map의 점 하나로 그려지고, 그래서 값도 {@code Boolean} 하나다.</p>
     *
     * <p>세 가지 상태를 구분한다. {@code true}는 성공 근거를 실제로 봤다는 뜻,
     * {@code false}는 health 실패를 봤다는 뜻, {@code null}은 <strong>근거가 없다</strong>는
     * 뜻이다. {@code null}을 {@code false}로 접으면 화면이 "아직 안 붙였다"를 "죽었다"로
     * 바꿔 말하게 되고, 그것은 운영자를 헛되이 부르는 거짓말이다. scrape job이 아직 없어
     * 시계열이 통째로 없는 경우가 정확히 여기에 해당한다.</p>
     *
     * <p>호스트 상태를 물려받지 않는다. node-exporter가 UP이라는 것은 두 <em>호스트</em>가
     * 살아 있다는 뜻이지 그 안의 Grafana가 살아 있다는 뜻이 아니다.</p>
     *
     * <p>Redis·Collector·C1 Archiver는 아직 여기 없다. 각자 운영 rollout이나 실행 검증이
     * 남아 있어 후속 작업으로 분리했고, 그동안 화면은 UNKNOWN으로 남는다 — 그것이 정확한
     * 표시다. 근거가 생기면 여기에 한 줄씩 는다.</p>
     */
    public record ServicesStatus(
            /** BE 프로세스 자신의 Actuator 집계. Prometheus와 무관하다. */
            Boolean backend,
            Boolean grafana
    ) {
        public static ServicesStatus unknown() {
            return new ServicesStatus(null, null);
        }

        /** Prometheus가 끊겨도 BE 자신의 상태는 안다. 나머지는 물어볼 곳이 없다. */
        public static ServicesStatus backendOnly(Boolean backend) {
            return new ServicesStatus(backend, null);
        }
    }

    /**
     * DB 적재 현황 (S15P21E102-261 Phase 4).
     *
     * <p>수집 파이프라인의 산출물 중 Postgres에 쌓이는 것 — 기술 목록·기술 후보·분석 요청
     * 건수다. HDFS·Spark·Kafka와 달리 Prometheus scrape 대상이 아니라 BE가 자기 DB를 직접
     * 세어 낸다(배치가 만드는 값이라 scrape할 장기 exporter가 없다).</p>
     *
     * <p>개별 count가 실패하면 그 값만 {@code null}이다. {@code null}과 0은 다르다 —
     * {@code null}은 세지 못했다는 뜻, 0은 실제로 0건이다.</p>
     */
    public record DataStoreStatus(
            Long technologyCount,
            Long technologyCandidateCount,
            Long analysisJobCount,
            /*
             * 유효시간을 넘긴 진행 중 분석 수 (S15P21E102-136).
             *
             * 0이 아니면 워커가 죽었거나 요청이 Kafka에 닿지 못하고 있다는 뜻이다.
             * StaleAnalysisReaper가 이들을 종료시키므로 정상 배포에서는 곧 0으로
             * 돌아온다 -- 계속 0이 아니면 reaper 자신이 돌지 않는 것이다.
             *
             * 이 숫자를 넣는 이유는 2026-09 장애에서 분석이 49시간 멈춰 있는 것을
             * 아무도 몰랐기 때문이다. 세는 창은 reaper와 같은 activeWindow다.
             */
            Long staleAnalysisJobCount
    ) {
        public static DataStoreStatus unknown() {
            return new DataStoreStatus(null, null, null, null);
        }
    }

    /**
     * 어떤 범위가 실제로 수집되고 있는지.
     *
     * <p>이 필드가 있는 이유는 화면이 "값이 0"과 "아직 수집하지 않음"을 구분해야 하기
     * 때문이다. HDFS/Spark 기본 exporter 지표는 현재 수집 대상이지만, Spark
     * application/executor, Collector business counter, Kafka topic business 지표는 아직
     * 별도 exposition endpoint나 exporter가 없다. 값을 만들지 않고 상태만 내린다.</p>
     */
    public record Coverage(
            CoverageState hdfs,
            CoverageState spark,
            CoverageState collector,
            CoverageState kafkaBusiness
    ) {
        /** 현재 상태. exporter가 붙으면 해당 필드만 COLLECTED로 바뀐다. */
        public static Coverage current() {
            return new Coverage(
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED);
        }
    }

    /**
     * Grafana·Prometheus 상세 화면 링크.
     *
     * <p>서버 설정에서만 온다. 관리자망 주소를 FE 번들에 넣지 않기 위해서이고,
     * 미설정이면 {@code null}이라 화면은 눌러도 아무 일 없는 링크를 그리지 않는다.</p>
     */
    public record Links(String grafanaUrl, String prometheusUrl) {
    }
}
