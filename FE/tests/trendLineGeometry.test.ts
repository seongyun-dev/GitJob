import assert from 'node:assert/strict'
import test from 'node:test'

import { plotSeries } from '../src/features/trend/model/lineGeometry.ts'

/**
 * 선 그래프 좌표 · 티켓 S15P21E102-329.
 *
 * 이 화면에서 가장 중요한 구분은 **관측된 0**과 **미집계**다. 계약상 실제 0은 유효한
 * 분모가 있을 때만 오고("실제 0은 유효한 분모/원천 행이 있을 때만 반환한다"), 그때
 * 0은 지어낸 값이 아니라 관측 결과다. 그것을 결손으로 그리면 있었던 관측이 사라진다.
 *
 * 좌표 계산을 컴포넌트에서 떼어낸 이유는 여기에 테스트를 붙이기 위해서다.
 * `TrendLineChart.tsx`는 `@/` 런타임 import 가 있어 `node --test` 가 불러올 수 없다.
 */

const point = (period: string, value: number | null) => ({ period, value })

test('관측값이 모두 0 인 시계열은 결손이 아니다', () => {
  const { plotted, max } = plotSeries([point('2026-06', 0), point('2026-07', 0), point('2026-08', 0)])

  assert.equal(max, 0)
  // 세 점 모두 좌표를 가진다. y 가 null 이면 화면이 점선 gap 으로 그리고
  // "집계되지 않은 기간 3개" 라고 잘못 적는다.
  assert.equal(
    plotted.filter((item) => item.y === null).length,
    0,
  )
  assert.deepEqual(
    plotted.map((item) => item.value),
    [0, 0, 0],
  )
})

test('관측된 0 은 기준선에 놓인다', () => {
  const { plotted } = plotSeries([point('2026-07', 0), point('2026-08', 10)])
  const baseline = plotted[1]?.y
  const zero = plotted[0]?.y

  assert.ok(zero !== null && zero !== undefined)
  assert.ok(baseline !== null && baseline !== undefined)
  // 0 은 가장 낮고, 10 은 그보다 위다. SVG 는 y 가 작을수록 위다.
  assert.ok((zero as number) > (baseline as number))
})

test('값이 null 인 기간만 좌표가 없다', () => {
  const { plotted } = plotSeries([point('2026-06', 0), point('2026-07', null), point('2026-08', 5)])

  assert.equal(plotted[0]?.y === null, false)
  assert.equal(plotted[1]?.y === null, true)
  assert.equal(plotted[2]?.y === null, false)
})

test('전부 null 인 시계열은 좌표가 하나도 없다', () => {
  const { plotted, max } = plotSeries([point('2026-07', null), point('2026-08', null)])

  assert.equal(max, 0)
  assert.equal(plotted.every((item) => item.y === null), true)
})

test('선은 실제 결손에서만 끊긴다', () => {
  const { plotted } = plotSeries([
    point('2026-05', 1),
    point('2026-06', 0),
    point('2026-07', null),
    point('2026-08', 3),
  ])
  const runs = plotted.reduce<number>((count, item, index) => {
    const previous = plotted[index - 1]
    if (item.y === null) return count
    return previous === undefined || previous.y === null ? count + 1 : count
  }, 0)

  // 0 은 구간을 끊지 않으므로 [1, 0] 과 [3] 두 구간이다.
  assert.equal(runs, 2)
})

test('최신 기간만 isLatest 다', () => {
  const { plotted } = plotSeries([point('2026-07', 1), point('2026-08', 2)])

  assert.deepEqual(
    plotted.map((item) => item.isLatest),
    [false, true],
  )
})

test('점이 하나면 가로 중앙에 놓는다', () => {
  const { plotted } = plotSeries([point('2026-08', 4)])

  assert.equal(plotted.length, 1)
  assert.ok((plotted[0]?.x as number) > 0)
})
