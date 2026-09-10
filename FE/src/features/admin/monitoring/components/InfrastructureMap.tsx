import { serverUpState } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { MonitoringView, ServerView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { Connection, ServerNode } from '@/features/admin/monitoring/model/topology'
import { cpuMemoryLevel } from '@/features/admin/monitoring/model/thresholds'
import { formatPercent, formatSeconds } from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue } from '@/features/admin/monitoring/ui/MetricValue'
import { UpDot } from '@/features/admin/monitoring/ui/StatusBadge'
import { monitoringDotState } from '@/features/admin/monitoring/model/monitoringState'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { Pill } from '@/shared/ui/Pill'

/**
 * Infrastructure Map · 티켓 S15P21E102-210. 이 화면의 중심 시각물이다.
 *
 * **여기에는 서버 이름도, 서비스 배치도, 개수도 없다.** 전부 topology config에서 온다
 * (`model/topology.config.ts`). EC2가 2대에서 3대가 되거나 Kafka가 데이터 서버로 옮겨가도
 * 이 파일은 바뀌지 않는다.
 *
 * 확정 디자인과 다른 점이 하나 있다. 디자인은 1174x372 박스에 카드를 픽셀 좌표로 놓고
 * SVG 선으로 잇는다. 그 좌표는 서버가 정확히 두 대일 때만 맞고, 세 대가 되면 선이
 * 허공을 가리킨다. 그래서 좌표 대신 격자와 띠로 옮겼다 — 왼쪽에서 오른쪽으로 흐르고
 * 아래에서 수집한다는 시각적 의미는 같고, 서버 수에는 종속되지 않는다.
 *
 * 상태 점은 Prometheus target UP/DOWN이 근거다. 컨테이너 단위 UP/DOWN을 주는 exporter가
 * 없어(`prometheus.yml`에 cAdvisor job이 없다) 서비스 칩은 호스트 서버의 상태를 따른다.
 * 확정 디자인의 각주도 같은 기준을 적어 두었다.
 */

const STREAM_TYPES = ['KAFKA_STREAM', 'HDFS_REPLICATION', 'SPARK_CONTROL'] as const

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

function ServerCard({ view, server }: { view: MonitoringView; server: ServerView }) {
  const up = serverUpState(view, server)
  const metrics = server.metrics

  return (
    <div className="rounded-[16px] border border-brand-line bg-[#F6F8FC] px-5 py-4">
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
          <ServiceChip key={service.id} service={service} up={up} />
        ))}
      </div>
    </div>
  )
}

/**
 * 흐름 띠.
 *
 * 디자인의 가운데 화살표에 해당한다. 애니메이션 점선 대신 화살표와 이름만 둔 이유는,
 * 움직이는 선은 데이터가 실제로 흐르고 있다고 말하는데 그것을 확인할 지표
 * (Kafka topic throughput)가 아직 없기 때문이다.
 */
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

/** 수집 바. 어떤 서버를 긁는지는 config의 `PROMETHEUS_SCRAPE` 연결 수로 드러난다. */
function ScrapeBar({ view }: { view: MonitoringView }) {
  const scrapeCount = view.connections.filter(
    (connection) => connection.type === 'PROMETHEUS_SCRAPE',
  ).length

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-[14px] border border-brand-line bg-white px-5 py-3.5 shadow-[0_8px_22px_rgba(25,47,81,0.06)]">
      <div>
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

      <span className="hidden h-7 w-px bg-brand-line sm:block" />

      <p className="text-[12.5px] leading-[1.4] text-brand-muted">
        <b className="font-[750] text-brand-ink-soft tabular-nums">
          {view.targets === null ? '—' : `${view.targets.up} / ${view.targets.total}`}
        </b>{' '}
        targets UP
        <br />
        scrape {formatSeconds(view.scrapeIntervalSeconds) ?? '—'}
      </p>

      {view.monitoring.dashboardLabel !== undefined && (
        <>
          <span className="hidden h-7 w-px bg-brand-line sm:block" />
          <div className="flex items-center gap-2">
            <span className="text-[14px] font-bold text-brand-ink-soft">
              {view.monitoring.dashboardLabel}
            </span>
            <Pill tone={view.links.grafanaUrl === null ? 'neutral' : 'accent'}>
              {view.links.grafanaUrl === null ? '링크 없음' : '링크 설정됨'}
            </Pill>
          </div>
        </>
      )}
    </div>
  )
}

export function InfrastructureMap({ view }: { view: MonitoringView }) {
  const streams = view.connections.filter((connection) =>
    STREAM_TYPES.some((type) => type === connection.type),
  )
  const scrapeInterval = formatSeconds(view.scrapeIntervalSeconds)

  return (
    <DataRegion
      eyebrow="INFRASTRUCTURE MAP"
      title={mapTitle(view)}
      hint={
        scrapeInterval === null
          ? 'Prometheus가 각 서버의 node metrics를 수집합니다.'
          : `Prometheus가 각 서버의 node metrics를 ${scrapeInterval} 간격으로 수집합니다.`
      }
      action={
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 pt-1.5 text-[12px] text-brand-muted">
          <LegendItem swatch="size-2 rounded-full bg-tone-success" label="정상" />
          <LegendItem swatch="size-2 rounded-full bg-tone-danger" label="중단" />
          <LegendItem swatch="size-2 rounded-full bg-tone-neutral" label="알 수 없음" />
        </div>
      }
    >
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

      <div className="mt-3">
        <ScrapeBar view={view} />
      </div>

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

      <PageFootnote>
        노드 상태는 Prometheus target UP/DOWN 기준입니다. 컨테이너 내부 지표를 주는
        exporter가 아직 없어 서비스 칩은 호스트 서버의 상태를 따릅니다.
        {view.replicationFactor === null
          ? ' HDFS 복제 계수는 확인된 설정값이 없어 표시하지 않습니다.'
          : ` HDFS 복제 계수 ${view.replicationFactor}.`}
      </PageFootnote>
    </DataRegion>
  )
}
