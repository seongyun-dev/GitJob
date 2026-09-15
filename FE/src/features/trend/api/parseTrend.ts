import {
  TREND_DIRECTIONS,
  TREND_SOURCE_IDS,
  type TechnologyTrend,
  type TrendComparison,
  type TrendOverview,
  type TrendPoint,
  type TrendRankRow,
  type TrendSeries,
  type TrendSource,
} from '@/features/trend/api/types'
import { readers } from '@/shared/api/parse'
import { DATA_STATUSES } from '@/shared/types/domain'

/**
 * 트렌드 응답의 런타임 파싱 · 티켓 S15P21E102-281.
 *
 * 왜 선언만 두지 않는지는 `shared/api/parse.ts` 머리말에 적었다.
 *
 * 이 계열에서 특히 중요한 것은 **`status`가 `READY`가 아닐 때 값을 지어내지 않는
 * 것**이다. 파서는 상태를 보정하지 않는다 — `PREPARING`인데 `points`가 차 있으면
 * 그대로 통과시키고, 무엇을 그릴지는 화면이 `status`로 정한다. 파서가 상태에 맞춰
 * 배열을 비우면 서버 계약이 어긋난 사실이 조용히 지워진다.
 */

const r = readers('trend')

function parseRankRow(value: unknown, at: string): TrendRankRow {
  const source = r.item(value, at)
  return {
    rank: r.number(source, 'rank', at),
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    share: r.string(source, 'share', at),
    delta: r.string(source, 'delta', at),
    direction: r.enum(source, 'direction', at, TREND_DIRECTIONS),
  }
}

function parseSource(value: unknown, at: string): TrendSource {
  const source = r.item(value, at)
  return {
    id: r.enum(source, 'id', at, TREND_SOURCE_IDS),
    label: r.string(source, 'label', at),
    unit: r.string(source, 'unit', at),
    status: r.enum(source, 'status', at, DATA_STATUSES),
    basis: r.string(source, 'basis', at),
    scopeNote: r.nullableString(source, 'scopeNote', at),
    rows: r.array(source, 'rows', at).map((item, i) => parseRankRow(item, `${at}.rows[${i}]`)),
    footnote: r.string(source, 'footnote', at),
  }
}

export function parseTrendOverview(value: unknown): TrendOverview {
  const at = 'trendOverview'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    sources: r
      .array(source, 'sources', at)
      .map((item, i) => parseSource(item, `${at}.sources[${i}]`)),
  }
}

function parsePoint(value: unknown, at: string): TrendPoint {
  const source = r.item(value, at)
  return {
    period: r.string(source, 'period', at),
    value: r.number(source, 'value', at),
  }
}

function parseSeries(value: unknown, at: string): TrendSeries {
  const source = r.item(value, at)
  return {
    sourceId: r.enum(source, 'sourceId', at, TREND_SOURCE_IDS),
    label: r.string(source, 'label', at),
    status: r.enum(source, 'status', at, DATA_STATUSES),
    axisLabel: r.string(source, 'axisLabel', at),
    latestText: r.nullableString(source, 'latestText', at),
    deltaText: r.nullableString(source, 'deltaText', at),
    points: r.array(source, 'points', at).map((item, i) => parsePoint(item, `${at}.points[${i}]`)),
    note: r.string(source, 'note', at),
  }
}

function parseTechnologyTrendBody(source: Record<string, unknown>, at: string): TechnologyTrend {
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    series: r.array(source, 'series', at).map((item, i) => parseSeries(item, `${at}.series[${i}]`)),
  }
}

export function parseTechnologyTrend(value: unknown): TechnologyTrend {
  const at = 'technologyTrend'
  return parseTechnologyTrendBody(r.root(value, at), at)
}

export function parseTrendComparison(value: unknown): TrendComparison {
  const at = 'trendComparison'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    sourceId: r.enum(source, 'sourceId', at, TREND_SOURCE_IDS),
    axisLabel: r.string(source, 'axisLabel', at),
    technologies: r
      .array(source, 'technologies', at)
      .map((item, i) =>
        parseTechnologyTrendBody(r.item(item, `${at}.technologies[${i}]`), `${at}.technologies[${i}]`),
      ),
  }
}
