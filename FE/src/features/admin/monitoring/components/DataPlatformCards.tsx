import type { MonitoringOverview } from '@/features/admin/monitoring/api/monitoringApi'
import type { CoverageState } from '@/features/admin/monitoring/model/monitoringState'
import { AdminBadge } from '@/features/admin/monitoring/ui/StatusBadge'

/**
 * Data Platform · 티켓 S15P21E102-210.
 * Kafka 실지표 S15P21E102-261 Phase 1, HDFS 실지표 Phase 2.
 *
 * 이 섹션의 요점은 **"서비스가 준비되지 않음"과 "상세 지표가 아직 연결되지 않음"을
 * 구분해 보여주는 것**이다. HDFS·Spark 기본 지표는 json-exporter가 연결되면 실수치를
 * 그리고, 고급 지표와 Collector business counter는 별도 source가 없어 준비 상태로 둔다.
 * 그래서 카드는 서비스가 죽었다고 말하지 않고, 무엇이 연결되면 무엇이 보일지를 말한다.
 *
 * 상태는 `overview.coverage`가 준다(BE 계약). 화면이 판단하지 않는다. exporter가 붙어
 * `COLLECTED`가 오면 카드가 실수치를 그린다. **Kafka(kafka-exporter)·HDFS·Spark
 * (json-exporter)는 기본 실수치를 그리고**, Collector는 DB source로 판단한다.
 *
 * 숫자 자리에 값을 만들지 않는다. `COLLECTED`가 아니면 `N/A`이고, `COLLECTED`라도 개별
 * 값이 `null`이면 `—`다 — 0(실제로 0)과 "값 없음"을 구분한다.
 */

/** `0.066` → `0.07`, `12.3` → `12.3`, `340` → `340`. 규모에 따라 자릿수를 줄인다. */
function formatRate(value: number | null): string {
  if (value === null) {
    return '—'
  }
  if (value >= 100) {
    return String(Math.round(value))
  }
  if (value >= 10) {
    return value.toFixed(1)
  }
  return value.toFixed(2)
}

/** 정수 개수/건수. `null`이면 `—`(0으로 채우지 않는다). */
function formatInt(value: number | null): string {
  return value === null ? '—' : value.toLocaleString()
}

/** `3243303530496` → `3.2TB`. 단위 환산은 1000 기준(용량 표기와 맞춘다). */
function formatBytesCompact(bytes: number | null): string {
  if (bytes === null) {
    return '—'
  }
  const tera = 1e12
  const giga = 1e9
  const mega = 1e6
  if (bytes >= tera) {
    return `${(bytes / tera).toFixed(1)}TB`
  }
  if (bytes >= giga) {
    return `${(bytes / giga).toFixed(1)}GB`
  }
  if (bytes >= mega) {
    return `${(bytes / mega).toFixed(1)}MB`
  }
  return `${bytes}B`
}

/** 사용률(%). 한쪽이라도 없거나 전체가 0이면 `—`. */
function capacityPercent(used: number | null, total: number | null): string {
  if (used === null || total === null || total === 0) {
    return '—'
  }
  return `${Math.round((used / total) * 100)}%`
}

const PLATFORMS: readonly {
  key: keyof MonitoringOverview['coverage']
  name: string
  /** COLLECTED일 때 카드 하단에 적을 수집원(그대로 노출). */
  source: string
  prerequisite: string
  willShow: string
}[] = [
  {
    key: 'hdfs',
    name: 'HDFS',
    source: 'json-exporter(NameNode JMX) 실시간 수집',
    prerequisite: 'NameNode JMX exporter 연결 후',
    willShow: '용량 · Block · Under-replicated · DataNode 상태',
  },
  {
    key: 'spark',
    name: 'Spark',
    source: 'json-exporter(Master /json/) 실시간 수집',
    prerequisite: 'Spark Master JSON exporter 연결 후',
    willShow: 'Worker · Core · Memory',
  },
  {
    // collector 슬롯을 "데이터 적재"로 쓴다. collector 산출물은 Kafka/HDFS로 흐르고
    // Postgres에는 기술·분석 도메인이 쌓이므로, 여기서는 BE가 DB를 직접 센 적재 건수를 낸다.
    key: 'collector',
    name: '데이터 적재',
    source: 'BE · DB 적재 기준',
    prerequisite: '수집 파이프라인 적재 후',
    willShow: '기술 · 기술 후보 · 분석 요청',
  },
  {
    key: 'kafkaBusiness',
    name: 'Kafka Topic',
    source: 'kafka-exporter 실시간 수집',
    prerequisite: 'topic 지표 연동 후',
    willShow: '처리량 · Consumer lag',
  },
]

