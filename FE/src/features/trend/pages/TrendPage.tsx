import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useJobDemands, useTarget } from '@/features/matching/hooks/useMatching'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import { unavailableSource } from '@/features/trend/api/adapter'
import { toTrendPeriodViews } from '@/features/trend/api/periodViews'
import { MarketDemandSection } from '@/features/trend/components/MarketDemandSection'
import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { useTechnologyTrendsBatch } from '@/features/trend/hooks/useTrends'
import {
  resolveEmptySourceStatus,
  summarizeTrendLoad,
} from '@/features/trend/model/sourceStatus'
import type { TrendSourceId, TrendSourceView } from '@/features/trend/model/view'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

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

  /*
   * 기술별 상세를 모아 기간별 순위를 만든다 · 티켓 S15P21E102-329.
   *
   * `/trends/compare`로는 최신 기간 하나밖에 그릴 수 없다 — BE가 기술당
   * `points.getLast()`로 줄인다. 카드 안에서 기간을 이동하려면 기간별 값이 필요하고,
   * 그것을 주는 것은 기술별 상세 상답이다.
   */
  const trendQueries = useTechnologyTrendsBatch(
    techIds,
    periods,
    {
      targetKey: target.data?.targetKey,
      targetRole: target.data?.targetRole,
      regions: target.data?.regions,
      careerLevels: target.data?.careerLevels,
    },
    target.isFetched,
  )
  const loadedDtos = trendQueries
    .map((query) => query.data)
    .filter((data): data is NonNullable<typeof data> => data !== undefined)
  /*
   * 빠진 기술을 센다. 기준은 오류 플래그가 아니라 **순위에 값이 들어갔는지**다.
   *
   * 조회 훅은 `retry: false`에 `staleTime`이 5분이라, 캐시를 들고 있던 기술이 재조회에서
   * 실패하면 `isError`가 켜진 채로도 `data`는 남아 순위에 그대로 들어간다. 그때
   * `isError`를 세면 열 개가 다 보이는 화면에 "9개만 성공했고 빠진 기술이 있다"고
   * 적게 된다 — 없는 실패를 지어내는 것도 실패를 숨기는 것과 같은 종류의 거짓이다.
   */
  const missingCount = trendQueries.length - loadedDtos.length
  const allSettled = trendQueries.length > 0 && trendQueries.every((query) => !query.isPending)
  /*
   * 부분 실패를 화면에 드러낸다 · 티켓 S15P21E102-329 D2.
   *
   * 빠진 기술은 `loadedDtos`에서 그냥 사라지므로, 알리지 않으면 9개로 만든 순위가
   * 10개 완전 성공과 구별되지 않는다. 부분 성공 자체는 그대로 두고 — 하나 때문에
   * 나머지 아홉을 감추지 않는다 — 그 사실만 위에 적는다.
   */
  const loadSummary = allSettled ? summarizeTrendLoad(trendQueries.length, loadedDtos.length) : null

  const periodViews = useMemo(
    () => toTrendPeriodViews(loadedDtos, techNames),
    // 기술 목록과 상답 개수가 같으면 같은 결과다. DTO 배열 자체는 매 렌더 새 배열이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loadedDtos.length, techIds.join(','), periods.join(',')],
  )

  /*
   * 선택 기간은 원천마다 독립이다. 주간을 옮겼다고 월별 카드까지 따라 움직이면 두
   * 카드를 나란히 놓은 이유가 없어진다.
   */
  const [selected, setSelected] = useState<Partial<Record<TrendSourceId, string>>>({})

  const sources: { view: TrendSourceView; periods: readonly string[]; selected: string }[] = []
  for (const id of ['GITHUB_WEEKLY', 'GITHUB_ARCHIVE', 'JOB'] as const) {
    const entry = periodViews.get(id)
    if (entry === undefined || entry.periods.length === 0) {
      /*
       * 그릴 기간이 하나도 없는 원천. 조회가 끝난 뒤에만 빈 카드를 그린다 — 로딩 중에
       * "데이터 없음"을 띄우면 아직 모르는 것을 없다고 말하는 것이 된다.
       *
       * 상태는 **서버가 내린 판정을 그대로 쓴다** · 티켓 S15P21E102-329 D1. 준비 중·
       * 실패는 오류가 아니라 200 + `dataStatus`로 오므로, 요청이 성공했다는 사실만으로
       * 상태를 다시 만들면 200 안의 `FAILED`가 "아직 집계된 기간이 없습니다"로 읽힌다.
       * 판정이 하나도 없을 때(어느 상답에도 그 원천이 없었을 때)만 요청 실패를 본다.
       */
      if (allSettled) {
        const judged = resolveEmptySourceStatus(
          (entry?.judgements ?? []).map((item) => item.status),
          missingCount > 0,
        )
        sources.push({
          view: unavailableSource(id, judged.status, judged.scopeNote),
          periods: [],
          selected: '',
        })
      }
      continue
    }
    // 기본값은 최신 기간이다.
    const latest = entry.periods[entry.periods.length - 1] as string
    const chosen =
      selected[id] !== undefined && entry.viewByPeriod.has(selected[id] as string)
        ? (selected[id] as string)
        : latest
    const view = entry.viewByPeriod.get(chosen)
    if (view !== undefined) {
      sources.push({ view, periods: entry.periods, selected: chosen })
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
        {/*
         * 직무와 무관한 시장 전체가 먼저다 · 티켓 S15P21E102-339. 아래 원천별 카드는
         * 목표 직무를 골라야 채워지는데, 무엇을 고를지 정하려면 시장을 먼저 봐야 한다.
         */}
        <MarketDemandSection limit={COMPARE_LIMIT} />

        <ComputeStatePanel
          isLoading={target.isLoading || demands.isLoading}
          error={target.error ?? demands.error}
          state={demands.data}
          loadingLabel="비교할 기술을 불러오는 중입니다."
          onRetry={() => void demands.refetch()}
        />

        {target.data === null && !target.isLoading && (
          <p className="text-[13px] text-brand-muted">
            직무별 추세를 보려면{' '}
            <Link to="/roles" className="font-semibold text-brand-600 hover:underline">
              목표 직무를 선택해 주세요.
            </Link>
          </p>
        )}

        {loadSummary !== null && (
          <StateCard
            kind={loadSummary.kind === 'FAILED' ? 'ERROR' : 'PARTIAL'}
            title={loadSummary.title}
            description={loadSummary.description}
          />
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map(({ view, periods: sourcePeriods, selected: current }) => (
            <TrendSourceCard
              key={view.id}
              source={view}
              navigation={
                sourcePeriods.length > 1
                  ? {
                      periods: sourcePeriods,
                      selected: current,
                      onSelect: (period) =>
                        setSelected((previous) => ({ ...previous, [view.id]: period })),
                    }
                  : undefined
              }
            />
          ))}
        </div>
      </div>
    </div>
  )
}
