import type { JobDemandDto } from '@/features/matching/api/types'
import type { TrendRankRow } from '@/features/trend/model/view'
import type { DataStatus } from '@/shared/types/domain'

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
  /**
   * 서버가 내린 판정을 그대로 들고 간다.
   *
   * `PENDING`을 전부 "준비 중"으로 그리면 `FAILED`가 기다리면 낫는 상태로 읽힌다.
   * 아직 조회 전이라 판정 자체가 없을 때만 `PREPARING`이다.
   */
  status: DataStatus
  rows: MarketDemandRow[]
  /** 막대의 기준. 1위 건수이며 고정값을 쓰지 않는다. */
  topCount: number
  jobCount: number | null
  matchingJobCount: number | null
  asOf: string | null
}

const PENDING: MarketDemandView = {
  kind: 'PENDING',
  status: 'PREPARING',
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
  if (demand === undefined) {
    return PENDING
  }
  if (!hasValue) {
    return { ...PENDING, status: demand.dataStatus }
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
    status: demand.dataStatus,
    rows,
    topCount: Math.max(0, ...rows.map((row) => row.totalCount)),
    jobCount: demand.basis.jobCount,
    matchingJobCount: demand.basis.matchingJobCount,
    asOf: demand.basis.asOf,
  }
}

/**
 * 카드 한 장이 그릴 순위 줄 · 티켓 S15P21E102-342.
 *
 * 시장 분포를 `TrendSourceCard`의 `JOB` 칸에 그대로 넣기 위한 변환이다. 카드를 새로
 * 만들지 않는 이유는 세 출처 카드가 같은 크기·같은 표 구조여야 하기 때문이다 — 하나만
 * 다른 컴포넌트로 그리면 그 순간 열 너비와 높이가 갈라진다.
 *
 * `delta`는 항상 `—`다. 시장 분포는 한 시점의 Snapshot이라 전기(前期)가 없다. 0으로
 * 채우면 "지난 기간과 같았다"는 없는 관측을 주장하게 된다.
 *
 * `share`는 건수다. 옆 두 카드의 같은 열도 관측 건수를 쓰므로, 여기만 비율을 넣으면
 * 같은 열에서 서로 다른 단위를 읽게 된다. 비율은 막대 길이와 기준 문구가 말한다.
 */
export function marketRankRows(view: MarketDemandView, limit: number): TrendRankRow[] {
  return view.rows.slice(0, limit).map((row) => ({
    rank: row.rank,
    techId: row.techId,
    // 표시 이름은 Registry 라벨을 아는 쪽이 채운다.
    techName: row.techId,
    dataStatus: 'READY' as DataStatus,
    statusReason: 'NONE',
    observedValue: row.totalCount,
    share: `${row.totalCount.toLocaleString('ko-KR')}건`,
    delta: '—',
    direction: null,
  }))
}