function CoverageBadge({ state }: { state: CoverageState }) {
  if (state === 'COLLECTED') {
    return <AdminBadge tone="success">COLLECTED</AdminBadge>
  }
  return <AdminBadge tone="neutral">PREPARING</AdminBadge>
}

/** 값이 들어오지 않은 카드의 자리. 점선 테두리가 "아직 없음"을 말한다. */
function EmptyMetric() {
  return (
    <div className="mt-3.5 grid flex-1 place-content-center rounded-[12px] border border-dashed border-brand-box px-4 py-4 text-center">
      <div className="inline-flex gap-1">
        {[0, 1, 2].map((index) => (
          <span key={index} className="h-1.5 w-4.5 rounded-sm bg-[#E4E9F1]" />
        ))}
      </div>
      <p className="mt-2 text-[22px] font-extrabold tracking-[-0.04em] text-brand-faint">N/A</p>
    </div>
  )
}

/**
 * 라벨 · 값 · 단위 한 줄. COLLECTED 카드가 세 줄에서 다섯 줄로 쓴다.
 *
 * 값이 줄바꿈하지 않는 것이 이 줄의 규칙이다 · 티켓 S15P21E102-313. 열 폭이 200px 남짓이라
 * `233,655개`·`2 / 3core`처럼 긴 값이 들어오면 두 줄이 되어 줄 높이가 카드마다 달라졌다.
 * 값은 붙여 두고, 자리가 모자라면 **라벨**이 줄어든다 — 라벨은 무엇을 재는지 알려 주는
 * 말이라 잘려도 읽히지만, 숫자는 잘리면 다른 값이 된다.
 *
 * 높이를 못 박는 이유도 같다. 값이 길어지거나 `—`로 비어도 줄 높이가 흔들리지 않아야
 * 카드 네 장의 눈금이 서로 맞는다.
 */
function StatRow({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="flex h-[39px] items-center justify-between gap-2 rounded-[10px] bg-[#F6F8FC] px-3">
      <span className="min-w-0 truncate text-[12px] font-medium text-brand-muted">{label}</span>
      <span className="shrink-0 text-[15px] font-extrabold tracking-[-0.02em] whitespace-nowrap text-brand-ink tabular-nums">
        {value}
        <span className="ml-1 text-[10px] font-semibold text-brand-faint">{unit}</span>
      </span>
    </div>
  )
}

/** Kafka 실지표(Phase 1). 개별 값이 `null`이면 그 줄만 `—`. */
function KafkaMetrics({ kafka }: { kafka: MonitoringOverview['kafka'] }) {
  return (
    <div className="mt-3.5 flex-1 space-y-2">
      <StatRow label="처리량" value={formatRate(kafka.messagesInPerSecond)} unit="msg/s" />
      <StatRow label="Consumer lag" value={formatInt(kafka.consumerLagTotal)} unit="msg" />
      <StatRow label="Topic" value={formatInt(kafka.topicCount)} unit="개" />
    </div>
  )
}

/** `2048`(MB) → `2` 또는 `1.5`. GB로 환산(1024 기준, JVM 메모리라 2진 단위). */
function mbToGb(mb: number): string {
  const gb = mb / 1024
  return gb < 10 ? gb.toFixed(1).replace(/\.0$/, '') : String(Math.round(gb))
}

