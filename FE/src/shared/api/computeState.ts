import type { DataStatus } from '@/shared/types/domain'

/**
 * 계산 계열 응답의 상태 (S15P21E102-279).
 *
 * BE는 "계산 중"을 오류가 아니라 200 + `dataStatus=PREPARING`으로 준다. 잠시 뒤 값이
 * 생기고 사용자가 할 일은 기다리는 것뿐이기 때문이다. 그래서 화면은 두 축을 본다 --
 * HTTP 실패(`ApiError`)와 여기 담긴 계산 상태.
 *
 * 컴포넌트 파일이 아니라 여기에 두는 이유는 판정이 한 군데여야 하기 때문이다. 화면마다
 * `dataStatus === 'READY'`를 적으면 `PARTIAL`을 빠뜨린 화면이 생기고, 그 화면은 일부
 * 저장소만 분석된 사용자에게 아무것도 보여주지 않는다.
 */
export interface ComputeState {
  dataStatus: DataStatus
  /** `COMPUTING`·`COHORT_NOT_PREPARED`·`INSUFFICIENT_EVIDENCE` 등. 문구와 폴링 간격을 정한다. */
  statusReason: string
}

/**
 * 값을 그려도 되는 상태인지.
 *
 * `PARTIAL`을 포함한다. 일부 저장소를 못 읽었어도 나머지로 나온 판정은 유효하고,
 * 그것을 숨기면 사용자는 있는 근거조차 보지 못한다. 부분이라는 사실은 배너로 알린다.
 */
export function hasComputedValue(state: ComputeState | undefined): boolean {
  return state !== undefined && (state.dataStatus === 'READY' || state.dataStatus === 'PARTIAL')
}
