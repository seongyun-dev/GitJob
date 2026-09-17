import type { ReactNode } from 'react'
import {
  averageAcrossServers,
  axisLabels,
  niceMax,
  sumAcrossServers,
} from '@/features/admin/monitoring/adapter/toChartData'
import type { MonitoringTimeseries } from '@/features/admin/monitoring/api/monitoringApi'
import { cpuMemoryLevel } from '@/features/admin/monitoring/model/thresholds'
import { LineChart, TimeAxis } from '@/features/admin/monitoring/ui/LineChart'
import { formatClock, formatPercent, throughput } from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue } from '@/features/admin/monitoring/ui/MetricValue'
import { DisconnectedStateCard } from '@/features/admin/monitoring/ui/StatusBadge'
import type { DisconnectedState } from '@/features/admin/monitoring/model/monitoringState'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Resource Overview · 티켓 S15P21E102-210.
 *
 * 확정 디자인의 두 카드에 대응한다 — CPU·Memory 겹친 선(전체 서버 평균)과 Network IN/OUT
 * (전체 서버 합산). 둘 다 최근 60분·5분 간격이며 그 범위는 BE가 정한다.
 *
 * 값을 못 받으면 빈 그래프를 그리지 않는다. 0으로 채운 평평한 선은 장애가 아니라 한가한
 * 서버로 읽히기 때문이다. 대신 그 자리에 상태 카드를 둔다 — 왜 비었는지가 그래프보다
 * 중요한 정보다.
 *
 * 색은 `index.css`의 브랜드 토큰 값이다. SVG `stroke`는 Tailwind 클래스를 받지 않아
 * 문자열로 넘긴다.
 */

const CPU_COLOR = '#2f5eeb'
const MEMORY_COLOR = '#afc8ff'
const IN_COLOR = '#5b8dff'
const OUT_COLOR = '#1a2743'

function ChartCard({
  title,
  caption,
  legend,
  children,
}: {
  title: string
  caption: string
  legend: ReactNode
  children: ReactNode
}) {
  return (
    <div className="rounded-[18px] border border-brand-line bg-white px-6 py-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-[13px] font-[750] text-brand-ink">{title}</h3>
          <p className="mt-1 text-[12px] text-brand-faint">{caption}</p>
        </div>
        {legend}
      </div>
      <div className="mt-3.5">{children}</div>
    </div>
  )
}

function LegendValue({
  swatch,
  label,
  value,
}: {
  swatch: ReactNode
  label: string
  value: ReactNode
}) {
  return (
    <div className="text-right">
      <div className="inline-flex items-center gap-1.5 text-[11.5px] text-brand-faint">
        {swatch}
        {label}
      </div>
      <div>{value}</div>
    </div>
  )
}

function lineSwatch(color: string) {
  return <span className="inline-block h-0.5 w-2.5" style={{ backgroundColor: color }} />
}

function blockSwatch(color: string) {
  return <span className="inline-block h-2 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
}

/** 연결되지 않았거나 점이 없을 때 그래프 자리에 들어가는 카드. */
function ChartFallback({
  state,
  reachable,
  title,
}: {
  state: DisconnectedState | null
  reachable: boolean
  title: string
}) {
  if (!reachable && state !== null) {
    return <DisconnectedStateCard state={state} title={title} />
  }
  return (
    <StateCard
      kind="NO_DATA"
      title={title}
      description="Prometheus에 연결됐지만 이 범위에 값이 없습니다. 수집이 방금 시작됐을 수 있습니다."
    />
  )
}

function disconnectedState(timeseries: MonitoringTimeseries | undefined): DisconnectedState | null {
  if (timeseries === undefined || timeseries.state === 'CONNECTED') {
    return null
  }
  return timeseries.state
}

