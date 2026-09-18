import type { JobDemandDto } from '@/features/matching/api/types'

/**
 * 현재 채용시장 기술 수요를 화면이 그릴 모양으로 · 티켓 S15P21E102-339.
 *
 * 서버가 준 `rank`·건수·비율을 그대로 옮긴다. 비율을 건수/분모로 다시 만들지 않는데,
 * C가 중복 제거와 품질 제외를 거쳐 만든 분모를 우리가 모르기 때문이다 — 다시 나누면
 * 같은 화면의 두 수치가 어긋난다.
 *
 * "값이 있는 상태인가"는 여기서 다시 판정하지 않고 `hasComputedValue`가 내린 답을
 * 받는다. 화면마다 `dataStatus === 'READY'`를 적으면 `PARTIAL`을 빠뜨린 화면이 생기고,
 * 그 화면은 일부만 읽힌 사용자에게 아무것도 보여주지 않는다. 값이 없는 상태의 문구는
 * `ComputeStatePanel`이 갖는다.
 *
 * (이 모듈이 그 함수를 직접 부르지 않는 것은 테스트 때문이기도 하다. `npm test`는 Vite
 * 없이 node로 돌아 `@/` alias를 해석하지 못하므로, 여기 있는 모듈은 실행 시점 import
 * 없이 타입만 가져온다.)
 */

export interface MarketDemandRow {
  techId: string
  rank: number
  totalCount: number
  totalRatio: number
}

export interface MarketDemandView {
  /** `ROWS`일 때만 본문을 그린다. `EMPTY`는 값은 왔는데 셀 기술이 없는 경우다. */
  kind: 'ROWS' | 'EMPTY' | 'PENDING'
  rows: MarketDemandRow[]
  /** 막대의 기준. 1위 건수이며 고정값을 쓰지 않는다. */
  topCount: number
  jobCount: number | null
  matchingJobCount: number | null
  asOf: string | null
}

const PENDING: MarketDemandView = {
  kind: 'PENDING',
  rows: [],
  topCount: 0,
  jobCount: null,
  matchingJobCount: null,
  asOf: null,
}

/**
 * @param hasValue `hasComputedValue(demand)`의 결과. 화면이 그 공용 판정을 넘겨 준다.
 */
export function marketDemandView(
  demand: JobDemandDto | undefined,
  hasValue: boolean,
): MarketDemandView {
  if (demand === undefined || !hasValue) {
    return PENDING
  }

  const rows = demand.technologies
    .filter((technology) => technology.totalCount > 0)
    .map((technology) => ({
      techId: technology.techId,
      rank: technology.rank,
      totalCount: technology.totalCount,
      totalRatio: technology.totalRatio,
    }))
    .sort((left, right) => left.rank - right.rank)

  return {
    kind: rows.length === 0 ? 'EMPTY' : 'ROWS',
    rows,
    topCount: Math.max(0, ...rows.map((row) => row.totalCount)),
    jobCount: demand.basis.jobCount,
    matchingJobCount: demand.basis.matchingJobCount,
    asOf: demand.basis.asOf,
  }
}
