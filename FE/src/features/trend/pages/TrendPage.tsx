import { Link } from 'react-router'
import { useJobDemands, useTarget } from '@/features/matching/hooks/useMatching'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import { toTrendSource, unavailableSource } from '@/features/trend/api/adapter'
import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { useTrendCompare } from '@/features/trend/hooks/useTrends'
import type { TrendSourceView } from '@/features/trend/model/view'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { PageHero } from '@/shared/ui/PageHero'

const COMPARE_LIMIT = 10
const OVERVIEW_MONTHS = 6

function completedMonths(count: number): string[] {
  const now = new Date()
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - (count - index), 1))
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
  })
}

export function TrendPage() {
  const target = useTarget()
  const demands = useJobDemands({
    targetRole: target.data?.targetRole,
    regions: target.data?.regions ?? [],
    careerLevels: target.data?.careerLevels ?? [],
  })
  const techIds = (demands.data?.technologies ?? [])
    .filter((technology) => technology.totalCount > 0)
    .slice(0, COMPARE_LIMIT)
    .map((technology) => technology.techId)
  const techNames = new Map(techIds.map((techId) => [techId, technologyDisplayName(techId)]))
  const periods = completedMonths(OVERVIEW_MONTHS)
  const weekly = useTrendCompare({ source: 'GITHUB_WEEKLY', techIds, periods: [] })
  const monthlyArchive = useTrendCompare({ source: 'GITHUB_ARCHIVE', techIds, periods })
  const monthlyJobs = useTrendCompare({
    source: 'JOB',
    techIds,
    periods,
    target: {
      targetKey: target.data?.targetKey,
      targetRole: target.data?.targetRole,
      regions: target.data?.regions,
      careerLevels: target.data?.careerLevels,
    },
    enabled: target.data !== null && target.data !== undefined,
  })

  const sources: TrendSourceView[] = []
  if (weekly.data !== undefined) {
    const card = toTrendSource(weekly.data, techNames)
    if (card !== null) sources.push(card)
  } else if (weekly.isError) {
    sources.push(unavailableSource('GITHUB_WEEKLY', 'FAILED', '활동 데이터를 불러오지 못했습니다.'))
  }
  for (const [id, query] of [
    ['GITHUB_ARCHIVE', monthlyArchive],
    ['JOB', monthlyJobs],
  ] as const) {
    if (query.data !== undefined) {
      const card = toTrendSource(query.data, techNames)
      if (card !== null) sources.push(card)
    } else if (query.isError) {
      sources.push(unavailableSource(id, 'FAILED', '이 출처의 데이터를 불러오지 못했습니다.'))
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero title="기술 트렌드" />
        {target.data !== null && target.data !== undefined && (
          <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
            <p className="text-[12px] text-brand-faint">비교 직무</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
              {targetRoleDisplayName(target.data.targetRole)}
            </p>
          </div>
        )}
      </div>

      <div className="mt-7 grid gap-4">
        <ComputeStatePanel
          isLoading={target.isLoading || demands.isLoading}
          error={target.error ?? demands.error}
          state={demands.data}
          loadingLabel="비교할 기술을 불러오는 중입니다."
          onRetry={() => void demands.refetch()}
        />

        {target.data === null && !target.isLoading && (
          <p className="text-[13px] text-brand-muted">
            먼저{' '}
            <Link to="/roles" className="font-semibold text-brand-600 hover:underline">
              목표 직무를 선택해 주세요.
            </Link>
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map((source) => (
            <TrendSourceCard key={source.id} source={source} />
          ))}
        </div>
      </div>
    </div>
  )
}
