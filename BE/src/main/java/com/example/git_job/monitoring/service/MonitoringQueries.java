package com.example.git_job.monitoring.service;

import com.example.git_job.monitoring.config.MonitoringProperties;
import org.springframework.stereotype.Component;

/**
 * 화면이 쓰는 PromQL 전부 (S15P21E102-209).
 *
 * <p>여기 있는 질의는 새로 만든 것이 아니라 S15P21E102-205가 서버에서 검증해 커밋한
 * {@code Infra/monitoring/grafana/dashboards/gitjob-system-monitoring.json}의 식을 옮긴
 * 것이다. 같은 값을 두 곳에서 다르게 계산하지 않으려는 것이며, 대시보드와 화면의 숫자가
 * 어긋나면 둘 중 하나가 틀렸다는 뜻이 된다.</p>
 *
 * <p>대시보드에 없고 여기 추가한 것은 세 개다 — {@link #cpuCores()},
 * {@link #memoryTotalBytes()}, {@link #memoryAvailableBytes()}. 확정 디자인의 Server
 * Detail이 "4 vCPU", "6.6 / 16 GB"를 표시하는데 비율만으로는 그릴 수 없어서다. 셋 다
 * S15P21E102-205 문서 3장이 수집 대상으로 확인한 metric family
 * ({@code node_cpu_seconds_total}, {@code node_memory_*})만 쓴다.</p>
 *
 * <p>여기 <em>없는</em> 것에도 이유가 있다. {@code node_load1}은 확정 디자인의 "load 0.9"에
 * 해당하지만 205 문서의 수집 확인 목록에 없어 넣지 않았다. 있을 것 같다는 추정으로 질의를
 * 만들면 빈 결과가 "부하 0"으로 읽힌다. disk I/O는 205가 수집하고 있지만 v2 화면에 그 값을
 * 쓰는 자리가 없어 넣지 않았다 — 수집 가능한 것과 이번 API가 제공할 것은 다르다.</p>
 *
 * <p>호스트명과 IP는 어디에도 없다. 셀렉터는 {@code cluster}·{@code role}·{@code instance}
 * 라벨만 쓴다. 서버를 늘릴 때 {@code Infra/monitoring/prometheus/targets/node-exporter.yml}에
 * target과 라벨만 추가하면 이 질의들이 그대로 새 서버를 포함하도록 설계된 계약이다
 * (S15P21E102-207의 2호스트 확장이 실제로 이 경로를 쓴다).</p>
 *
 * <p>{@code role}로 서비스/데이터 서버를 가르지 않는다. 서버 목록은 질의 결과의 라벨에서
 * 나오고, 어떤 role이 몇 대인지는 이 코드가 알지 않는다.</p>
 */
@Component
public class MonitoringQueries {

    /** 대시보드가 쓰는 rate 창. 15초 scrape 간격에서 5분은 결측 한두 번을 견딘다. */
    private static final String RATE_WINDOW = "5m";

    /**
     * root 파일시스템만 본다. 대시보드와 같은 기준이고, 컨테이너 overlay와 tmpfs를 합산하면
     * 같은 바이트가 여러 번 세어진다.
     */
    private static final String ROOT_FILESYSTEM = "mountpoint=\"/\",fstype!~\"tmpfs|overlay\"";

    private final String cluster;

    public MonitoringQueries(MonitoringProperties properties) {
        this.cluster = properties.getCluster();
    }

    /**
     * node-exporter target의 UP/DOWN. 서버 목록의 출처이기도 하다 — {@code role}·
     * {@code node}·{@code host}·{@code instance} 라벨이 이 결과에 실려 온다.
     */
    public String nodeUp() {
        return "up{job=\"node-exporter\"," + clusterSelector() + "}";
    }

    /** Kafka exporter 도달 여부. 브로커가 여러 대여도 하나라도 살아 있으면 1이다. */
    public String kafkaUp() {
        return "max(up{job=\"kafka-exporter\"," + clusterSelector() + "})";
    }

    /**
     * Topic 수 (S15P21E102-261 Phase 1). 파티션 metric을 {@code topic}으로 묶어 센다 —
     * 파티션 개수가 아니라 topic 개수다.
     */
    public String kafkaTopicCount() {
        return "count(count by (topic) (kafka_topic_partitions{" + clusterSelector() + "}))";
    }

    /**
     * 초당 유입 메시지 수. 파티션 current offset 증가율의 합이라 특정 topic이 아니라 클러스터
     * 전체 처리량이고, kafka-exporter의 offset metric만 쓴다.
     */
    public String kafkaMessagesInPerSecond() {
        return "sum(rate(kafka_topic_partition_current_offset{" + clusterSelector()
                + "}[" + RATE_WINDOW + "]))";
    }

    /**
     * Consumer lag 합계. exporter는 커밋 오프셋이 없는 파티션에 {@code -1}을 준다. clamp_min으로
     * 0 밑을 잘라 합계가 음수가 되지 않게 한다 — {@code -1}들의 합은 lag이 아니라 "측정 불가"라
     * "밀린 메시지 0"과 다르다.
     */
    public String kafkaConsumerLagTotal() {
        return "sum(clamp_min(kafka_consumergroup_lag{" + clusterSelector() + "}, 0))";
    }

    /**
     * HDFS json-exporter 도달 여부 (S15P21E102-261 Phase 2). NameNode /jmx 를 json-exporter가
     * 변환하고 Prometheus가 {@code job="hdfs"}로 scrape 한다. 값이 하나라도 살아 있으면 1이다.
     */
    public String hdfsUp() {
        return "max(up{job=\"hdfs\"," + clusterSelector() + "})";
    }

