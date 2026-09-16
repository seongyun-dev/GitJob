import { Link } from 'react-router'
import { useJobDemands, useTarget } from '@/features/matching/hooks/useMatching'
import { toTrendSource, unavailableSource } from '@/features/trend/api/adapter'
import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { useTrendCompare } from '@/features/trend/hooks/useTrends'
import type { TrendSourceView } from '@/features/trend/model/view'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'

/**
 * 기술 트렌드 개요 · 확정 디자인 `Final v2`의 `12 Trend Overview` (S15P21E102-279).
 *
 * <h2>출처를 나란히 두되 합치지 않는다</h2>
 *
 * 출처마다 측정 단위와 기간이 달라 순위를 출처 안에서만 비교한다. 종합 Trend 점수를
 * 만들지 않는다(`docs/ai/c-public-trend.md`). 그래서 출처마다 카드를 따로 부르고,
 * 한 출처가 실패해도 나머지는 그대로 그린다.
 *
 * <h2>비교할 기술을 화면이 고르지 않는다</h2>
 *
 * 순위를 매기려면 대상 목록이 필요한데, 그 목록을 화면이 임의로 정하면 목록 자체가
 * 근거 없는 순위가 된다. 그래서 <b>목표 직무의 수요 상위 기술</b>을 쓴다 — 사용자가
 * 비교하려는 직무가 실제로 요구하는 기술이다.
 */

/** 한 카드에 담을 기술 수. C의 비교 상한이 10이라 그에 맞춘다. */
const COMPARE_LIMIT = 10

export function TrendPage() {
  const target = useTarget()
  const demands = useJobDemands({
    targetRole: target.data?.targetRole,
    regions: target.data?.regions ?? [],
    careerLevels: target.data?.careerLevels ?? [],
  })

  const techIds = (demands.data?.technologies ?? [])
    .slice(0, COMPARE_LIMIT)
    .map((technology) => technology.techId)
  const techNames = new Map(techIds.map((techId) => [techId, techId]))

  const weekly = useTrendCompare({ source: 'GITHUB_WEEKLY', techIds, periods: [] })

  const sources: TrendSourceView[] = []
  if (weekly.data !== undefined) {
    const card = toTrendSource(weekly.data, techNames)
    if (card !== null) {
      sources.push(card)
    }
  } else if (weekly.isError) {
    sources.push(
      unavailableSource('GITHUB_WEEKLY', 'FAILED', '이 출처의 집계를 불러오지 못했습니다.'),
    )
  }
  /*
   * 월별 Archive는 기간을 명시해야 조회된다. 화면이 최근 몇 달을 임의로 고르면
   * 표시한 기간과 실제 계산 기간이 달라지므로, 개요에서는 기간을 정할 근거가 없어
   * 조회하지 않는다. 상세 화면이 기술 하나에 대해 기간을 받아 보여준다.
   */
  sources.push(
    unavailableSource(
      'GITHUB_ARCHIVE',
      'NOT_SUPPORTED',
      '월별 Archive는 기간을 지정해야 조회됩니다. 기술 상세에서 확인하세요.',
    ),
  )
  /*
   * JOB 출처는 조회 경로가 아직 없다(계약 §6-9). 빈 표를 그리면 "공고 수요가 0"으로
   * 읽히므로 지원하지 않는다고 적는다.
   */
  sources.push(
    unavailableSource(
      'JOB',
      'NOT_SUPPORTED',
      '공고 기반 추세는 조회 경로가 준비되면 표시됩니다.',
    ),
  )

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TECHNOLOGY TREND"
          title="기술 트렌드 — 출처별로 따로 봅니다"
          description="출처마다 측정 단위와 기간이 다릅니다. 출처 안에서만 순위를 비교하고, 합산하거나 종합 점수로 만들지 않습니다."
        />
        {target.data !== null && target.data !== undefined && (
          <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
            <p className="text-[12px] text-brand-faint">비교 대상 기술</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
              {target.data.targetRole} 수요 상위 {techIds.length}개
            </p>
          </div>
        )}
      </div>

      <div className="mt-7 grid gap-4">
        {/*
          목표 직무가 없으면 비교할 기술 목록이 없다. 임의로 고르지 않고 직무 선택으로
          보낸다 -- 목록을 화면이 정하면 그 자체가 근거 없는 순위가 된다.
        */}
        <ComputeStatePanel
          isLoading={target.isLoading || demands.isLoading}
          error={target.error ?? demands.error}
          state={demands.data}
          loadingLabel="비교할 기술 목록을 불러오는 중입니다."
          onRetry={() => void demands.refetch()}
        />

        {target.data === null && !target.isLoading && (
          <p className="text-[12.5px] leading-[1.7] text-brand-muted">
            목표 직무를 고르면 그 직무가 요구하는 기술을 출처별로 비교합니다.{' '}
            <Link to="/roles" className="font-semibold text-brand-600 hover:underline">
              목표 직무 고르기
            </Link>
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map((source) => (
            <TrendSourceCard key={source.id} source={source} />
          ))}
        </div>

        {/*
          단위 범례. 세 막대의 길이가 각 출처 안에서만 상대값이라는 것을 본문 아래에
          한 번 더 밝힌다.
        */}
        <ul className="flex flex-wrap gap-2">
          {sources.map((source) => (
            <li
              key={source.id}
              className="rounded-full border border-brand-line bg-white/70 px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
            >
              {source.unit}
            </li>
          ))}
        </ul>
      </div>

      <PageFootnote>
        각 출처 안에서만 순위를 비교합니다. 출처 간 순위 차이는 데이터 성격의 차이이며 우열이
        아닙니다. 값이 없는 기간과 기술은 0으로 채우지 않습니다.
      </PageFootnote>
    </div>
  )
}
