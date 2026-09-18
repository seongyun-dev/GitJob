/**
 * 상세 화면의 주간 head는 BE 계약상 기간을 selector에 넣지 않는다. 따라서 월별 selector와
 * 같은 범위 버튼을 눌렀을 때 오래된 주차를 화면에서 잘라야 한다. 현재 진행 중인 주차는
 * 완료 월 목록의 끝보다 늦을 수 있으므로 상한은 두지 않고 시작 월만 적용한다.
 */
export function pointsSinceMonth<T extends { period: string }>(
  points: readonly T[],
  earliestMonth: string | undefined,
): T[] {
  if (earliestMonth === undefined) return [...points]
  return points.filter((point) => point.period.slice(0, 7) >= earliestMonth)
}
