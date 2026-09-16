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
