/**
 * 고정 enum. 명세와 와이어프레임이 값을 확정했으므로 문자열을 임의로 늘리지 않는다.
 * 화면 표기를 바꿔야 하면 이 파일과 대응 컴포넌트를 함께 고친다.
 */

/** 판정 근거 수준. 숙련도가 아니라 근거의 누적 상태다. */
export const EVIDENCE_LEVELS = ['L0', 'L1', 'L2', 'L3'] as const
export type EvidenceLevel = (typeof EVIDENCE_LEVELS)[number]

/**
 * 기여 라벨 5종. 비율 값을 노출하지 않는다(와이어프레임 1-1 금지 규칙).
 * 숫자를 받는 자리를 만들지 않는 것이 이 타입의 목적이다.
 *
 * `OTHER_AUTHOR`와 `UNVERIFIED`는 붙여 쓰지 않는다. 앞은 커밋 작성자를 물어
 * **남이 썼음을 확인한** 것이고, 뒤는 **물어보지 못한** 것이다. 합쳐서 보여주면
 * 화면이 "확인 못 했다"를 "본인이 안 썼다"로 말하게 된다.
 */
export const CONTRIBUTION_LABELS = [
  'SOLE_AUTHOR',
  'CO_AUTHORED',
  'PARTIAL_EDIT',
  'OTHER_AUTHOR',
  'UNVERIFIED',
] as const
export type ContributionLabel = (typeof CONTRIBUTION_LABELS)[number]

/** 분석 잡 상태 6종 (와이어프레임 1-2 확정). */
export const JOB_STATUSES = [
  'QUEUED',
  'RUNNING',
  'RATE_LIMITED',
  'SUCCEEDED',
  'FAILED',
  'CANCELED',
] as const
export type JobStatus = (typeof JOB_STATUSES)[number]

const TERMINAL_JOB_STATUSES = new Set<JobStatus>(['SUCCEEDED', 'FAILED', 'CANCELED'])

/**
 * 폴링을 멈춰야 하는 상태인지 판정한다(설계 §4-2).
 * RATE_LIMITED는 종료가 아니므로 계속 폴링한다.
 */
export function isTerminalJobStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.has(status)
}

/**
 * 데이터 준비 상태. 준비 중이나 표본 부족은 오류가 아니라 200 + 이 값으로 온다(명세 §2-3).
 * 더미·추정값을 채워 표시하지 않는다.
 */
export const DATA_STATUSES = [
  'READY',
  'PREPARING',
  'PARTIAL',
  'NO_DATA',
  'INSUFFICIENT_DATA',
  'NOT_SUPPORTED',
  'FAILED',
] as const
export type DataStatus = (typeof DATA_STATUSES)[number]