/** Spark 실지표(Phase 3). Worker 수, Core 사용/전체, Memory 사용/전체(GB). */
function SparkMetrics({ spark }: { spark: MonitoringOverview['spark'] }) {
  const cores =
    spark.coresUsed === null || spark.coresTotal === null
      ? '—'
      : `${spark.coresUsed} / ${spark.coresTotal}`
  const memory =
    spark.memoryUsedMb === null || spark.memoryTotalMb === null
      ? '—'
      : `${mbToGb(spark.memoryUsedMb)} / ${mbToGb(spark.memoryTotalMb)}`
  return (
    <div className="mt-3.5 flex-1 space-y-2">
      <StatRow label="Worker" value={formatInt(spark.aliveWorkers)} unit="개" />
      <StatRow label="Core" value={cores} unit="core" />
      <StatRow label="Memory" value={memory} unit="GB" />
    </div>
  )
}

/** DB 적재 현황(Phase 4). BE가 Postgres를 직접 센 건수 — Prometheus 경유 아님. */
function DataStoreMetrics({ dataStore }: { dataStore: MonitoringOverview['dataStore'] }) {
  return (
    <div className="mt-3.5 flex-1 space-y-2">
      <StatRow label="기술" value={formatInt(dataStore.technologyCount)} unit="개" />
      <StatRow label="기술 후보" value={formatInt(dataStore.technologyCandidateCount)} unit="개" />
      <StatRow label="분석 요청" value={formatInt(dataStore.analysisJobCount)} unit="건" />
    </div>
  )
}

/** HDFS 실지표(Phase 2). 용량은 사용률 + 전체 용량, DataNode는 Live 수와 Down 여부. */
function HdfsMetrics({ hdfs }: { hdfs: MonitoringOverview['hdfs'] }) {
  const dataNode = hdfs.liveDataNodes === null ? '—' : String(hdfs.liveDataNodes)
  const dataNodeUnit =
    hdfs.deadDataNodes !== null && hdfs.deadDataNodes > 0
      ? `개 · ${hdfs.deadDataNodes} down`
      : '개 정상'
  return (
    <div className="mt-3.5 flex-1 space-y-2">
      <StatRow
        label="용량"
        value={capacityPercent(hdfs.capacityUsedBytes, hdfs.capacityTotalBytes)}
        unit={`/ ${formatBytesCompact(hdfs.capacityTotalBytes)}`}
      />
      <StatRow label="여유" value={formatBytesCompact(hdfs.capacityRemainingBytes)} unit="" />
      <StatRow label="Block" value={formatInt(hdfs.blocksTotal)} unit="개" />
      <StatRow label="Under-rep" value={formatInt(hdfs.underReplicatedBlocks)} unit="개" />
      <StatRow label="DataNode" value={dataNode} unit={dataNodeUnit} />
    </div>
  )
}

