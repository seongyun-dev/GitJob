import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { serverUpState } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { MonitoringView, ServerView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { Connection, ServerNode } from '@/features/admin/monitoring/model/topology'
import { cpuMemoryLevel } from '@/features/admin/monitoring/model/thresholds'
import { formatPercent, formatSeconds } from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue } from '@/features/admin/monitoring/ui/MetricValue'
import { AdminBadge, UpDot } from '@/features/admin/monitoring/ui/StatusBadge'
import { monitoringDotState } from '@/features/admin/monitoring/model/monitoringState'
import { serviceUpState } from '@/features/admin/monitoring/model/serviceHealth'

/**
 * Infrastructure Map · 티켓 S15P21E102-210. 이 화면의 중심 시각물이다.
 *
 * **여기에는 서버 이름도, 서비스 배치도, 개수도 없다.** 전부 topology config에서 온다
 * (`model/topology.config.ts`). EC2가 2대에서 3대가 되거나 Kafka가 데이터 서버로 옮겨가도
 * 이 파일은 바뀌지 않는다.
 *
 * 배치는 두 갈래다.
 *   - **디자인형** (`xl` 이상 · 서버 2대 · 흐름 1개): 확정 디자인 `Admin Monitoring v2`의
 *     1174×372 박스를 그대로 옮겼다 — 카드 절대좌표(left/right 0 · top 34 · 380px), 가운데
 *     Kafka 필(top 58), 하단 중앙 Prometheus 바, 그리고 디자인 파일의 `mapLines()`를
 *     좌표째 포팅한 SVG(Kafka 트랙 · 화살표 · 흐르는 점선 · 수집 점선 곡선 · 상태 점).
 *     디자인이 데스크톱 전용(`min-width:1440px`)이라 박스가 들어가는 폭에서만 그린다.
 *   - **일반형** (그 아래 폭, 또는 서버 수·흐름 수가 다를 때): 격자. 서버가 3대가 되면
 *     디자인의 좌표는 허공을 가리키므로 좌표 대신 격자로 물러난다.
 *
 * SVG 색은 리터럴 hex다. `stroke`는 Tailwind 클래스를 받지 않아 `ResourceOverview`와 같은
 * 방식으로 문자열을 넘긴다. 값은 디자인 파일 것 그대로.
 *
 * 서버 상태 점은 Prometheus target UP/DOWN이 근거다. 서비스 칩은 overview가 실제로
 * 제공하는 서비스별 source만 사용하며, source가 없는 서비스는 회색 UNKNOWN으로 남긴다.
 */

const STREAM_TYPES = ['KAFKA_STREAM', 'HDFS_REPLICATION', 'SPARK_CONTROL'] as const

/** 카드 표면. `DataRegion`과 같은 값 — radius 18 · border · shadow. */
const CARD =
  'overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]'

/**
 * 디자인 파일 `mapLines()`의 좌표. 카드 380px 두 장이 1174px 박스 양 끝에 있을 때만 맞는다.
 *
 * `cardBottom`·`promTop`은 여기 없다. 카드 높이는 서비스 칩 수에 따라 바뀌고(티켓 313에서
 * 데이터 서버가 6개가 되며 한 줄 늘었다), 고정 좌표로 두면 수집 점이 카드 **안쪽**에 박힌다.
 * 아래 세 값은 실제로 잰 카드 높이에서 만든다.
 */
const MAP = { W: 1174, cy: 132, lx: 380, rx: 794, cardTop: 34 } as const

/** 디자인의 세로 여백 — 카드 아래에서 수집 바 위까지, 그리고 바 높이. */
const GAP = { cardToBar: 62, barHeight: 73 } as const

/** 디자인 기본값(카드 203px)일 때 원래 좌표가 나오는 최소 높이. */
const MIN_MAP_HEIGHT = 372

/** 디자인 파일의 DOT 팔레트. */
const DOT = { ok: '#219A67', down: '#D05D6D', unknown: '#B9C2CF' } as const

function dotColor(up: boolean | null): string {
  return up === null ? DOT.unknown : up ? DOT.ok : DOT.down
}

/**
 * 제목을 config에서 만든다.
 *
 * 디자인의 "서비스 서버 → Kafka 스트리밍 → 데이터 서버"를 문자열로 박으면 topology가
 * 바뀔 때 제목만 옛 구조를 주장한다. 흐름 연결이 하나면 그 양 끝과 이름으로 문장을
 * 만들고, 아니면 서버 이름을 나열한다.
 */
