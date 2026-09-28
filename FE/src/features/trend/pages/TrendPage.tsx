import { useState } from 'react'
import { Link } from 'react-router'
import type { JobDemandDto } from '@/features/matching/api/types'
import { useCurrentMarketDemands, useTarget } from '@/features/matching/hooks/useMatching'
import { formatCollectedAt } from '@/features/matching/model/presentation'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import type { TrendRankingDto } from '@/features/trend/api/trendApi'
import {
  marketDemandSource,
  trendRankingSource,
  unavailableSource,
} from '@/features/trend/api/adapter'
import type { TrendPeriodNavigation } from '@/features/trend/components/TrendSourceCard'
import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { useTrendRankings } from '@/features/trend/hooks/useTrends'
import { pendingSourceStatus } from '@/features/trend/model/githubTrendTechnologies'
import { periodNavigation } from '@/features/trend/model/periodNavigation'
import type { MarketDemandView } from '@/features/trend/model/marketDemand'
import { marketDemandView } from '@/features/trend/model/marketDemand'
import type { TrendSourceId, TrendSourceView } from '@/features/trend/model/view'
import { hasComputedValue } from '@/shared/api/computeState'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { PageHero } from '@/shared/ui/PageHero'

/** 화면 한 장이 읽을 수 있는 순위 길이. 무엇 중의 10개인지는 카드가 따로 밝힌다. */
const TOP_N = 10

/** 이 분포가 무엇을 기준으로 나온 것인지. 기준을 숨기면 숫자를 절대값으로 읽는다. */
function marketBasisText(view: MarketDemandView, isLoading: boolean): string {
  if (isLoading) {
    return '불러오는 중'
  }
  if (view.jobCount === null) {
    return '기준 미정'
  }
  return `공고 ${view.jobCount.toLocaleString('ko-KR')}건 기준 · ${formatCollectedAt(view.asOf)}`
}

/** 값이 없을 때 카드 안에 적을 이유. 없으면 카드가 각주를 쓴다. */
function marketStatusNote(
  demand: JobDemandDto | undefined,
  isLoading: boolean,
  error: unknown,
): string | null {
  if (isLoading) {
    return '현재 채용공고의 기술 수요를 불러오는 중입니다.'
  }
  if (error !== null && error !== undefined) {
    return '기술 수요를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
  }
  if (demand === undefined) {
    return null
  }
  if (demand.dataStatus === 'PREPARING') {
    return '비교할 공고를 준비하고 있습니다. 준비되면 자동으로 표시됩니다.'
  }
  if (demand.dataStatus === 'FAILED') {
    return '기술 수요를 만들지 못했습니다. 잠시 후 다시 확인해 주세요.'
  }
  return null
}

/**
 * GitHub 한 출처의 카드 · 티켓 S15P21E102-346.
 *
 * 값이 없어도 카드는 사라지지 않는다. 카드가 보이는 것과 값이 있는 것은 다른 사실이고,
 * 자리를 비우면 화면은 그 출처가 아예 없는 것처럼 읽힌다.
 */
function githubRankingSource(
  id: TrendSourceId,
  unit: string,
  query: {
    data: TrendRankingDto | undefined
    isLoading: boolean
    error: unknown
  },
): TrendSourceView {
  if (query.error !== null && query.error !== undefined) {
    return unavailableSource(id, 'FAILED', '이 출처의 데이터를 불러오지 못했습니다.')
  }
  if (query.data === undefined) {
    const pending = pendingSourceStatus()
    return unavailableSource(id, pending.status, pending.scopeNote, pending.basis)
  }
  if (query.data.technologies.length === 0) {
    // 서버가 판정을 줬으면 그것을 쓴다. 요청이 성공했다는 사실만으로 상태를 새로
    // 만들면 200 안의 PREPARING 이 "데이터 없음"으로 읽힌다.
    return unavailableSource(
      id,
      query.data.dataStatus,
      '이 출처에는 아직 집계된 기간이 없습니다.',
      query.data.period ?? '기간 미정',
    )
  }
  return trendRankingSource(id, unit, rankingBasis(query.data), query.data)
}

/**
 * 카드 기준 문구. 기간만 적는다.
 *
 * 모집단(`sampleRepoCount`)은 응답에 그대로 있고 비중(%) 계산에도 계속 쓰이지만,
 * 카드 문구로는 내보내지 않는다 — 카드가 묻는 것은 "이 기간에 무엇이 많이 관측됐나"
 * 이고, 표본 크기는 그 답을 읽는 데 필요하지 않다(-346에서 함께 적던 것을 되돌린다).
 */
function rankingBasis(data: TrendRankingDto): string {
  return data.period ?? '기간 미정'
}

/**
 * 카드 하나의 기간 이동 · 티켓 S15P21E102-329.
 *
 * **값이 없어도 붙인다.** 아직 집계되지 않은 기간으로 옮겨 간 카드에서 화살표를
 * 없애면 되돌아올 수 없고, 기간 이동이 한 방향 함정이 된다. 그래서 순위 행이 아니라
 * 서버가 준 기간 목록을 기준으로 만든다.
 */
