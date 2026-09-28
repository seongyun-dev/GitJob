import type {
  TechnologyTrendDto,
  TrendCompareDto,
  TrendCompareRowDto,
  TrendRankingDto,
  TrendSourceDto,
} from '@/features/trend/api/trendApi'
import type {
  TrendRankRow,
  TrendSeriesView,
  TrendSourceId,
  TrendSourceView,
} from '@/features/trend/model/view'
import type { MarketDemandView } from '@/features/trend/model/marketDemand'
import { marketRankRows } from '@/features/trend/model/marketDemand'
import {
  observedShareText,
  observedValueText,
  rankObservableRows,
} from '@/features/trend/model/ranking'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
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
        latestText: last === undefined ? null : observedValueText(last.value, last.denominator),
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

/**
 * 기간별 기술 순위를 출처 카드로 · 티켓 S15P21E102-346.
 *
 * 서버가 Registry 전체를 놓고 정렬한 결과를 그대로 옮긴다. 화면은 어느 기술을 보여
 * 줄지 고르지 않는다 — 기간이 바뀌면 기술 종류도 바뀌는 것이 정상이다.
 *
 * `dataStatus` 는 행마다 서버 판정을 그대로 싣는다. 표본이 얇아도 값은 값이므로
 * 순위에 남기고, 그 사실은 카드가 아래 한 줄로만 말한다(S15P21E102-327).
 */
export function trendRankingSource(
  id: TrendSourceId,
  unit: string,
  basis: string | null,
  ranking: TrendRankingDto,
): TrendSourceView {
  const rows: TrendRankRow[] = ranking.technologies.map((item) => ({
    rank: item.rank,
    techId: item.techId,
    /*
     * 이름은 서버 것이 먼저다. 없으면 화면 사전을 보고, 그래도 없으면 tech_id 를
     * 그대로 쓴다 — id 를 알면서 "알 수 없는 기술"이라고 적으면 아는 것을 버리는 것이다.
     */
    techName: item.displayName ?? technologyDisplayName(item.techId, item.techId),
    dataStatus: item.dataStatus,
    statusReason: ranking.statusReason,
    observedValue: item.value,
    // 분모가 있으면 비중으로 적는다. 주차마다 모집단이 달라(4,045 vs 133) raw count
    // 를 그대로 두면 기간을 옮겼을 때 값이 줄어든 것처럼 읽힌다.
    share: observedShareText(item.value, ranking.sampleRepoCount),
    // 한 기간의 순위라 전기(前期)가 없다. 0 으로 채우면 없는 관측을 주장하게 된다.
    delta: '—',
    direction: null,
  }))
  return {
    id,
    label: LABEL[id],
    unit,
    status: rows.length === 0 ? 'NO_DATA' : 'READY',
    basis: basis ?? '기간 미정',
    scopeNote: null,
    maximumObservedValue: rows[0]?.observedValue ?? null,
    rows,
    unobservedRows: [],
    footnote: FOOTNOTE[id],
  }
}

/**
 * 현재 채용시장 분포를 `채용공고 수요` 카드로 · 티켓 S15P21E102-342.
 *
 * 상단에 큰 섹션을 따로 두면 아래 세 카드가 한 줄에서 같은 크기로 읽히지 않는다.
 * 그래서 시장 분포를 다른 두 출처와 **같은 카드 컴포넌트**에 넣는다.
 *
 * `unit`은 카드 제목이라 세 카드의 제목 체계를 그대로 따른다. 보조 라벨은 카드 안의
 * eyebrow(`label`)와 기준 문구로만 쓰고 별도 대형 제목을 만들지 않는다.
 */
export function marketDemandSource(
  view: MarketDemandView,
  basis: string,
  statusNote: string | null,
  techNames: ReadonlyMap<string, string>,
  limit: number,
): TrendSourceView {
  const rows = marketRankRows(view, limit).map((row) => ({
    ...row,
    techName: techNames.get(row.techId) ?? row.techId,
  }))
  return {
    id: 'JOB',
    label: LABEL.JOB,
    // eyebrow 가 출처 이름이고 제목은 무엇을 세는지다 — 옆 카드의 `GitHub 활동`·`저장소`와
    // 같은 자리다. 둘 다 출처 이름을 쓰면 카드 머리에 같은 말이 두 번 적힌다.
    unit: '공고 요구 건수',
    // 값이 없는 상태는 카드가 배지와 안내문으로 말한다. 빈 표를 READY로 그리면
    // 사용자는 "세어 봤더니 하나도 없다"로 읽는다. 값이 없을 때의 판정은 서버가 준
    // 것을 그대로 쓴다 -- FAILED 를 "준비 중"으로 그리면 기다리면 낫는 상태가 된다.
    status:
      view.kind === 'ROWS'
        ? view.status === 'PARTIAL'
          ? 'PARTIAL'
          : 'READY'
        : view.kind === 'EMPTY'
          ? 'NO_DATA'
          : view.status,
    basis,
    scopeNote: statusNote,
    maximumObservedValue: rows.length === 0 ? null : view.topCount,
    rows,
    unobservedRows: [],
    footnote: '지금 수집된 채용공고 전체에서 요구된 기술입니다. 목표 직무와 무관합니다.',
  }
}

/**
 * 그릴 값이 없는 출처. 빈 표 대신 이유를 남긴다.
 *
 * @param basis 기준 문구. 조회가 아직 끝나지 않았으면 "조회 불가"가 아니다 —
 *     묻고 있는 중인데 못 묻는다고 적으면 카드가 사실과 다른 말을 한다
 *     (티켓 S15P21E102-345).
 */
export function unavailableSource(
  id: TrendSourceId,
  status: TrendSourceView['status'],
  scopeNote: string,
  basis = '조회 불가',
): TrendSourceView {
  return {
    id,
    label: LABEL[id],
    unit: id === 'JOB' ? '채용공고 수요' : 'GitHub 활동',
    status,
    basis,
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