    public String hdfsCapacityUsedBytes() {
        return "max(hdfs_capacity_used_bytes{" + clusterSelector() + "})";
    }

    public String hdfsCapacityTotalBytes() {
        return "max(hdfs_capacity_total_bytes{" + clusterSelector() + "})";
    }

    public String hdfsCapacityRemainingBytes() {
        return "max(hdfs_capacity_remaining_bytes{" + clusterSelector() + "})";
    }

    public String hdfsBlocksTotal() {
        return "max(hdfs_blocks_total{" + clusterSelector() + "})";
    }

    public String hdfsUnderReplicatedBlocks() {
        return "max(hdfs_under_replicated_blocks{" + clusterSelector() + "})";
    }

    public String hdfsLiveDataNodes() {
        return "max(hdfs_live_datanodes{" + clusterSelector() + "})";
    }

    public String hdfsDeadDataNodes() {
        return "max(hdfs_dead_datanodes{" + clusterSelector() + "})";
    }

    /**
     * Spark Master json-exporter 도달 여부 (S15P21E102-261 Phase 3). Master /json/을
     * json-exporter가 변환하고 Prometheus가 {@code job="spark"}로 scrape 한다.
     */
    public String sparkUp() {
        return "max(up{job=\"spark\"," + clusterSelector() + "})";
    }

    public String sparkWorkersAlive() {
        return "max(spark_workers_alive{" + clusterSelector() + "})";
    }

    public String sparkCoresTotal() {
        return "max(spark_cores_total{" + clusterSelector() + "})";
    }

    public String sparkCoresUsed() {
        return "max(spark_cores_used{" + clusterSelector() + "})";
    }

    public String sparkMemoryTotalMb() {
        return "max(spark_memory_total_mb{" + clusterSelector() + "})";
    }

    public String sparkMemoryUsedMb() {
        return "max(spark_memory_used_mb{" + clusterSelector() + "})";
    }

    /**
     * Grafana 도달 여부 (S15P21E102-321).
     *
     * <p>Grafana가 스스로 내는 {@code /metrics}를 Prometheus가 scrape 한 결과다. 그 안의
     * 지표는 하나도 저장하지 않는다(prometheus.yml이 전부 drop 한다) — 필요한 것은
     * Prometheus가 직접 붙이는 {@code up} 하나뿐이다.</p>
     *
     * <p>job이 아직 등록되지 않았으면 결과가 <em>비어</em> 온다. 0이 아니라 빈 결과라는 것이
     * 중요하다 — 빈 결과는 "모른다", 0은 "재봤더니 닿지 않았다"다. 부르는 쪽이 둘을
     * 구분한다.</p>
     */
    public String grafanaUp() {
        return "max(up{job=\"grafana\"," + clusterSelector() + "})";
    }

    public String cpuPercent() {
        return "100 - (avg by (cluster, role, instance) (rate(node_cpu_seconds_total{"
                + clusterSelector() + ",mode=\"idle\"}[" + RATE_WINDOW + "])) * 100)";
    }

    /**
     * vCPU 수. {@code idle} mode의 시계열이 코어당 하나씩 있어 그 개수가 코어 수다.
     * 사용률과 같은 metric을 쓰므로 별도 수집 가정이 필요하지 않다.
     */
    public String cpuCores() {
        return "count by (cluster, role, instance) (node_cpu_seconds_total{"
                + clusterSelector() + ",mode=\"idle\"})";
    }

    public String memoryPercent() {
        return "100 * (1 - (node_memory_MemAvailable_bytes{" + clusterSelector()
                + "} / node_memory_MemTotal_bytes{" + clusterSelector() + "}))";
    }

    public String memoryTotalBytes() {
        return "node_memory_MemTotal_bytes{" + clusterSelector() + "}";
    }

    public String memoryAvailableBytes() {
        return "node_memory_MemAvailable_bytes{" + clusterSelector() + "}";
    }

    public String diskPercent() {
        return "100 * (1 - (node_filesystem_avail_bytes{" + rootFilesystemSelector()
                + "} / node_filesystem_size_bytes{" + rootFilesystemSelector() + "}))";
    }

    /** 용량 표시는 비율만으로 부족하다. 화면이 "488 GB / 800 GB"를 보여준다. */
    public String diskTotalBytes() {
        return "node_filesystem_size_bytes{" + rootFilesystemSelector() + "}";
    }

    public String diskAvailableBytes() {
        return "node_filesystem_avail_bytes{" + rootFilesystemSelector() + "}";
    }

    /** {@code lo}를 제외한다. 루프백을 더하면 내부 트래픽이 두 번 세어진다. */
    public String networkReceiveBytesPerSecond() {
        return ioRate("node_network_receive_bytes_total", clusterSelector() + ",device!~\"lo\"");
    }

    public String networkTransmitBytesPerSecond() {
        return ioRate("node_network_transmit_bytes_total", clusterSelector() + ",device!~\"lo\"");
    }

    private String ioRate(String metric, String selector) {
        return "sum by (cluster, role, instance) (rate(" + metric + "{" + selector
                + "}[" + RATE_WINDOW + "]))";
    }

    private String clusterSelector() {
        return "cluster=\"" + cluster + "\"";
    }

    private String rootFilesystemSelector() {
        return clusterSelector() + "," + ROOT_FILESYSTEM;
    }
}
