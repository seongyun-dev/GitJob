import type { ComputeStateFields } from '@/features/matching/api/types'

/** 계산 중일 때의 기본 폴링 간격. 서버가 `retryAfterSec`을 주면 그쪽을 따른다. */
const DEFAULT_POLL_MS = 5_000

/** 준비되지 않은 입력을 기다릴 때. 짧게 물으면 의미 없이 서버만 때린다. */
const SLOW_POLL_MS = 30_000

/**
 * 시장 분포가 값을 가진 뒤에도 다시 묻는 간격 · 티켓 S15P21E102-343.
 *
 * 새 채용공고 입력은 하루 두 번 들어온다. 그것을 잡으려고 1분마다 물으면 하루 1,440번을
 * 던져 의미 있는 변화 두 건을 건지는 셈이다. 10분이면 최대 지연이 수집 주기의 1%도 되지
 * 않으면서, 100명이 동시에 열어 둬도 0.17 rps다.
 */
const MARKET_READY_POLL_MS = 600_000

/**
 * 다음 조회까지의 간격.
 *
 * React Query는 refetch 실패 뒤에도 직전 성공 data를 보존한다. 따라서 data만 보고
 * `PREPARING`을 판단하면 세션 만료 같은 영구 4xx 뒤에도 계속 호출한다. 최신 요청이
 * 실패한 경우에는 전역 오류 처리가 세션·화면 전환을 맡도록 폴링을 즉시 멈춘다.
 */
export function pollInterval(
  state: ComputeStateFields | undefined,
  hasError: boolean,
): number | false {
  if (hasError || state === undefined || state.dataStatus !== 'PREPARING') {
    return false
  }
  if (state.retryAfterSec !== null) {
    return Math.max(state.retryAfterSec, 1) * 1000
  }
  return state.statusReason === 'COHORT_NOT_PREPARED' ? SLOW_POLL_MS : DEFAULT_POLL_MS
}

/**
 * 현재 시장 분포의 다음 조회까지의 간격 · 티켓 S15P21E102-343.
 *
 * 직무별 조회와 달리 값이 생긴 뒤에도 멈추지 않는다. 이 지표는 사용자가 조건을 바꿔서
 * 달라지는 값이 아니라 **새 채용공고가 들어오면 스스로 달라지는 값**이고, BE 는 요청마다
 * 최신 canonical cutoff 를 다시 고른다. 그래서 다시 묻는 것만으로 최신화된다 — 멈추면
 * 화면을 열어 둔 사람만 옛 숫자를 계속 본다.
 *
 * 계산 중일 때의 간격은 {@link pollInterval} 그대로다. 두 벌로 적으면 서버가 준
 * `retryAfterSec` 을 한쪽만 따르게 된다.
 *
 * 최신 요청이 실패한 경우 멈추는 것도 같다. 세션 만료 같은 영구 4xx 에서 10분마다
 * 계속 때릴 이유가 없고, 전역 오류 처리가 화면 전환을 맡는다.
 */
export function marketPollInterval(
  state: ComputeStateFields | undefined,
  hasError: boolean,
): number | false {
  if (hasError || state === undefined) {
    return false
  }
  const preparing = pollInterval(state, hasError)
  return preparing === false ? MARKET_READY_POLL_MS : preparing
}