function mapTitle(view: MonitoringView): string {
  const streams = view.connections.filter((connection) =>
    STREAM_TYPES.some((type) => type === connection.type),
  )
  const names = new Map(view.servers.map((server) => [server.node.id, server.node.name]))

  const stream = streams.length === 1 ? streams[0] : undefined
  if (stream !== undefined) {
    const from = names.get(stream.from)
    const to = names.get(stream.to)
    if (from !== undefined && to !== undefined) {
      return `${from} → ${stream.label ?? '연결'} → ${to}`
    }
  }
  return view.servers.map((server) => server.node.name).join(' · ')
}

function LegendItem({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={swatch} />
      {label}
    </span>
  )
}

function ServiceChip({ service, up }: { service: ServerNode['services'][number]; up: boolean | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[9px] border border-brand-line bg-white px-2.5 py-1.5 text-[12.5px] font-bold text-brand-ink-soft">
      <UpDot up={up} label={service.label} />
      {service.label}
      <span className="font-evidence text-[10.5px] font-bold text-brand-faint">
        {service.tag}
      </span>
    </span>
  )
}

/** 서버 카드. 디자인 padding 18px 20px · radius 16 · #F6F8FC. */
function ServerCard({ view, server }: { view: MonitoringView; server: ServerView }) {
  const up = serverUpState(view, server)
  /*
    칩 하나하나의 근거 · 티켓 319. 살아 있는 DataNode·Worker 수는 이미 수집되고 있어
    (NameNode `/jmx`, Spark Master `/json/`) 그 두 칩을 회색으로 둘 이유가 없다.
    판정 규칙 자체는 `model/serviceHealth` 한 곳에 있다.
  */
  const serviceEvidence = {
    prometheusState: view.state,
    kafkaUp: view.kafka.up,
    hdfsUp: view.hdfs.up,
    sparkUp: view.spark.up,
    liveDataNodes: view.hdfs.liveDataNodes,
    aliveWorkers: view.spark.aliveWorkers,
  } as const
  const metrics = server.metrics

  return (
    <div className="rounded-[16px] border border-brand-line bg-[#F6F8FC] px-5 py-[18px]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint uppercase">
            {server.node.name}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <UpDot up={up} label={server.node.displayName} />
            <code className="font-evidence text-[18px] font-extrabold text-brand-ink">
              {server.node.displayName}
            </code>
          </div>
        </div>
        <div className="flex shrink-0 gap-3.5 text-right">
          <div>
            <p className="text-[11px] text-brand-faint">CPU</p>
            <MetricValue
              text={formatPercent(metrics?.cpuPercent ?? null)}
              level={cpuMemoryLevel(metrics?.cpuPercent ?? null)}
              size="sm"
            />
          </div>
          <div>
            <p className="text-[11px] text-brand-faint">MEM</p>
            <MetricValue
              text={formatPercent(metrics?.memoryPercent ?? null)}
              level={cpuMemoryLevel(metrics?.memoryPercent ?? null)}
              size="sm"
            />
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {server.node.services.map((service) => (
          <ServiceChip
            key={service.id}
            service={service}
            up={serviceUpState(service.id, serviceEvidence)}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * 가운데 흐름 필 — 디자인의 `Kafka Streaming` 알약(999px radius · #EAF1FF · #2F5EEB 12.5px/800)
 * 과 그 아래 캡션. 디자인형에서는 화살표를 SVG가 그리므로 `withArrow`를 끈다.
 */
function StreamPill({
  connection,
  view,
  withArrow,
}: {
  connection: Connection
  view: MonitoringView
  withArrow: boolean
}) {
  const names = new Map(view.servers.map((server) => [server.node.id, server.node.displayName]))
  const from = names.get(connection.from)
  const to = names.get(connection.to)

  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <span className="inline-flex items-center gap-2 rounded-full border border-brand-line-active bg-tone-accent-bg px-3.5 py-2 text-[12.5px] font-extrabold whitespace-nowrap text-brand-600">
        {connection.label ?? '연결'}
        {from !== undefined && to !== undefined && (
          <code className="font-evidence text-[11px] font-bold text-brand-muted">
            {from} → {to}
          </code>
        )}
      </span>
      {connection.caption !== undefined && (
        <span className="text-[11.5px] whitespace-nowrap text-brand-faint">{connection.caption}</span>
      )}
      {withArrow && (
        <span className="mt-1 hidden items-center text-brand-400 lg:inline-flex" aria-hidden>
          <span className="h-0.5 w-10 rounded-full bg-brand-line-active" />
          <span className="-ml-px h-0.5 w-10 rounded-full bg-brand-400" />
          <span className="ml-1 text-[14px] leading-none font-bold">→</span>
        </span>
      )}
    </div>
  )
}

/** 흐름 띠 — 일반형에서 카드 위에 두는 가로 띠. */
function StreamBand({ connection, view }: { connection: Connection; view: MonitoringView }) {
  const names = new Map(view.servers.map((server) => [server.node.id, server.node.displayName]))
  const from = names.get(connection.from)
  const to = names.get(connection.to)

  return (
    <div className="flex flex-wrap items-center justify-center gap-2 rounded-[12px] border border-brand-line-active bg-tone-accent-bg px-4 py-2.5 text-center">
      <span className="text-[12.5px] font-extrabold text-brand-600">
        {connection.label ?? '연결'}
      </span>
      {from !== undefined && to !== undefined && (
        <code className="font-evidence text-[11.5px] font-bold text-brand-muted">
          {from} → {to}
        </code>
      )}
      {connection.caption !== undefined && (
        <span className="text-[11.5px] text-brand-faint">{connection.caption}</span>
      )}
    </div>
  )
}

/**
 * 수집 바. 디자인은 지도 하단 중앙에 내용 폭으로 놓는다(`white-space:nowrap`).
 * 어떤 서버를 긁는지는 config의 `PROMETHEUS_SCRAPE` 연결 수로 드러난다.
 */
function ScrapeBar({ view }: { view: MonitoringView }) {
  const scrapeCount = view.connections.filter(
    (connection) => connection.type === 'PROMETHEUS_SCRAPE',
  ).length

  return (
    <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-[14px] border border-brand-line bg-white px-[22px] py-3.5 shadow-[0_8px_22px_rgba(25,47,81,0.06)] lg:w-auto lg:flex-nowrap lg:whitespace-nowrap">
      <div className="shrink-0">
        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
          MONITORING
        </p>
        <div className="mt-1 flex items-center gap-2">
          <UpDot up={monitoringDotState(view.state)} label={view.monitoring.label} />
          <span className="text-[15px] font-[750] text-brand-ink">
            {view.monitoring.label}
          </span>
          <span className="text-[12px] text-brand-faint">
            {scrapeCount}개 서버 수집 대상
          </span>
        </div>
      </div>

      <span className="hidden h-[30px] w-px shrink-0 bg-[#E8EDF4] sm:block" />

      <p className="shrink-0 text-[12.5px] leading-[1.4] text-brand-muted">
        <b className="font-[750] text-brand-ink-soft tabular-nums">
          {view.targets === null ? '—' : `${view.targets.up} / ${view.targets.total}`}
        </b>{' '}
        targets UP
        <br />
        scrape {formatSeconds(view.scrapeIntervalSeconds) ?? '—'}
      </p>

      {view.monitoring.dashboardLabel !== undefined && (
        <>
          <span className="hidden h-[30px] w-px shrink-0 bg-[#E8EDF4] sm:block" />
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-[14px] font-bold text-brand-ink-soft">
              {view.monitoring.dashboardLabel}
            </span>
            <AdminBadge tone={view.links.grafanaUrl === null ? 'neutral' : 'accent'}>
              {view.links.grafanaUrl === null ? '링크 없음' : '링크 설정됨'}
            </AdminBadge>
          </div>
        </>
      )}
    </div>
  )
}

/** 잰 카드 높이에서 만든 지도 좌표 · 티켓 S15P21E102-313. */
interface MapGeometry {
  height: number
  promTop: number
  leftBottom: number
  rightBottom: number
}

/**
 * 두 카드의 실제 높이를 재서 지도 좌표를 만든다.
 *
 * 카드 높이는 서비스 칩 수와 줄바꿈에 따라 바뀐다. 고정 좌표(디자인의 `cardBottom: 237`)를
 * 그대로 두면 카드가 그보다 길어지는 순간 수집 점이 카드 안쪽에 박히고, 점선 곡선도 카드
 * 뒤로 숨는다 — 데이터 서버 칩이 여섯 개가 되면서 실제로 그렇게 됐다.
 *
 * `useLayoutEffect`로 재는 이유는 그린 뒤에 재면 한 프레임 동안 선이 엉뚱한 자리에 있다가
 * 튀기 때문이다. 폭이 바뀌면 칩 줄바꿈이 달라져 높이도 바뀌므로 `ResizeObserver`로 따라간다.
 */
function useMapGeometry(): {
  geometry: MapGeometry
  leftRef: (node: HTMLDivElement | null) => void
  rightRef: (node: HTMLDivElement | null) => void
} {
  const nodes = useRef<{ left: HTMLDivElement | null; right: HTMLDivElement | null }>({
    left: null,
    right: null,
  })
  const [heights, setHeights] = useState({ left: 0, right: 0 })

  const measure = useCallback(() => {
    setHeights((previous) => {
      const left = nodes.current.left?.offsetHeight ?? 0
      const right = nodes.current.right?.offsetHeight ?? 0
      return previous.left === left && previous.right === right ? previous : { left, right }
    })
  }, [])

  const observer = useRef<ResizeObserver | null>(null)
  useLayoutEffect(() => {
    // 두 카드를 함께 본다. 한쪽만 줄바꿈이 달라져도 좌표가 바뀐다.
    const instance = new ResizeObserver(measure)
    observer.current = instance
    for (const node of [nodes.current.left, nodes.current.right]) {
      if (node !== null) {
        instance.observe(node)
      }
    }
    measure()
    return () => {
      instance.disconnect()
      observer.current = null
    }
  }, [measure])

  const attach = useCallback(
    (side: 'left' | 'right') => (node: HTMLDivElement | null) => {
      nodes.current[side] = node
      if (node !== null) {
        observer.current?.observe(node)
      }
      measure()
    },
    [measure],
  )

  const leftBottom = MAP.cardTop + heights.left
  const rightBottom = MAP.cardTop + heights.right
  const height = Math.max(
    MIN_MAP_HEIGHT,
    Math.max(leftBottom, rightBottom) + GAP.cardToBar + GAP.barHeight,
  )

  return {
    geometry: { height, promTop: height - GAP.barHeight, leftBottom, rightBottom },
    leftRef: attach('left'),
    rightRef: attach('right'),
  }
}

/**
 * 디자인 파일 `mapLines()`의 포팅. 좌표·두께·색·점선 간격·애니메이션까지 그대로다.
 * 바뀐 것은 mock 바인딩만 — 점 색은 실제 서버 UP 상태, 수집 간격 문구는 실제 값.
 * 왼쪽 점선 곡선은 디자인이 항상 회색이고 오른쪽만 경고 시 주황인데, 여기서는 둘 다
 * 서버 상태가 DOWN이면 붉게 그린다(경고 단계는 target UP/DOWN에 없다).
 */
function MapLines({
  leftUp,
  rightUp,
  scrapeInterval,
  geometry,
}: {
  leftUp: boolean | null
  rightUp: boolean | null
  scrapeInterval: string | null
  geometry: MapGeometry
}) {
  const { W, cy, lx, rx } = MAP
  const { height: H, promTop, leftBottom, rightBottom } = geometry
  const scrapeStroke = (up: boolean | null) => (up === false ? DOT.down : DOT.unknown)

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className="pointer-events-none absolute top-0 left-0 z-[1] overflow-visible"
      aria-hidden
    >
      <defs>
        <marker
          id="gj-map-arrow"
          viewBox="0 0 10 10"
          refX={8}
          refY={5}
          markerWidth={9}
          markerHeight={9}
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 Z" fill="#2F5EEB" />
        </marker>
      </defs>

      {/* Kafka 스트림: 트랙 + 파란 선 + 흐르는 점선 (디자인: solid = streaming) */}
      <line x1={lx} y1={cy} x2={rx - 10} y2={cy} stroke="#D7E4FF" strokeWidth={4} strokeLinecap="round" />
      <line
        x1={lx}
        y1={cy}
        x2={rx - 10}
        y2={cy}
        stroke="#5B8DFF"
        strokeWidth={2.5}
        strokeLinecap="round"
        markerEnd="url(#gj-map-arrow)"
      />
      <line
        x1={lx + 6}
        y1={cy}
        x2={rx - 26}
        y2={cy}
        stroke="#2F5EEB"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeDasharray="6 16"
        style={{ animation: 'gj-flow 1.4s linear infinite' }}
      />
      <circle cx={lx} cy={cy} r={5} fill="#fff" stroke={dotColor(leftUp)} strokeWidth={2} />
      <circle cx={rx} cy={cy} r={5} fill="#fff" stroke={dotColor(rightUp)} strokeWidth={2} />

      {/* Prometheus 수집 (점선): 바 상단에서 각 카드 아래 틈으로 */}
      <path
        d={`M${W / 2 - 150},${promTop} C${W / 2 - 150},${promTop - 34} 190,${promTop - 10} 190,${leftBottom + 8}`}
        fill="none"
        stroke={scrapeStroke(leftUp)}
        strokeWidth={1.5}
        strokeDasharray="4 5"
      />
      <path
        d={`M${W / 2 + 150},${promTop} C${W / 2 + 150},${promTop - 34} 984,${promTop - 10} 984,${rightBottom + 8}`}
        fill="none"
        stroke={scrapeStroke(rightUp)}
        strokeWidth={1.5}
        strokeDasharray="4 5"
      />
      <circle cx={190} cy={leftBottom + 8} r={4.5} fill="#fff" stroke={dotColor(leftUp)} strokeWidth={2} />
      <circle cx={984} cy={rightBottom + 8} r={4.5} fill="#fff" stroke={dotColor(rightUp)} strokeWidth={2} />
      <text
        x={W / 2}
        y={promTop - 18}
        textAnchor="middle"
        fontSize={11}
        fontWeight={600}
        fill="#98A4B5"
        fontFamily="inherit"
      >
        metrics scrape · {scrapeInterval ?? '—'} · node_exporter
      </text>
    </svg>
  )
}

export function InfrastructureMap({ view }: { view: MonitoringView }) {
  const { geometry, leftRef, rightRef } = useMapGeometry()
  const streams = view.connections.filter((connection) =>
    STREAM_TYPES.some((type) => type === connection.type),
  )
  const scrapeInterval = formatSeconds(view.scrapeIntervalSeconds)

  // 디자인 배치가 성립하는 유일한 조건. 카드 두 장 사이에 흐름 하나. 배열 인덱스를
  // 조건식 안에서 바로 쓰지 않고 const 로 꺼내 두는 이유는 타입이 `| undefined` 를 잃지
  // 않게 하기 위해서다 — 길이 검사로는 TypeScript 가 인덱스 결과를 좁혀 주지 않는다.
  const stream = streams.length === 1 ? streams[0] : undefined
  const [left, right] = view.servers
  const twoServerFlow =
    view.servers.length === 2 &&
    stream !== undefined &&
    left !== undefined &&
    right !== undefined

  return (
    <section className={CARD} aria-labelledby="infra-map-heading">
      {/* 헤더. 디자인 padding 24px 28px 0 · 제목 22px · 보조 13px · 범례 오른쪽. */}
      <div className="flex flex-wrap items-start justify-between gap-6 px-7 pt-6">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            INFRASTRUCTURE MAP
          </p>
          <h2
            id="infra-map-heading"
            className="mt-2 text-[22px] leading-[1.2] font-[750] tracking-[-0.03em] text-brand-ink"
          >
            {mapTitle(view)}
          </h2>
          <p className="mt-1.5 text-[13px] text-brand-faint">
            {scrapeInterval === null
              ? 'Prometheus가 각 서버의 node metrics를 수집합니다.'
              : `Prometheus가 각 서버의 node metrics를 ${scrapeInterval} 간격으로 수집합니다.`}
          </p>
        </div>
        {/* 디자인 범례 5종 중 실제로 그리는 것: 상태 점 3종 + 스트리밍 선 + 수집 점선. `주의`는 UP/DOWN에 단계가 없어 뺐다. */}
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 pt-1.5 text-[12px] text-brand-muted">
          <LegendItem swatch="size-2 rounded-full bg-tone-success" label="정상" />
          <LegendItem swatch="size-2 rounded-full bg-tone-danger" label="중단" />
          <LegendItem swatch="size-2 rounded-full bg-tone-neutral" label="알 수 없음" />
          <span className="hidden xl:contents">
            <LegendItem swatch="inline-block h-0.5 w-[18px] rounded-[1px] bg-brand-400" label="스트리밍" />
            <LegendItem
              swatch="inline-block h-0 w-[18px] border-t-2 border-dashed border-[#B9C2CF]"
              label="metrics 수집"
            />
          </span>
        </div>
      </div>

      <div className="px-7 pt-[18px]">
        {twoServerFlow ? (
          <>
            {/* 디자인형 — 1174×372 절대좌표 박스. 박스가 들어가는 폭(xl)에서만. */}
            <div
              className="relative mx-auto hidden w-[1174px] xl:block"
              style={{ height: geometry.height }}
            >
              <div ref={leftRef} className="absolute top-[34px] left-0 w-[380px]">
                <ServerCard view={view} server={left} />
              </div>
              <div ref={rightRef} className="absolute top-[34px] right-0 w-[380px]">
                <ServerCard view={view} server={right} />
              </div>
              <MapLines
                leftUp={serverUpState(view, left)}
                rightUp={serverUpState(view, right)}
                scrapeInterval={scrapeInterval}
                geometry={geometry}
              />
              <div className="absolute top-[58px] left-1/2 z-[2] -translate-x-1/2">
                <StreamPill connection={stream} view={view} withArrow={false} />
              </div>
              <div className="absolute bottom-0 left-1/2 z-[2] -translate-x-1/2">
                <ScrapeBar view={view} />
              </div>
            </div>

            {/* 일반형 — xl 아래. 카드 · 필 · 카드 격자, 바는 아래 중앙. */}
            <div className="xl:hidden">
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-start lg:gap-4">
                <ServerCard view={view} server={left} />
                <div className="flex justify-center lg:pt-6">
                  <StreamPill connection={stream} view={view} withArrow />
                </div>
                <ServerCard view={view} server={right} />
              </div>
              <div className="mt-[18px] flex justify-center">
                <ScrapeBar view={view} />
              </div>
            </div>
          </>
        ) : (
          <>
            {streams.map((connection) => (
              <div key={connection.id} className="mb-3">
                <StreamBand connection={connection} view={view} />
              </div>
            ))}
            {/*
              열 수가 서버 수에서 나오므로 정적 클래스로 표현할 수 없다. `index.css`에 두려면
              가능한 서버 수마다 클래스를 만들어야 하는데, 그것은 이 컴포넌트가 서버 수를
              아는 것과 같다.
            */}
            <div
              className="grid gap-3 lg:gap-3.5"
              style={{
                gridTemplateColumns: `repeat(${Math.max(1, view.servers.length)}, minmax(0, 1fr))`,
              }}
            >
              {view.servers.map((server) => (
                <ServerCard key={server.node.id} view={view} server={server} />
              ))}
            </div>
            <div className="mt-[18px] flex justify-center">
              <ScrapeBar view={view} />
            </div>
          </>
        )}

        {/*
          config에 없는데 Prometheus가 알고 있는 서버. 감추지 않는다 — 서버가 추가됐는데
          topology config를 갱신하지 않은 상황이 정확히 여기서 드러나야 한다.
        */}
        {view.unmappedServers.length > 0 && (
          <div className="mt-3 rounded-[12px] border border-tone-caution bg-tone-caution-bg px-4 py-3">
            <p className="text-[12.5px] font-bold text-tone-caution">
              topology 설정에 없는 target {view.unmappedServers.length}개가 수집되고 있습니다.
            </p>
            <ul className="mt-1.5 flex flex-wrap gap-2">
              {view.unmappedServers.map((server) => (
                <li
                  key={server.instance}
                  className="font-evidence text-[11.5px] text-brand-muted"
                >
                  {server.instance}
                  {server.role === null ? '' : ` (role=${server.role})`}
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
              `features/admin/monitoring/model/topology.config.ts`에 서버를 추가하면 지도에
              함께 표시됩니다.
            </p>
          </div>
        )}
      </div>

      {/* 각주. 디자인 `padding 14px 28px 18px · border-top`. `FUTURE STATE` 태그는 디자인 파일의 자기 표기라 옮기지 않는다. */}
      <p className="mt-3.5 border-t border-[#E8EDF4] px-7 pt-3.5 pb-[18px] text-[12px] leading-[1.6] text-brand-faint">
        노드 상태는 Prometheus node-exporter target UP/DOWN 기준입니다. 서비스 칩은
        overview가 제공하는 실제 서비스 source만 사용하며, source가 없는 서비스는 UNKNOWN으로
        표시합니다.
        {view.replicationFactor === null
          ? ' HDFS 복제 계수는 확인된 설정값이 없어 표시하지 않습니다.'
          : ` HDFS 복제 계수 ${view.replicationFactor}.`}
      </p>
    </section>
  )
}
