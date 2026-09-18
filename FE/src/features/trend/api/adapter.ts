import type {
  TechnologyTrendDto,
  TrendCompareDto,
  TrendCompareRowDto,
  TrendSourceDto,
} from '@/features/trend/api/trendApi'
import type {
  TrendRankRow,
  TrendSeriesView,
  TrendSourceId,
  TrendSourceView,
} from '@/features/trend/model/view'
import { rankObservableRows } from '@/features/trend/model/ranking'
import { pointsForSource } from '@/features/trend/model/periods'

/**
 * Trend DTO를 화면 타입으로 (S15P21E102-279).
 *
 * 수치를 만들지 않는다. 비율도 증감도 C가 계산한 값이고, 화면이 두 점을 빼서 만들면
 * 결측 기간이 있을 때 실제와 다른 변화를 말하게 된다.
 *
 * 값이 없는 자리는 `—`로 남긴다. 0으로 채우면 "관측했더니 0이었다"가 되어 없는 순위가
 * 생긴다.
 */

const SOURCE_IDS: readonly TrendSourceId[] = ['GITHUB_WEEKLY', 'GITHUB_ARCHIVE', 'JOB']

const LABEL: Readonly<Record<TrendSourceId, string>> = {
  GITHUB_WEEKLY: 'GitHub 주간 활동',
  GITHUB_ARCHIVE: 'GitHub 월별 활동',
  JOB: '채용공고 수요',
}

const FOOTNOTE: Readonly<Record<TrendSourceId, string>> = {
  GITHUB_WEEKLY: '공개 저장소의 주간 활동 관측입니다. 비공개 저장소는 포함하지 않습니다.',
  GITHUB_ARCHIVE: '월별 GitHub 활동입니다. 완료된 달만 표시합니다.',
  JOB: '수집된 채용공고의 월별 요구 건수입니다.',
}

export function toSourceId(value: string): TrendSourceId | null {
  return SOURCE_IDS.includes(value as TrendSourceId) ? (value as TrendSourceId) : null
}

function unitDisplayName(sourceId: TrendSourceId, value: string | null): string {
  if (value === null) return sourceId === 'JOB' ? '채용공고 수요' : 'GitHub 활동'
  const normalized = value.trim().toUpperCase()
  if (normalized === 'EVENTS' || normalized === 'EVENT_COUNT') return 'GitHub 활동'
  if (normalized === 'REPOSITORIES' || normalized === 'REPOSITORY_COUNT') return '저장소'
  if (normalized === 'JOB_POSTINGS' || normalized === 'JOB_COUNT') return '채용공고 수요'
  return value
}

function reasonText(
  reasons: readonly string[],
  fallback: string,
  status: TrendSourceDto['dataStatus'],
): string {
  if (reasons.length === 0) return fallback
  if (status === 'PARTIAL') {
    return '일부 공개 저장소의 분석이 완료되지 않아 집계 범위에 제한이 있습니다.'
  }
  return reasons.some((reason) => /^[A-Z0-9_:.-]+$/.test(reason))
    ? '비교할 데이터가 충분하지 않습니다.'
    : reasons.join(' · ')
}

