import type { DataStatus } from '@/shared/types/domain'

/**
 * 순위에 올릴 수 있는 상태 · 티켓 S15P21E102-327.
 *
 * BE 가 주는 값이 언제 믿을 만한지를 그대로 율긴 목록이다.
 *
 * `TrendService.source()` 는 실패·미준비 경로를 전부 `Source.empty()` 로 보내고
 * 그쪽은 points 가 비어 있지만, `Source.of()` 는 **points 를 가진 채** payload 의
 * status 를 그대로 옮긴다(`ComputeState.ofTrend`). 즉 payload 의 status 가
 * `FAILED` · `NOT_SUPPORTED` · `PREPARING` 이어도 수치는 남아 있을 수 있다.
 * 그런 값은 계산이 끝나지 않았거나 실패한 중간 산물이므로 순위를 매기면
 * 안 된다 — 값이 있다는 것과 그 값을 의지할 수 있다는 것은 다르다.
 *
 * `INSUFFICIENT_DATA` 는 다르다. 측정은 끝났고 표본이 얇을 뿐이라 수치 자체는
 * 유효하다. `PARTIAL` 도 같은 이유로 넣는다 — `ComputeState.isReady()` 가
 * `READY` 와 `PARTIAL` 을 같은 사용 가능 상태로 본다.
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
 * <h2>Why the rank is not gated on `READY` (ticket S15P21E102-327)</h2>
 *
 * It was, and that emptied the screen. No TREND point in production carries
 * `READY`: on 2026-09-18 all 221 heads were `INSUFFICIENT_DATA`, because each
 * technology matches only three public repositories. The counts underneath are
 * real measurements — 145,891 and 153,682 events for the 2026-09-07 week — and
 * dropping them told the reader we had measured nothing, which is a different
 * and worse claim than "this sample is small".
 *
 * So the rank follows the value, and the status travels with the row for the
 * card to show. `dataStatus` is untouched; an insufficient sample is still
 * labelled insufficient wherever it is drawn.
 *
 * The gate did not simply go away, it narrowed. `RANKABLE_STATUSES` still keeps
 * out the states whose numbers cannot be trusted — a `FAILED` source can carry
 * a leftover value, and ranking it would dress a failure as a measurement.
 *
 * A null value stays unranked. That is the real distinction — "we did not
 * measure this" against "we measured it on thin evidence" — and a zero-length
 * bar would read as an observed zero.
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
