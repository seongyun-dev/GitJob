import type { DataStatus } from '@/shared/types/domain'

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
 * A source card ranks only values that were actually observed by that source.
 *
 * `READY` or `PARTIAL` with zero is a real observation and remains rankable.
 * `PARTIAL` means the public aggregate has a quality limitation, not that the
 * numeric observation disappeared. A null value must not become a ranked zero.
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
        (row.dataStatus === 'READY' || row.dataStatus === 'PARTIAL') && row.value !== null,
    )
    .sort((left, right) => right.value - left.value || left.index - right.index)
    .map(({ index: _index, ...row }, index) => ({ ...row, rank: index + 1 }))
  const unobserved = rows.filter(
    (row) =>
      (row.dataStatus !== 'READY' && row.dataStatus !== 'PARTIAL') || row.value === null,
  )

  return {
    observed,
    unobserved,
    maximumObservedValue: observed[0]?.value ?? null,
  }
}