export function DataPlatformCards({
  coverage,
  kafka,
  hdfs,
  spark,
  dataStore,
}: {
  coverage: MonitoringOverview['coverage']
  kafka: MonitoringOverview['kafka']
  hdfs: MonitoringOverview['hdfs']
  spark: MonitoringOverview['spark']
  dataStore: MonitoringOverview['dataStore']
}) {
  const states = Object.values(coverage)
  const collectedCount = states.filter((state) => state === 'COLLECTED').length
  const hasPreparing = collectedCount < states.length
  const subtitle =
    collectedCount === 0
      ? '서비스는 동작 중 · 상세 지표 수집 전'
      : hasPreparing
        ? '일부 지표 수집 중 · 나머지 수집 전'
        : '전체 지표 수집 중'

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 px-1">
        <h2 className="text-[18px] font-[750] tracking-[-0.03em] text-brand-ink">
          Data Platform
        </h2>
        <span className="text-[12.5px] text-brand-faint">{subtitle}</span>
      </div>

      <div className="gj-mon-platforms">
        {PLATFORMS.map((platform) => {
          const state = coverage[platform.key]
          const collected = state === 'COLLECTED'
          return (
            <div
              key={platform.key}
              /*
                세로 flex 인 것은 카드마다 지표 줄 수가 다르기 때문이다 · 티켓 S15P21E102-313.
                HDFS 는 다섯 줄, 나머지는 세 줄, PREPARING 은 `N/A` 블록 하나다. 지표 블록이
                남는 높이를 먹어야 수집원 각주가 네 장 모두 카드 바닥에 맞춰 선다 — 그러지
                않으면 각주가 카드마다 다른 높이에 떠서 네 장이 서로 다른 물건처럼 보인다.
                카드 높이 자체는 grid 가 이미 맞춘다.
              */
              className="flex flex-col rounded-[18px] border border-brand-line bg-white px-[22px] py-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
            >
              {/*
                머리 높이를 두 줄로 못 박는다. 열 폭이 200px 남짓이라 배지(86px)를 빼면 이름에
                70px 남짓만 남고, `데이터 적재`·`Kafka Topic` 만 두 줄이 되어 카드마다 머리
                높이가 27px 과 42px 로 갈렸다. 항상 두 줄 자리를 두면 이름이 길어져도 아래
                지표가 밀리지 않는다.

                이름을 자르지 않는 이유는 그것이 카드의 정체이기 때문이다. 대신 배지를
                `shrink-0` 으로 고정해 이름이 먼저 접히게 한다.
              */}
              <div className="flex min-h-[42px] items-start justify-between gap-2.5">
                <span className="text-[14px] leading-[1.5] font-[750] break-keep text-brand-ink">
                  {platform.name}
                </span>
                <span className="shrink-0">
                  <CoverageBadge state={state} />
                </span>
              </div>

              {collected && platform.key === 'kafkaBusiness' ? (
                <KafkaMetrics kafka={kafka} />
              ) : collected && platform.key === 'hdfs' ? (
                <HdfsMetrics hdfs={hdfs} />
              ) : collected && platform.key === 'spark' ? (
                <SparkMetrics spark={spark} />
              ) : collected && platform.key === 'collector' ? (
                <DataStoreMetrics dataStore={dataStore} />
              ) : (
                <EmptyMetric />
              )}

              <p className="mt-3 text-[12px] leading-[1.55] text-brand-faint">
                {collected ? (
                  <b className="font-bold text-brand-muted">{platform.source}</b>
                ) : (
                  <>
                    <b className="font-bold text-brand-muted">{platform.prerequisite}</b>
                    <br />
                    {platform.willShow}
                  </>
                )}
              </p>
            </div>
          )
        })}
      </div>

      {/*
        안내문은 현재 상태에 맞춘다. PREPARING 카드가 하나라도 있으면 그 뜻을 설명하고,
        전부 COLLECTED면 수집원과 값 표기 규칙을 안내한다. CoverageState는 COLLECTED/
        NOT_COLLECTED 둘뿐이라 NO_DATA/FAILED 는 말하지 않는다(있지도 않은 상태를 주장하지 않음).
      */}
      <p className="mt-3 px-1.5 text-[12px] leading-[1.6] text-brand-faint">
        {hasPreparing ? (
          <>
            PREPARING은 수집 파이프라인이 아직 연결되지 않은 상태입니다. 서비스가 중단된
            것이 아니며, 컨테이너·서버의 동작 여부는 Infrastructure Map에서 확인합니다.
          </>
        ) : (
          <>
            모든 지표를 수집 중입니다 — HDFS·Spark·Kafka는 Prometheus 실시간, 데이터 적재는
            DB 기준입니다. 값 없음(—)과 0은 구분해 표시하며, 컨테이너·서버의 동작 여부는
            Infrastructure Map에서 확인합니다.
          </>
        )}
      </p>
    </section>
  )
}
