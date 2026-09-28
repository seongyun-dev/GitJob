import type { DataStatus } from '@/shared/types/domain'

/**
 * 순위에 올릴 수 있는 상태 · 티켓 S15P21E102-327.
 *
 * 값이 있다는 것과 그 값을 의지할 수 있다는 것은 다르다. `TrendService.source()` 는
 * 실패·미준비 경로를 빈 points 로 보내지만, payload 의 status 가 `FAILED` ·
 * `PREPARING` · `NOT_SUPPORTED` 인데 수치가 남아 있는 경우가 있다. 그런 잔여 수치를
 * 순위에 올리면 실패를 측정처럼 보이게 한다.
 *
 * `INSUFFICIENT_DATA` 는 다르다. 측정은 끝났고 표본이 얇을 뿐이라 수치 자체는 유효하다.
 * `PARTIAL` 도 같은 이유로 넣는다.
 */
const RANKABLE_STATUSES: ReadonlySet<DataStatus> = new Set<DataStatus>([
  'READY',
  'PARTIAL',
  'INSUFFICIENT_DATA',
])

export interface TrendObservationRow {
  techId: string
  dataStatus: DataStatus
  value: number | null
}

export interface RankedTrendObservation extends Omit<TrendObservationRow, 'value'> {
  value: number
  rank: number
}

/**
 * A source card ranks every value that source actually observed.
 *
 * <h2>순위를 `READY` 로 막지 않는 이유 (티켓 S15P21E102-327)</h2>
 *
 * 막아 봤고, 화면이 비었다. 운영 TREND point 에는 `READY` 가 하나도 없다 —
 * 2026-09-18 기준 head 221건이 전부 `INSUFFICIENT_DATA` 였고, 기술마다 매칭되는
 * 공개 저장소가 세 개뿐이라 근거 임계를 넘지 못한다. 그 아래 수치는 실측이다
 * (2026-08 html 1,204,607 · javascript 878,599). 그것을 빼면 화면은 "아무것도
 * 측정하지 못했다"고 말하는데, 그건 "표본이 얇다"와 다르고 더 틀린 말이다.
 *
 * 그래서 순위는 값을 따라간다. 상태는 행에 그대로 실려 카드가 표시에 쓴다.
 * `dataStatus` 는 손대지 않는다 — 얇은 표본은 어디에 그려지든 얇은 표본이다.
 *
 * 문은 사라진 게 아니라 좁아졌다. {@link RANKABLE_STATUSES} 는 수치를 믿을 수 없는
 * 상태를 여전히 막는다.
 *
 * 값이 없는 행은 순위를 받지 않는다. 그것이 진짜 구분이다 — "측정하지 않았다"와
 * "얇은 근거로 측정했다"는 다르고, 길이 0 막대는 관측된 0 으로 읽힌다.
 */
export function rankObservableRows(rows: readonly TrendObservationRow[]): {
  observed: RankedTrendObservation[]
  unobserved: TrendObservationRow[]
  maximumObservedValue: number | null
} {
  const observed: RankedTrendObservation[] = rows
    .map((row, index) => ({ ...row, index }))
    .filter(
      (row): row is TrendObservationRow & { index: number; value: number } =>
        row.value !== null && RANKABLE_STATUSES.has(row.dataStatus),
    )
    .sort((left, right) => right.value - left.value || left.index - right.index)
    .map(({ index: _index, ...row }, index) => ({ ...row, rank: index + 1 }))
  const unobserved = rows.filter(
    (row) => row.value === null || !RANKABLE_STATUSES.has(row.dataStatus),
  )

  return {
    observed,
    unobserved,
    maximumObservedValue: observed[0]?.value ?? null,
  }
}

/**
 * 관측 수를 모집단 대비 비중으로 · 티켓 S15P21E102-346.
 *
 * 카드의 `비중` 칸은 분모가 있어야 읽힌다. 주차마다 모집단이 달라(2026-08-31 =
 * 4,045 · 09-07 = 133) raw count 를 그대로 적으면 기간끼리 비교할 때 틀린다.
 *
 * 분모를 모르면 count 를 그대로 적는다 — 없는 분모를 1 로 두고 비율을 만들지 않는다.
 */
export function observedShareText(
  value: number | null,
  denominator: number | null | undefined,
): string {
  if (value === null) {
    return '—'
  }
  if (denominator === null || denominator === undefined || denominator <= 0) {
    return value.toLocaleString('ko-KR')
  }
  return `${((value / denominator) * 100).toFixed(1)}%`
}

/**
 * 상세 화면의 최신 값 표기 · 티켓 S15P21E102-348.
 *
 * 분모가 있으면 함께 적는다. GitHub 관측은 주차마다 모집단이 달라(2026-08-31 = 4,045 ·
 * 09-07 = 133) 저장소 수만 보면 기간을 옮겼을 때 관심이 식은 것처럼 읽힌다.
 *
 * 분모를 모르면 값만 적는다 — 없는 모집단을 지어내지 않는다.
 */
export function observedValueText(
  value: number | null,
  denominator: number | null | undefined,
): string {
  if (value === null) {
    return '—'
  }
  const counted = value.toLocaleString('ko-KR')
  if (denominator === null || denominator === undefined || denominator <= 0) {
    return counted
  }
  return `${counted} / ${denominator.toLocaleString('ko-KR')} (${observedShareText(value, denominator)})`
}
