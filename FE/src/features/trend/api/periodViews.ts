import type { TechnologyTrendDto } from '@/features/trend/api/trendApi'
import { buildSourceView } from '@/features/trend/api/adapter'
import { groupTrendRowsByPeriod } from '@/features/trend/model/periodRows'
import type { SourceJudgement } from '@/features/trend/model/periodRows'
import type { TrendSourceId, TrendSourceView } from '@/features/trend/model/view'

/**
 * 기간별 카드 조립 · 티켓 S15P21E102-329.
 *
 * 묶는 일은 `model/periodRows`가, 카드 한 장을 만드는 일은 `buildSourceView`가 한다.
 * 여기서는 둘을 잇기만 한다 — 순위·상태 판정을 다시 구현하지 않는 것이 요점이다.
 * compare 경로와 개요 경로가 같은 `buildSourceView`를 쓰므로, 같은 기간의 카드는 어느
 * 요청으로 왔든 같게 보인다.
 */

/** 한 원천의 기간 목록과 기간별 카드. 기간은 오름순이고 마지막이 제일 최신이다. */
export interface TrendSourcePeriods {
  periods: string[]
  viewByPeriod: Map<string, TrendSourceView>
  /**
   * 서버가 내린 판정. 그릴 기간이 없을 때 화면이 이유를 말하는 데 쓴다
   * (티켓 S15P21E102-329 D1). 기간이 있는 카드의 상태는 `buildSourceView`가 정한다.
   */
  judgements: SourceJudgement[]
}

export function toTrendPeriodViews(
  dtos: readonly TechnologyTrendDto[],
  techNames: ReadonlyMap<string, string>,
): Map<TrendSourceId, TrendSourcePeriods> {
  const grouped = groupTrendRowsByPeriod(dtos)
  const result = new Map<TrendSourceId, TrendSourcePeriods>()

  for (const [id, entry] of grouped) {
    const viewByPeriod = new Map<string, TrendSourceView>()
    for (const period of entry.periods) {
      viewByPeriod.set(
        period,
        buildSourceView(id, entry.unit, entry.rowsByPeriod.get(period) ?? [], period, techNames),
      )
    }
    result.set(id, { periods: entry.periods, viewByPeriod, judgements: entry.judgements })
  }
  return result
}
