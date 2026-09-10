import type { MonitoringView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import { DISK_THRESHOLD, diskLevel } from '@/features/admin/monitoring/model/thresholds'
import { formatCapacity, formatPercent } from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue, UsageBar } from '@/features/admin/monitoring/ui/MetricValue'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Disk Capacity · 티켓 S15P21E102-210.
 *
 * 확정 디자인의 큰 사용률 숫자, 임계치 표시가 있는 바, 서버별 줄에 대응한다.
 *
 * 전체 사용률을 서버 비율의 평균으로 내지 않는다. 400GB 서버와 100GB 서버의 비율을
 * 평균하면 실제 사용량과 무관한 값이 나온다. 바이트를 더한 뒤 비율을 낸다.
 *
 * 서버 한 대라도 용량을 못 읽으면 합계를 만들지 않는다. 반쪽 합계는 실제보다 작은
 * 사용량을 주장하고, 그것이 곧 "여유 있다"는 오판으로 이어진다.
 */

interface Totals {
  usedBytes: number
  totalBytes: number
  percent: number
}

function totals(view: MonitoringView): Totals | null {
  let usedBytes = 0
  let totalBytes = 0

  for (const server of view.servers) {
    const used = server.metrics?.diskUsedBytes ?? null
    const total = server.metrics?.diskTotalBytes ?? null
    if (used === null || total === null) {
      return null
    }
    usedBytes += used
    totalBytes += total
  }

  if (view.servers.length === 0 || totalBytes === 0) {
    return null
  }
  return { usedBytes, totalBytes, percent: (usedBytes / totalBytes) * 100 }
}

export function DiskCapacity({ view }: { view: MonitoringView }) {
  const summary = totals(view)

  return (
    <div className="rounded-[18px] border border-brand-line bg-white px-6 py-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <h3 className="text-[13px] font-[750] text-brand-ink">Disk Capacity</h3>
      <p className="mt-1 text-[12px] text-brand-faint">
        전체 서버 합산 · root 파일시스템
      </p>

      {summary === null ? (
        <div className="mt-4">
          <StateCard
            kind="NO_DATA"
            title="용량 합계를 만들 수 없습니다"
            description="서버 중 한 대 이상의 디스크 용량을 읽지 못했습니다. 일부만 더한 합계는 실제보다 작은 사용량을 보여주므로 표시하지 않습니다."
          />
        </div>
      ) : (
        <>
          <div className="mt-4 flex items-baseline gap-2.5">
            <MetricValue
              text={formatPercent(summary.percent)}
              level={diskLevel(summary.percent)}
              size="lg"
            />
            <span className="text-[14px] font-bold text-brand-muted tabular-nums">
              {formatCapacity(summary.usedBytes, summary.totalBytes)}
            </span>
          </div>

          {/* 임계치 표시. 눈금 위치는 `thresholds.ts`가 정한다. */}
          <div className="relative mt-4 h-3.5 rounded-sm bg-[#EEF1F6]">
            <div
              className={`absolute inset-y-0 left-0 rounded-sm ${
                diskLevel(summary.percent) === 'CRITICAL'
                  ? 'bg-tone-danger'
                  : diskLevel(summary.percent) === 'WARNING'
                    ? 'bg-tone-caution'
                    : 'bg-linear-to-r from-brand-600 to-brand-400'
              }`}
              style={{ width: `${Math.min(100, summary.percent)}%` }}
            />
            <span
              className="absolute -top-1 -bottom-1 w-px bg-tone-caution"
              style={{ left: `${DISK_THRESHOLD.warning}%` }}
            />
            <span
              className="absolute -top-1 -bottom-1 w-px bg-tone-danger"
              style={{ left: `${DISK_THRESHOLD.critical}%` }}
            />
          </div>
          <div className="mt-2.5 flex justify-between text-[11.5px] text-brand-faint">
            <span>0</span>
            <span className="flex gap-3.5">
              <span className="font-bold text-tone-caution">
                Warning {DISK_THRESHOLD.warning}%
              </span>
              <span className="font-bold text-tone-danger">
                Critical {DISK_THRESHOLD.critical}%
              </span>
            </span>
          </div>
        </>
      )}

      <div className="mt-4 flex flex-col">
        {view.servers.map((server) => {
          const percent = server.metrics?.diskPercent ?? null
          return (
            <div
              key={server.node.id}
              className="flex items-center justify-between gap-3.5 border-t border-brand-line py-2.5"
            >
              <code className="font-evidence shrink-0 text-[12.5px] font-bold text-brand-ink-soft">
                {server.node.displayName}
              </code>
              <span className="min-w-0 flex-1">
                <UsageBar
                  percent={percent}
                  level={diskLevel(percent)}
                  label={`${server.node.displayName} 디스크 사용률`}
                />
              </span>
              <span className="shrink-0 text-[12.5px] font-bold text-brand-ink-soft tabular-nums">
                {formatCapacity(
                  server.metrics?.diskUsedBytes ?? null,
                  server.metrics?.diskTotalBytes ?? null,
                ) ?? '값 없음'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
