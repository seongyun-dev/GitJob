import type { TrendSourceId } from '@/features/trend/model/view'

/**
 * 선택한 월 범위의 하한을 적용한다 · **월별·공고 원천 전용**.
 *
 * 주간에는 쓰지 않는다(티켓 S15P21E102-329). 주간 head는 누적이고 BE가 기간 selector를
 * 받지 않으므로(`CTrend.Selector.weekly`는 periods를 비워 보내고, 넣으면 C가 422로
 * 거절한다) 월 하한으로 주차를 잘라낼 근거가 없다. "최근 3개월"을 눌렀다고 그보다 앞선
 * 주차의 관측이 없어지는 것은 아니다. 어느 원천에 적용할지는 `pointsForSource`가 정한다.
 *
 * 상한을 두지 않는 이유는 그대로다 — 진행 중인 기간은 완료 월 목록의 끝보다 늦을 수 있다.
 */
export function pointsSinceMonth<T extends { period: string }>(
  points: readonly T[],
  earliestMonth: string | undefined,
): T[] {
  if (earliestMonth === undefined) return [...points]
  return points.filter((point) => point.period.slice(0, 7) >= earliestMonth)
}

/**
 * 한 원천이 그릴 point. 주간만 월 범위에서 제외한다 · 티켓 S15P21E102-329.
 *
 * 이 분기를 `toTrendSeries` 안에 두지 않고 꺼내 둔 이유는 테스트를 붙이기 위해서다.
 * `api/adapter`는 `@/` 런타임 import가 있어 `node --test`가 불러올 수 없는데, 주간을
 * 자르지 않는다는 것은 이 티켓이 되돌린 실제 회귀라 주석이 아니라 값으로 고정해야 한다.
 */
export function pointsForSource<T extends { period: string }>(
  sourceId: TrendSourceId,
  points: readonly T[],
  earliestMonth: string | undefined,
): T[] {
  return sourceId === 'GITHUB_WEEKLY' ? [...points] : pointsSinceMonth(points, earliestMonth)
}
