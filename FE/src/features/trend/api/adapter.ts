import type {
  TechnologyTrendDto,
  TrendCompareDto,
  TrendSourceDto,
} from '@/features/trend/api/trendApi'
import type {
  TrendRankRow,
  TrendSeriesView,
  TrendSourceId,
  TrendSourceView,
} from '@/features/trend/model/view'

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
  GITHUB_WEEKLY: 'GITHUB · 주간 활동',
  GITHUB_ARCHIVE: 'GITHUB · 월별 Archive',
  JOB: 'JOB · 채용공고',
}

const FOOTNOTE: Readonly<Record<TrendSourceId, string>> = {
  GITHUB_WEEKLY: '공개 저장소의 주간 활동 관측입니다. 비공개 저장소는 포함하지 않습니다.',
  GITHUB_ARCHIVE: '월별 commit 관측입니다. 완료된 달만 포함하며 미완료 월은 비어 있습니다.',
  JOB: '수집된 채용공고의 월별 요구 건수입니다.',
}

function toSourceId(value: string): TrendSourceId | null {
  return SOURCE_IDS.includes(value as TrendSourceId) ? (value as TrendSourceId) : null
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
export function toTrendSeries(dto: TechnologyTrendDto): TrendSeriesView[] {
  return dto.sources
    .map((source) => {
      const id = toSourceId(source.sourceId)
      if (id === null) {
        return null
      }
      const points = source.points.map((point) => ({
        period: point.period,
        value: point.value,
      }))
      const last = source.points.at(-1)
      const unit = source.unit ?? '관측값'
      return {
        sourceId: id,
        label: LABEL[id],
        status: source.dataStatus,
        axisLabel: unit,
        latestText: last === undefined ? null : numberText(last.value),
        deltaText:
          last === undefined ? null : changeText(last.absoluteChange, last.relativeChange),
        points,
        note: source.reasons.length === 0 ? FOOTNOTE[id] : source.reasons.join(' · '),
      } satisfies TrendSeriesView
    })
    .filter((series): series is TrendSeriesView => series !== null)
}

/**
 * 개요 화면의 출처 카드.
 *
 * 순위는 비교 응답이 준 순서를 그대로 쓴다. 값이 없는 기술은 뒤로 밀리되 순번은
 * 유지한다 — 순위를 화면이 다시 매기면 "값 없음"이 최하위라는 판정이 되어 버린다.
 */
export function toTrendSource(
  compare: TrendCompareDto,
  techNames: ReadonlyMap<string, string>,
): TrendSourceView | null {
  const id = toSourceId(compare.sourceId)
  if (id === null) {
    return null
  }
  const rows: TrendRankRow[] = compare.rows.map((row, index) => ({
    rank: index + 1,
    techId: row.techId,
    techName: techNames.get(row.techId) ?? row.techId,
    share: numberText(row.value),
    delta: changeText(row.absoluteChange, row.relativeChange),
    direction: direction(row.absoluteChange, row.relativeChange),
  }))
  const ready = compare.rows.filter((row) => row.value !== null)
  return {
    id,
    label: LABEL[id],
    unit: compare.unit ?? '관측값',
    // 한 기술도 값이 없으면 카드 전체가 비어 있는 것이다. 빈 표를 READY로 그리면
    // 사용자는 "관측했더니 전부 0"으로 읽는다.
    status: ready.length === 0 ? 'NO_DATA' : 'READY',
    basis: compare.rows[0]?.period ?? '기간 미정',
    scopeNote: null,
    rows: ready.length === 0 ? [] : rows,
    footnote: FOOTNOTE[id],
  }
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
    unit: id === 'JOB' ? '월별 공고 요구 건수' : '관측값',
    status,
    basis: '조회 불가',
    scopeNote,
    rows: [],
    footnote: FOOTNOTE[id],
  }
}

/** 상세 화면에서도 쓰는 출처 표기. 카드와 계열이 같은 이름을 써야 한다. */
export function sourceLabel(dto: TrendSourceDto): string {
  const id = toSourceId(dto.sourceId)
  return id === null ? dto.sourceId : LABEL[id]
}
