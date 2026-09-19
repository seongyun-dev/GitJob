/**
 * 카드 안 기간 이동이 어디로 갈 수 있는지 · 티켓 S15P21E102-329.
 *
 * <h2>왜 화면이 기간을 만들지 않는가</h2>
 *
 * 달력으로 "최근 6개월"이나 "지난 주차"를 계산하면 아직 집계되지 않은 기간을 묻게
 * 되고, 그러면 값이 있는데도 빈 카드가 뜬다. 어느 기간이 게시돼 있는지는 저장한 쪽만
 * 알고, 순위 API 가 `availablePeriods` 로 그것을 답한다.
 *
 * <h2>왜 순수 함수인가</h2>
 *
 * `node --test` 는 `@/` alias 를 해석하지 못해 런타임 import 가 있는 모듈을 불러올 수
 * 없다. 기간 이동은 이 화면이 한 번 잃었다가 되살린 기능이라(-345 에서 제거됐다)
 * 주석이 아니라 값으로 고정해 둘 필요가 있다.
 */

/** 카드가 받을 이동 정보. 갈 곳이 하나뿐이면 `null` — 버튼을 만들지 않는다. */
export interface PeriodNavigationState {
  periods: readonly string[]
  selected: string
}

/**
 * 서버가 답한 기간 목록과 실제로 읽은 기간에서 이동 상태를 만든다.
 *
 * 목록에 없는 기간이 선택돼 있으면 최신으로 되돌린다. 그대로 두면 카드가 목록 밖을
 * 가리켜 이전·다음이 모두 disabled 가 되고, 사용자는 되돌아올 수 없는 곳에 갇힌다.
 */
export function periodNavigation(
  availablePeriods: readonly string[] | null | undefined,
  period: string | null | undefined,
): PeriodNavigationState | null {
  const periods = availablePeriods ?? []
  if (periods.length <= 1) {
    return null
  }
  const selected =
    period !== null && period !== undefined && periods.includes(period)
      ? period
      : (periods[periods.length - 1] as string)
  return { periods, selected }
}
