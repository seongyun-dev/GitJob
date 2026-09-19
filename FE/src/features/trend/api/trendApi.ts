import type { DataStatus } from '@/shared/types/domain'
import { get } from '@/shared/api/client'

/**
 * 기술 Trend 조회 (S15P21E102-279).
 *
 * 개인 결과가 아니라 로그인만 확인한다. 계약은 `docs/be/c-compute-public-api.md` §4-8·4-9.
 *
 * **출처별로 따로 받는다.** 응답이 배열인 것이 계약의 핵심이고, 합성 점수 필드는 없다.
 * 출처 하나가 비어도 요청은 성공이며 그 카드만 비운다.
 */

export interface TrendPointDto {
  period: string
  status: string | null
  /** 미집계 기간은 `null`. 0이 아니다. */
  value: number | null
  denominator: number | null
  ratio: number | null
  absoluteChange: number | null
  relativeChange: number | null
}

export interface TrendSourceDto {
  sourceId: string
  cSource: string
  dataStatus: DataStatus
  statusReason: string
  /** 무엇을 세는지. 출처 간 비교를 막기 위해 화면이 반드시 표시한다. */
  unit: string | null
  metric: string | null
  granularity: string | null
  periods: string[]
  points: TrendPointDto[]
  reasons: string[]
}

export interface TechnologyTrendDto {
  techId: string
  sources: TrendSourceDto[]
}

export interface TrendCompareRowDto {
  techId: string
  dataStatus: DataStatus
  statusReason: string
  period: string | null
  value: number | null
  ratio: number | null
  absoluteChange: number | null
  relativeChange: number | null
}

export interface TrendCompareDto {
  sourceId: string
  cSource: string
  unit: string | null
  rows: TrendCompareRowDto[]
}

export interface TrendTargetParams {
  targetRole?: string
  regions?: readonly string[]
  careerLevels?: readonly string[]
}

function appendTarget(query: URLSearchParams, target: TrendTargetParams): void {
  if (target.targetRole !== undefined && target.targetRole !== '') {
    query.set('targetRole', target.targetRole)
  }
  target.regions?.forEach((region) => query.append('regions', region))
  target.careerLevels?.forEach((level) => query.append('careerLevels', level))
}

/**
 * 기술 하나의 출처별 추세.
 *
 * @param periods 월별 Archive를 볼 기간. 비우면 주간 출처만 조회한다. 화면이 임의로
 *                최근 몇 달을 고르지 않는 이유는, 표시한 기간과 실제 계산 기간이
 *                달라지면 안 되기 때문이다.
 */
export function fetchTechnologyTrends(
  techId: string,
  periods: readonly string[],
  target: TrendTargetParams = {},
): Promise<TechnologyTrendDto> {
  const query = new URLSearchParams()
  periods.forEach((period) => query.append('periods', period))
  appendTarget(query, target)
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return get<TechnologyTrendDto>(`/technologies/${encodeURIComponent(techId)}/trends${suffix}`)
}

/** 기술 교차 비교. 한 번에 한 출처만 본다 — 섞으면 분모가 다른 값이 한 축에 들어간다. */
export function fetchTrendCompare(params: {
  source: string
  techIds: readonly string[]
  periods: readonly string[]
  target?: TrendTargetParams
}): Promise<TrendCompareDto> {
  const query = new URLSearchParams({ source: params.source })
  params.techIds.forEach((techId) => query.append('techIds', techId))
  params.periods.forEach((period) => query.append('periods', period))
  appendTarget(query, params.target ?? {})
  return get<TrendCompareDto>(`/trends/compare?${query.toString()}`)
}

/**
 * 한 기간에 실제로 많이 관측된 기술 · 티켓 S15P21E102-346.
 *
 * `techIds` 를 보내지 않는 것이 `/trends/compare` 와의 차이다. 비교는 "이 기술들 중
 * 누가 위인가"를 묻고 이쪽은 "이 기간에 무엇이 많았는가"를 묻는다. 후자는 화면이
 * 후보를 고르는 순간 다른 질문이 되므로, 모집단 전체를 서버가 본다.
 */
export interface TrendRankingDto {
  dataStatus: DataStatus
  statusReason: string
  retryAfterSec: number | null
  sourceId: string
  granularity: string
  period: string | null
  /**
   * 이 출처가 실제로 게시한 기간 목록, 오름순 · 티켓 S15P21E102-329.
   *
   * 카드 안의 기간 이동이 이것으로 움직인다. 화면이 달력으로 계산하면 아직 집계되지
   * 않은 주를 물어 값이 있는데도 빈 카드가 뜬다.
   */
  availablePeriods: string[]
  /** 순위 값의 단위. GitHub 출처는 `REPOSITORIES` — 그 기술이 관측된 저장소 수. */
  unit: string | null
  /**
   * 이 기간의 모집단. `value / sampleRepoCount` 가 비중이다.
   *
   * 주차마다 크기가 달라(2026-08-31 = 4,045 / 09-07 = 133) 이것 없이 raw count 를
   * 기간끼리 비교하면 틀린다.
   */
  sampleRepoCount: number | null
  /** 순위를 매긴 모집단 크기. "상위 10개"가 무엇 중의 10개인지 밝힌다. */
  technologyPopulation: number | null
  technologies: {
    techId: string
    /** Registry 에 없는 기술이면 `null`. 이름을 지어내지 않는다. */
    displayName: string | null
    rank: number
    value: number
    dataStatus: DataStatus
  }[]
}

export function fetchTrendRankings(params: {
  source: string
  granularity: string
  /** 비우면 서버가 그 출처의 최신 게시 기간을 고른다. */
  period?: string
  limit?: number
}): Promise<TrendRankingDto> {
  const query = new URLSearchParams({
    source: params.source,
    granularity: params.granularity,
  })
  if (params.period !== undefined && params.period !== '') {
    query.set('period', params.period)
  }
  if (params.limit !== undefined) {
    query.set('limit', String(params.limit))
  }
  return get<TrendRankingDto>(`/trends/rankings?${query.toString()}`)
}
