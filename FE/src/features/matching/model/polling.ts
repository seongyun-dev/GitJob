import type { ComputeStateFields } from '@/features/matching/api/types'

/** 계산 중일 때의 기본 폴링 간격. 서버가 `retryAfterSec`을 주면 그쪽을 따른다. */
const DEFAULT_POLL_MS = 5_000

/** 준비되지 않은 입력을 기다릴 때. 짧게 물으면 의미 없이 서버만 때린다. */
const SLOW_POLL_MS = 30_000

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
