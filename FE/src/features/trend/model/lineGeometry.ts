/**
 * 선 그래프 좌표 계산 · 티켓 S15P21E102-329.
 *
 * <h2>관측된 0 과 미집계는 다르다</h2>
 *
 * 이 좌표계가 지켜야 하는 단 하나의 구분이다. 계약상 실제 0 은 유효한 분모가 있을 때만
 * 오므로("실제 0은 유효한 분모/원천 행이 있을 때만 반환한다") 0 은 지어낸 값이 아니라
 * 관측 결과다. `y` 가 `null` 인 점은 화면이 점선 gap 으로 그리고 "집계되지 않은 기간"
 * 으로 세므로, 관측된 0 에 `null` 을 주면 있었던 관측이 결손으로 바뀐다.
 *
 * 그래서 최댓값이 0 이어도 축 배율만 1 로 두고 좌표는 그대로 만든다. 0 은 기준선에
 * 놓이고, 높이로 차이를 보여줄 수 없다는 사실은 화면이 따로 적는다.
 *
 * <h2>컴포넌트에서 떼어낸 이유</h2>
 *
 * 테스트를 붙이기 위해서다. `TrendLineChart.tsx` 는 `StateCard` 를 런타임 import 하고
 * `node --test` 는 `@/` alias 를 해석하지 못한다. 좌표 규칙은 회귀가 실제로 발생한
 * 곳이라 고정할 값이 있다.
 *
 * <h2>좌표계</h2>
 *
 * x 는 **기간 인덱스**다. 주차 간 실제 시간 간격이 다르더라도 관측 순서가 축이므로 점
 * 간격은 균등하다. y 는 SVG 관례대로 작을수록 위다.
 */

export const VIEW_WIDTH = 100
export const VIEW_HEIGHT = 40
const PAD_X = 3
const PAD_Y = 4

export interface SeriesPoint {
  period: string
  value: number | null
}

export interface PlottedPoint {
  period: string
  value: number | null
  x: number
  /** 결손 기간만 `null`. 관측된 0 은 기준선 좌표를 갖는다. */
  y: number | null
  isLatest: boolean
}

export function plotSeries(points: readonly SeriesPoint[]): {
  plotted: PlottedPoint[]
  max: number
} {
  const values = points
    .map((point) => point.value)
    .filter((value): value is number => value !== null)
  const max = values.length === 0 ? 0 : Math.max(...values)
  /*
   * 배율은 0 으로 나누는 것만 막는다. 관측값이 모두 0 인 시계열은 전부 기준선에
   * 놓이고, 그것이 사실이다 — 결손이 아니다.
   */
  const scale = max > 0 ? max : 1
  const usableX = VIEW_WIDTH - PAD_X * 2
  const usableY = VIEW_HEIGHT - PAD_Y * 2
  const lastIndex = points.length - 1

  const plotted = points.map((point, index) => ({
    period: point.period,
    value: point.value,
    x:
      points.length === 1
        ? PAD_X + usableX / 2
        : PAD_X + (index * usableX) / (points.length - 1),
    y: point.value === null ? null : VIEW_HEIGHT - PAD_Y - (point.value / scale) * usableY,
    isLatest: index === lastIndex,
  }))
  return { plotted, max }
}

/**
 * 값이 있는 점들을 **연속 구간**으로 자른다.
 *
 * 결손 기간을 만나면 구간을 끊는다. 구간마다 polyline 하나를 그리므로 빠진 기간을
 * 가로지르는 선분이 생기지 않는다. 점 하나만 있는 구간도 남겨 두는데, 그 점의 marker
 * 는 따로 그리므로 선이 없어도 값은 보인다.
 */
export function segments(plotted: readonly PlottedPoint[]): PlottedPoint[][] {
  const runs: PlottedPoint[][] = []
  let current: PlottedPoint[] = []
  for (const point of plotted) {
    if (point.y === null) {
      if (current.length > 0) runs.push(current)
      current = []
      continue
    }
    current.push(point)
  }
  if (current.length > 0) runs.push(current)
  return runs
}