function sourceNavigation(
  id: TrendSourceId,
  data: TrendRankingDto | undefined,
  onSelect: (update: (previous: Partial<Record<TrendSourceId, string>>) =>
    Partial<Record<TrendSourceId, string>>) => void,
): TrendPeriodNavigation | undefined {
  const state = periodNavigation(data?.availablePeriods, data?.period)
  if (state === null) {
    return undefined
  }
  return {
    periods: state.periods,
    selected: state.selected,
    // 선택은 출처별로 따로 둔다. 한 카드를 옮겼다고 다른 카드가 따라가지 않는다.
    onSelect: (period) => onSelect((previous) => ({ ...previous, [id]: period })),
  }
}

export function TrendPage() {
  const target = useTarget()

  /*
   * 현재 채용시장 분포 · 티켓 S15P21E102-342(-339에서 상단 대형 섹션이던 것).
   *
   * 목표 직무와 무관한 공용 집계라 `enabled` 조건 없이 바로 조회한다.
   */
  const market = useCurrentMarketDemands({ regions: [], careerLevels: [] })
  const marketDemand = marketDemandView(market.data, hasComputedValue(market.data))
  const marketTechNames = new Map(
    marketDemand.rows.map((row) => [row.techId, technologyDisplayName(row.techId)]),
  )
  const marketView = marketDemandSource(
    marketDemand,
    marketBasisText(marketDemand, market.isLoading),
    marketStatusNote(market.data, market.isLoading, market.error),
    marketTechNames,
    TOP_N,
  )

  /*
   * GitHub 카드는 서버가 정렬한 결과를 그대로 그린다 · 티켓 S15P21E102-346.
   *
   * 조회할 기술을 화면이 고르지 않는다. 고르면 카드가 보여 주는 것이 "이 기간에 많이
   * 관측된 기술"이 아니라 "우리가 고른 것들 중의 순위"가 되고, 기간이 바뀌어도 기술
   * 종류가 그대로다.
   *
   * 기간도 보내지 않는다. 달력으로 최근 주차를 계산하면 아직 게시되지 않은 주를 물어
   * 값이 있는데도 빈 카드가 뜬다 — 어느 기간이 있는지는 저장한 쪽이 안다.
   *
   * 목표 직무는 어느 쪽에도 들어가지 않는다. GitHub 관측은 직무와 무관하고, 실어
   * 보내면 직무를 바꿀 때마다 같은 관측을 다시 받아 온다.
   */
  /*
   * 선택 기간은 원천마다 독립이다 · 티켓 S15P21E102-329. 주간을 옮겼다고 월별 카드까지
   * 따라 움직이면 두 카드를 나란히 놓은 이유가 없어진다 — 모집단도 기간 체계도 다르다.
   *
   * 비어 있으면 서버가 그 출처의 최신 게시 기간을 고른다. 화면이 달력으로 계산하지
   * 않는 것이 요점이다.
   */
  const [selected, setSelected] = useState<Partial<Record<TrendSourceId, string>>>({})

  const weekly = useTrendRankings({
    source: 'GITHUB_WEEKLY',
    granularity: 'WEEK',
    period: selected.GITHUB_WEEKLY,
    limit: TOP_N,
  })
  const monthly = useTrendRankings({
    source: 'GITHUB_ARCHIVE',
    granularity: 'MONTH',
    period: selected.GITHUB_ARCHIVE,
    limit: TOP_N,
  })

  /*
   * 세 자리는 언제나 있다 · 티켓 S15P21E102-345. 값이 없으면 카드 안에서만 상태를
   * 말하고, 카드 자체를 빼지 않는다.
   */
  const sources: { view: TrendSourceView; navigation?: TrendPeriodNavigation }[] = [
    {
      view: githubRankingSource('GITHUB_WEEKLY', '주간 활동 저장소 수', weekly),
      navigation: sourceNavigation('GITHUB_WEEKLY', weekly.data, setSelected),
    },
    {
      view: githubRankingSource('GITHUB_ARCHIVE', '월별 활동 저장소 수', monthly),
      navigation: sourceNavigation('GITHUB_ARCHIVE', monthly.data, setSelected),
    },
    { view: marketView },
  ]

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
          화면 전체를 덮는 상태 패널을 두지 않는다 · 티켓 S15P21E102-345.

          셋 다 자기 조회를 갖고 자기 상태를 카드 안에서 말한다. 한 조회의 로딩을 화면
          머리에 띄우면 나머지 둘이 이미 그려졌는데도 화면 전체가 준비 중으로 읽힌다.
        */}
        {target.data === null && !target.isLoading && (
          <p className="text-[13px] text-brand-muted">
            아직 목표 직무를 선택하지 않았어요.{' '}
            <Link to="/roles" className="font-semibold text-brand-600 hover:underline">
              목표 직무 선택하기
            </Link>
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map(({ view, navigation }) => (
            <TrendSourceCard key={view.id} source={view} navigation={navigation} />
          ))}
        </div>
      </div>
    </div>
  )
}