/** 표기 문자열. 값이 없으면 지어내지 않고 `—`를 둔다. */
function numberText(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value.toLocaleString('ko-KR')}${suffix}`
}

function changeText(absolute: number | null, relative: number | null): string {
  if (absolute === null && relative === null) {
    return '—'
  }
  if (relative !== null) {
    const arrow = relative >= 0 ? '↑' : '↓'
    return `${arrow} ${Math.abs(relative * 100).toFixed(1)}%`
  }
  const arrow = (absolute as number) >= 0 ? '↑' : '↓'
  return `${arrow} ${Math.abs(absolute as number).toLocaleString('ko-KR')}`
}

function direction(absolute: number | null, relative: number | null): 'UP' | 'DOWN' | null {
  const value = relative ?? absolute
  if (value === null) {
    return null
  }
  return value >= 0 ? 'UP' : 'DOWN'
}

/**
 * 상세 화면의 계열.
 *
 * 기간 배열을 그대로 쓴다. 빠진 달을 채워 넣지 않는 것이 계약이고, 채우면 없는 관측을
 * 화면이 만들어 낸다.
 */
export function toTrendSeries(
  dto: TechnologyTrendDto,
  earliestMonth?: string,
): TrendSeriesView[] {
  return dto.sources
    .map((source) => {
      const id = toSourceId(source.sourceId)
      if (id === null) {
        return null
      }
      /*
       * 주간은 월 범위로 자르지 않는다 (티켓 S15P21E102-329).
       *
       * 주간 head 는 누적이고 BE 는 여기에 기간 selector 를 주지 않는다
       * (`CTrend.Selector.weekly(tech)` 는 periods 를 받지 않으며, 보내면 C 가 422 로
       * 거절한다). 그래서 3/6/12개월 버튼은 주간과 아무 관계가 없는데도 월 하한으로
       * 주차를 잘라내고 있었다 — 사용자가 "최근 3개월"을 눌렀다고 그보다 앞선 주차의
       * 관측이 없어지는 것은 아니다. 월별·공고만 요청한 범위로 좁힌다.
       */
      const selectedPoints = pointsForSource(id, source.points, earliestMonth)
      const points = selectedPoints.map((point) => ({
        period: point.period,
        value: point.value,
      }))
      const last = selectedPoints.at(-1)
      const unit = unitDisplayName(id, source.unit)
      return {
        sourceId: id,
        label: LABEL[id],
        status: source.dataStatus,
        axisLabel: unit,
        latestText: last === undefined ? null : numberText(last.value),
        deltaText:
          last === undefined ? null : changeText(last.absoluteChange, last.relativeChange),
        points,
        note: reasonText(source.reasons, FOOTNOTE[id], source.dataStatus),
      } satisfies TrendSeriesView
    })
    .filter((series): series is TrendSeriesView => series !== null)
}

/**
 * 개요 화면의 출처 카드.
 *
 * 공고 수요는 비교 후보를 고르는 근거이고, 각 카드 순위는 해당 출처의 실제 관측값이다.
 * `READY + 0`은 관측된 값으로 남기며, 미관측/표본 부족은 순위를 받지 않는다.
 */
export function toTrendSource(
  compare: TrendCompareDto,
  techNames: ReadonlyMap<string, string>,
): TrendSourceView | null {
  const id = toSourceId(compare.sourceId)
  if (id === null) {
    return null
  }
  return buildSourceView(
    id,
    compare.unit,
    compare.rows,
    compare.rows[0]?.period ?? '기간 미정',
    techNames,
  )
}

/**
 * 한 출처 · 한 기간의 카드.
 *
 * `toTrendSource`(compare 응답)와 `toTrendPeriodViews`(기술별 상세 응답)가 같은 함수를
 * 쓴다. 두 경로가 순위·상태 판정을 따로 구현하면 같은 화면의 같은 카드가 어느 요청으로
 * 왔는지에 따라 다르게 보인다.
 */
export function buildSourceView(
  id: TrendSourceId,
  unit: string | null,
  sourceRowList: readonly TrendCompareRowDto[],
  basis: string,
  techNames: ReadonlyMap<string, string>,
): TrendSourceView {
  const ranking = rankObservableRows(sourceRowList)
  const sourceRows = new Map(sourceRowList.map((row) => [row.techId, row]))
  const rows: TrendRankRow[] = ranking.observed.map((row) => {
    const source = sourceRows.get(row.techId)
    return {
      rank: row.rank,
      techId: row.techId,
      techName: techNames.get(row.techId) ?? '알 수 없는 기술',
      dataStatus: row.dataStatus,
      statusReason: source?.statusReason ?? '',
      observedValue: row.value,
      share: numberText(row.value),
      delta: changeText(source?.absoluteChange ?? null, source?.relativeChange ?? null),
      direction: direction(source?.absoluteChange ?? null, source?.relativeChange ?? null),
    }
  })
  const unobservedRows = ranking.unobserved.map((row) => {
    const source = sourceRows.get(row.techId)
    return {
      techId: row.techId,
      techName: techNames.get(row.techId) ?? '알 수 없는 기술',
      dataStatus: row.dataStatus,
      statusReason: source?.statusReason ?? '',
    }
  })
  return {
    id,
    label: LABEL[id],
    unit: unitDisplayName(id, unit),
    // 한 기술도 값이 없으면 카드 전체가 비어 있는 것이다. 빈 표를 READY로 그리면
    // 사용자는 "관측했더니 전부 0"으로 읽는다.
    status:
      rows.length === 0
        ? unavailableStatus(unobservedRows.map((row) => row.dataStatus))
        : rows.some((row) => row.dataStatus === 'PARTIAL')
          ? 'PARTIAL'
          : 'READY',
    basis,
    scopeNote: null,
    maximumObservedValue: ranking.maximumObservedValue,
    rows,
    unobservedRows,
    footnote: FOOTNOTE[id],
  }
}

function unavailableStatus(statuses: readonly TrendSourceView['status'][]): TrendSourceView['status'] {
  if (statuses.includes('PREPARING')) return 'PREPARING'
  if (statuses.includes('INSUFFICIENT_DATA')) return 'INSUFFICIENT_DATA'
  if (statuses.includes('FAILED')) return 'FAILED'
  if (statuses.includes('NOT_SUPPORTED')) return 'NOT_SUPPORTED'
  return 'NO_DATA'
}

/** 조회조차 하지 못한 출처. 빈 표 대신 이유를 남긴다. */
export function unavailableSource(
  id: TrendSourceId,
  status: TrendSourceView['status'],
  scopeNote: string,
): TrendSourceView {
  return {
    id,
    label: LABEL[id],
    unit: id === 'JOB' ? '채용공고 수요' : 'GitHub 활동',
    status,
    basis: '조회 불가',
    scopeNote,
    maximumObservedValue: null,
    rows: [],
    unobservedRows: [],
    footnote: FOOTNOTE[id],
  }
}

/** 상세 화면에서도 쓰는 출처 표기. 카드와 계열이 같은 이름을 써야 한다. */
export function sourceLabel(dto: TrendSourceDto): string {
  const id = toSourceId(dto.sourceId)
  return id === null ? dto.sourceId : LABEL[id]
}
