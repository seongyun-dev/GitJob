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
  formatThroughput,
  percentNumber,
  throughput,
  totalThroughput,
} from '@/features/admin/monitoring/ui/formatMetric'
import { AdminTable } from '@/features/admin/monitoring/ui/AdminTable'
import { MetricValue, UsageBar } from '@/features/admin/monitoring/ui/MetricValue'
import { UpBadge } from '@/features/admin/monitoring/ui/StatusBadge'

/**
 * Server Detail · 티켓 S15P21E102-210.
 *
 * 확정 디자인의 표를 옮긴 것이며 컬럼과 열 폭도 디자인에서 읽었다
 * (`190px repeat(4,1fr) 120px`). 표 카드는 `ui/AdminTable` — 흰 카드 안에 헤더 · 행 ·
 * 각주(임계치)가 들어간다. 값은 디자인대로 숫자 22px 크게 · 단위(`%`·`MB/s`) 12px 작게.
 *
 * 행 격자를 인라인 스타일이 아니라 `index.css`의 `.gj-mon-row`에 둔 이유는 좁은 화면에서
 * 열이 접혀야 하기 때문이다. 인라인 스타일에는 미디어 쿼리를 쓸 수 없어, 그렇게 하면
 * 큰 화면용 행과 좁은 화면용 행을 각각 만들게 되고 같은 셀 코드가 두 벌이 된다.
 *
 * 행은 topology config 순서다. 서버가 늘면 행이 늘고 이 파일은 바뀌지 않는다.
 *
 * 디자인에 있는데 여기 없는 것이 셋이다. `Ubuntu 22.04`, `Uptime 41d 6h`, CPU 보조 표기의
 * `load 0.9`는 mock이다 — OS·uptime을 주는 지표가 이번 API에 없고 `node_load1`은
 * S15P21E102-205의 수집 확인 목록에 없어 BE가 질의하지 않는다. 자리를 비우는 편이
 * 그럴듯한 숫자보다 정확하다.
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
  /** 단위 없는 숫자 문자열. `percentNumber`·`throughput`이 만든다. */
  value: string | null
  /** 숫자 옆에 작게 붙는 단위. 디자인의 `23 %` · `6.2 MB/s`. */
  unit: string
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

/** 행. 디자인 padding 20px 24px · 행 사이 #EEF1F6. 헤더가 border-bottom 을 가지므로 첫 행은 위 선을 뺀다. */
function ServerRow({ view, server }: { view: MonitoringView; server: ServerView }) {
  const metrics = server.metrics
  const cpuPercent = metrics?.cpuPercent ?? null
  const memoryPercent = metrics?.memoryPercent ?? null
  const diskPercent = metrics?.diskPercent ?? null
  const receive = metrics?.networkReceiveBytesPerSecond ?? null
  const transmit = metrics?.networkTransmitBytesPerSecond ?? null
  const networkRate = throughput(totalThroughput(receive, transmit))
  const name = server.node.displayName

  return (
    <div className="gj-mon-row border-t border-[#EEF1F6] px-6 py-5 first:border-t-0">
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
        value={percentNumber(cpuPercent)}
        unit="%"
        percent={cpuPercent}
        level={cpuMemoryLevel(cpuPercent)}
        caption={metrics?.cpuCores == null ? null : `${metrics.cpuCores} vCPU`}
        label={`${name} CPU`}
      />
      <MetricCell
        value={percentNumber(memoryPercent)}
        unit="%"
        percent={memoryPercent}
        level={cpuMemoryLevel(memoryPercent)}
        caption={formatCapacity(
          metrics?.memoryUsedBytes ?? null,
          metrics?.memoryTotalBytes ?? null,
        )}
        label={`${name} MEMORY`}
      />
      <MetricCell
        value={percentNumber(diskPercent)}
        unit="%"
        percent={diskPercent}
        level={diskLevel(diskPercent)}
        caption={formatCapacity(
          metrics?.diskUsedBytes ?? null,
          metrics?.diskTotalBytes ?? null,
        )}
        label={`${name} DISK`}
      />
      <MetricCell
        value={networkRate?.value ?? null}
        unit={networkRate?.unit ?? 'MB/s'}
        // 처리량에는 상한이 없어 비율 바를 만들 수 없다. 임의의 최대값으로 채우면
        // 그 눈금이 무엇을 뜻하는지 아무도 모른다.
        percent={null}
        level="NORMAL"
        caption={
          receive === null || transmit === null
            ? null
            : `In ${formatThroughput(receive) ?? '—'} · Out ${
                formatThroughput(transmit) ?? '—'
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

      <AdminTable
        columns={COLUMNS}
        template={TEMPLATE}
        footer={
          <>
            임계치 · CPU/Memory {CPU_MEMORY_THRESHOLD.warning}% 주의 ·{' '}
            {CPU_MEMORY_THRESHOLD.critical}% 경고 · Disk {DISK_THRESHOLD.warning}% 주의 ·{' '}
            {DISK_THRESHOLD.critical}% 경고
          </>
        }
      >
        {view.servers.map((server) => (
          <ServerRow key={server.node.id} view={view} server={server} />
        ))}
      </AdminTable>
    </section>
  )
}
