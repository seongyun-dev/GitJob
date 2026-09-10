import { serverUpState } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { MonitoringView, ServerView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import {
  CPU_MEMORY_THRESHOLD,
  DISK_THRESHOLD,
  cpuMemoryLevel,
  diskLevel,
} from '@/features/admin/monitoring/model/thresholds'
import type { UsageLevel } from '@/features/admin/monitoring/model/thresholds'
import {
  formatCapacity,
  formatPercent,
  megabytesPerSecond,
  totalThroughput,
} from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue, UsageBar } from '@/features/admin/monitoring/ui/MetricValue'
import { UpBadge } from '@/features/admin/monitoring/ui/StatusBadge'
import { TableScaffold } from '@/shared/ui/Scaffold'

/**
 * Server Detail · 티켓 S15P21E102-210.
 *
 * 확정 디자인의 표를 옮긴 것이며 컬럼과 열 폭도 디자인에서 읽었다
 * (`190px repeat(4,1fr) 120px`). 골격은 `shared/ui/Scaffold`의 `TableScaffold`를 쓴다 —
 * 값이 없어도 무엇이 들어올 자리인지 남는다.
 *
 * 행 격자를 인라인 스타일이 아니라 `index.css`의 `.gj-mon-row`에 둔 이유는 좁은 화면에서
 * 열이 접혀야 하기 때문이다. 인라인 스타일에는 미디어 쿼리를 쓸 수 없어, 그렇게 하면
 * 큰 화면용 행과 좁은 화면용 행을 각각 만들게 되고 같은 셀 코드가 두 벌이 된다.
 *
 * 행은 topology config 순서다. 서버가 늘면 행이 늘고 이 파일은 바뀌지 않는다.
 *
 * 디자인에 있는데 여기 없는 것이 둘이다. `Uptime 41d 6h`와 CPU 보조 표기의 `load 0.9`는
 * mock이다 — uptime을 주는 지표가 이번 API에 없고 `node_load1`은 S15P21E102-205의 수집
 * 확인 목록에 없어 BE가 질의하지 않는다. 자리를 비우는 편이 그럴듯한 숫자보다 정확하다.
 */

const COLUMNS = ['SERVER', 'CPU', 'MEMORY', 'DISK', 'NETWORK', 'STATUS'] as const

/** `.gj-mon-row`의 큰 화면 격자와 같은 값이어야 한다. */
const TEMPLATE = '190px repeat(4, minmax(0, 1fr)) 120px'

function MetricCell({
  value,
  unit,
  percent,
  level,
  caption,
  label,
}: {
  value: string | null
  /**
   * 값 문자열에 단위가 없을 때만 준다. `formatPercent`는 `%`를 이미 붙이므로
   * 백분율 칸에서는 넘기지 않는다 — 넘기면 `23% %`가 된다.
   */
  unit?: string
  /** 바에 쓰는 비율. 처리량처럼 상한이 없는 지표는 `null`이다. */
  percent: number | null
  level: UsageLevel
  caption: string | null
  label: string
}) {
  return (
    <div>
      <p className="mb-1 text-[10.5px] font-extrabold tracking-[0.08em] text-brand-faint lg:hidden">
        {label.split(' ').slice(-1)[0]}
      </p>
      <MetricValue text={value} unit={unit} level={level} />
      <div className="mt-2">
        <UsageBar percent={percent} level={level} label={label} />
      </div>
      <p className="mt-1.5 text-[11.5px] text-brand-faint">{caption ?? '값 없음'}</p>
    </div>
  )
}

function ServerRow({ view, server }: { view: MonitoringView; server: ServerView }) {
  const metrics = server.metrics
  const cpuPercent = metrics?.cpuPercent ?? null
  const memoryPercent = metrics?.memoryPercent ?? null
  const diskPercent = metrics?.diskPercent ?? null
  const receive = metrics?.networkReceiveBytesPerSecond ?? null
  const transmit = metrics?.networkTransmitBytesPerSecond ?? null
  const name = server.node.displayName

  return (
    <div className="gj-mon-row border-t border-brand-line py-4 first:border-t-0">
      <div className="max-lg:col-span-full">
        <code className="font-evidence text-[14px] font-bold text-brand-ink">{name}</code>
        <p className="mt-1.5 text-[12px] text-brand-faint">{server.node.name}</p>
        {/*
          Prometheus에 닿았는데도 이 서버가 결과에 없을 때만 알린다. 미연결이면 원인은
          이 서버가 아니라 모니터링이고, 그것은 화면 맨 위 배너가 이미 말한다.
        */}
        {view.reachable && metrics === null && (
          <p className="mt-1 text-[11.5px] text-tone-caution">
            수집 대상에서 찾지 못했습니다
          </p>
        )}
      </div>

      <MetricCell
        value={formatPercent(cpuPercent)}
        percent={cpuPercent}
        level={cpuMemoryLevel(cpuPercent)}
        caption={metrics?.cpuCores == null ? null : `${metrics.cpuCores} vCPU`}
        label={`${name} CPU`}
      />
      <MetricCell
        value={formatPercent(memoryPercent)}
        percent={memoryPercent}
        level={cpuMemoryLevel(memoryPercent)}
        caption={formatCapacity(
          metrics?.memoryUsedBytes ?? null,
          metrics?.memoryTotalBytes ?? null,
        )}
        label={`${name} MEMORY`}
      />
      <MetricCell
        value={formatPercent(diskPercent)}
        percent={diskPercent}
        level={diskLevel(diskPercent)}
        caption={formatCapacity(
          metrics?.diskUsedBytes ?? null,
          metrics?.diskTotalBytes ?? null,
        )}
        label={`${name} DISK`}
      />
      <MetricCell
        value={megabytesPerSecond(totalThroughput(receive, transmit))}
        unit="MB/s"
        // 처리량에는 상한이 없어 비율 바를 만들 수 없다. 임의의 최대값으로 채우면
        // 그 눈금이 무엇을 뜻하는지 아무도 모른다.
        percent={null}
        level="NORMAL"
        caption={
          receive === null || transmit === null
            ? null
            : `In ${megabytesPerSecond(receive) ?? '—'} · Out ${
                megabytesPerSecond(transmit) ?? '—'
              }`
        }
        label={`${name} NETWORK`}
      />

      <div className="max-lg:col-span-full">
        <UpBadge up={serverUpState(view, server)} />
      </div>
    </div>
  )
}

export function ServerDetailTable({ view }: { view: MonitoringView }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 px-1">
        <h2 className="text-[18px] font-[750] tracking-[-0.03em] text-brand-ink">
          Server Detail
        </h2>
        <span className="text-[12.5px] text-brand-faint">서버 간 비교 · 현재 값 기준</span>
      </div>

      <TableScaffold columns={COLUMNS} template={TEMPLATE}>
        {view.servers.map((server) => (
          <ServerRow key={server.node.id} view={view} server={server} />
        ))}
      </TableScaffold>

      <p className="mt-3 px-1 text-[12px] text-brand-faint">
        임계치 · CPU/Memory {CPU_MEMORY_THRESHOLD.warning}% 주의 ·{' '}
        {CPU_MEMORY_THRESHOLD.critical}% 경고 · Disk {DISK_THRESHOLD.warning}% 주의 ·{' '}
        {DISK_THRESHOLD.critical}% 경고
      </p>
    </section>
  )
}