export function ResourceOverview({
  cpu,
  memory,
  network,
}: {
  cpu: MonitoringTimeseries | undefined
  memory: MonitoringTimeseries | undefined
  network: MonitoringTimeseries | undefined
}) {
  const cpuData = averageAcrossServers(cpu)
  const memoryData = averageAcrossServers(memory)
  const receive = sumAcrossServers(network, 'receive')
  const transmit = sumAcrossServers(network, 'transmit')

  const usageHasPoints = cpuData.values.length > 0 || memoryData.values.length > 0
  const networkHasPoints = receive.values.length > 0 || transmit.values.length > 0
  const networkMax = niceMax([...receive.values, ...transmit.values])
  // 단위는 값에 따라 MB/s·KB/s로 바뀜다. 그래서 범례 값이 자기 단위를 직접 달고,
  // caption은 더 이상 단위를 주장하지 않는다 (S15P21E102-292).
  const receiveRate = throughput(receive.latest)
  const transmitRate = throughput(transmit.latest)

  return (
    <div className="gj-mon-charts">
      <ChartCard
        title="CPU · Memory"
        caption="전체 서버 평균 · 최근 60분 · 5분 간격"
        legend={
          <div className="flex gap-5">
            <LegendValue
              swatch={lineSwatch(CPU_COLOR)}
              label="CPU"
              value={
                <MetricValue
                  text={formatPercent(cpuData.latest)}
                  level={cpuMemoryLevel(cpuData.latest)}
                  size="lg"
                />
              }
            />
            <LegendValue
              swatch={lineSwatch(MEMORY_COLOR)}
              label="Memory"
              value={
                <MetricValue
                  text={formatPercent(memoryData.latest)}
                  level={cpuMemoryLevel(memoryData.latest)}
                  size="lg"
                />
              }
            />
          </div>
        }
      >
        {usageHasPoints ? (
          <>
            <LineChart
              ariaLabel="전체 서버 평균 CPU와 메모리 사용률 최근 60분"
              max={100}
              series={[
                { id: 'memory', label: 'Memory', color: MEMORY_COLOR, values: memoryData.values },
                { id: 'cpu', label: 'CPU', color: CPU_COLOR, width: 2.5, values: cpuData.values },
              ]}
            />
            <TimeAxis
              labels={axisLabels(
                cpuData.times.length > 0 ? cpuData.times : memoryData.times,
                5,
                formatClock,
              )}
            />
          </>
        ) : (
          <ChartFallback
            state={disconnectedState(cpu) ?? disconnectedState(memory)}
            reachable={cpu?.reachable === true || memory?.reachable === true}
            title="CPU · Memory 시계열"
          />
        )}
      </ChartCard>

      <ChartCard
        title="Network I/O"
        caption="전체 서버 합산 · 최근 60분"
        legend={
          <div className="flex gap-4">
            <LegendValue
              swatch={blockSwatch(IN_COLOR)}
              label="IN"
              value={
                <MetricValue
                  text={receiveRate?.value ?? null}
                  unit={receiveRate?.unit}
                  size="md"
                />
              }
            />
            <LegendValue
              swatch={blockSwatch(OUT_COLOR)}
              label="OUT"
              value={
                <MetricValue
                  text={transmitRate?.value ?? null}
                  unit={transmitRate?.unit}
                  size="md"
                />
              }
            />
          </div>
        }
      >
        {networkHasPoints ? (
          <>
            <LineChart
              ariaLabel="전체 서버 합산 네트워크 수신과 송신 최근 60분"
              width={480}
              max={networkMax}
              series={[
                {
                  id: 'receive',
                  label: 'IN',
                  color: IN_COLOR,
                  fill: 'rgba(91,141,255,0.12)',
                  values: receive.values,
                },
                { id: 'transmit', label: 'OUT', color: OUT_COLOR, values: transmit.values },
              ]}
            />
            <TimeAxis
              labels={axisLabels(
                receive.times.length > 0 ? receive.times : transmit.times,
                3,
                formatClock,
              )}
            />
          </>
        ) : (
          <ChartFallback
            state={disconnectedState(network)}
            reachable={network?.reachable === true}
            title="Network I/O 시계열"
          />
        )}
      </ChartCard>
    </div>
  )
}
