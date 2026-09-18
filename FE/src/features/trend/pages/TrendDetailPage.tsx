import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useTarget } from '@/features/matching/hooks/useMatching'
import { toTrendSeries } from '@/features/trend/api/adapter'
import { TrendBarChart } from '@/features/trend/components/TrendBarChart'
import { useTechnologyTrends } from '@/features/trend/hooks/useTrends'
import { ApiError } from '@/shared/api/client'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { DataRegion } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

function recentMonths(count: number): string[] {
  const now = new Date()
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - (count - index), 1))
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
  })
}

const RANGES = [
  { label: '최근 3개월', months: 3 },
  { label: '최근 6개월', months: 6 },
  { label: '최근 12개월', months: 12 },
] as const

export function TrendDetailPage() {
  const { techId } = useParams()
  const [range, setRange] = useState<number>(6)
  const periods = useMemo(() => recentMonths(range), [range])
  const target = useTarget()
  const trends = useTechnologyTrends(
    techId,
    periods,
    {
      targetKey: target.data?.targetKey,
      targetRole: target.data?.targetRole,
      regions: target.data?.regions,
      careerLevels: target.data?.careerLevels,
    },
    target.isFetched,
  )
  const series = trends.data === undefined ? [] : toTrendSeries(trends.data, periods[0])
  const charted = series.filter((item) => item.points.length > 0)
  const stateOnly = series.filter((item) => item.points.length === 0)

  return (
    <div>
      <Link
        to="/trends"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 기술 트렌드
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero title={`${technologyDisplayName(techId ?? '')} 트렌드`} />
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {RANGES.map((option) => (
            <button
              key={option.months}
              type="button"
              aria-pressed={range === option.months}
              onClick={() => setRange(option.months)}
              className={`rounded-[10px] px-3.5 py-2 text-[12.5px] font-bold transition-colors ${
                range === option.months
                  ? 'bg-tone-accent-bg text-brand-ink'
                  : 'border border-brand-line bg-white text-brand-faint hover:text-brand-ink'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {trends.isLoading && (
          <StateCard kind="LOADING" title="추이를 불러오는 중입니다." description="" />
        )}

        {trends.error !== null && (
          <StateCard
            kind="ERROR"
            title={
              trends.error instanceof ApiError
                ? trends.error.message
                : '추이를 불러오지 못했습니다.'
            }
            description="잠시 후 다시 시도해 주세요."
          />
        )}

        {trends.data !== undefined &&
          (charted.length === 0 ? (
            <StateCard
              kind="NO_DATA"
              title="이 기간의 데이터가 아직 없어요"
              description="다른 기간을 선택해 보세요."
            />
          ) : (
            charted.map((item) => (
              <DataRegion key={item.sourceId} title={item.label}>
                <TrendBarChart series={item} />
              </DataRegion>
            ))
          ))}

        {stateOnly.length > 0 && (
          <DataRegion title="다른 출처 상태">
            <div className="grid gap-3 sm:grid-cols-2">
              {stateOnly.map((item) => (
                <div
                  key={item.sourceId}
                  className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                >
                  <p className="text-[13px] font-[750] text-brand-ink">{item.label}</p>
                  <p className="mt-1.5 text-[12px] leading-[1.6] text-brand-muted">
                    {item.note}
                  </p>
                </div>
              ))}
            </div>
          </DataRegion>
        )}
      </div>
    </div>
  )
}
