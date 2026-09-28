/**
 * 마이페이지 조회 응답 타입 · 티켓 S15P21E102-281.
 *
 * BE 미구현 상태에서 먼저 고정하는 계약이다. 근거는 B조 API 명세서 v0.1의
 * B-FN-009 분석 이력 목록 조회(`GET /me/analyses`, 화면 14).
 *
 * ## 계정·연결 정보는 여기 없다
 *
 * 화면 14의 `계정 · 연결` 영역은 **이미 붙일 곳이 있다.** 티켓 246이
 * `features/auth/api/me.ts`에 `GET /auth/me`를 만들어 두었고 그것이 BE에 실제로
 * 구현된 유일한 사용자 조회다. 명세표 B-FN-001은 같은 것을 `GET /me`로 적지만,
 * 계약 문서가 정한 우선순위는 "BE에 구현된 것은 BE 코드를 따르고, 아직 없는 것만
 * 명세를 유지한다"이므로 `/auth/me`를 쓴다. 이 경로 차이는 계약 문서 미결에 올렸다.
 *
 * ## 분석 상태가 `JobStatus`와 다른 이유
 *
 * `shared/types/domain.ts`의 `JOB_STATUSES`는 와이어프레임 1-2가 확정한 **6종**이고
 * `PARTIAL_SUCCEEDED`가 없다. 명세 v0.1의 분석 상태는 그것을 포함한 **7종**이다.
 * 이력 표는 부분 성공을 따로 그려야 하므로(`src/mocks/README.md`가 적은, `JobStatus`
 * 컴포넌트를 쓰지 않는 이유) 이 파일이 7종을 따로 둔다.
 *
 * **공용 `JOB_STATUSES`를 늘리지 않았다.** 그 상수는 분석 진행 폴링의 종료 판정
 * (`isTerminalJobStatus`)에 쓰이고, 값을 하나 더하면 그 판정이 조용히 달라진다.
 * 어느 쪽이 맞는지는 BE 구현이 정하며 계약 문서 미결에 올렸다.
 */
export const ANALYSIS_HISTORY_STATUSES = [
  'QUEUED',
  'RUNNING',
  'RATE_LIMITED',
  'SUCCEEDED',
  'PARTIAL_SUCCEEDED',
  'FAILED',
  'CANCELED',
] as const
export type AnalysisHistoryStatus = (typeof ANALYSIS_HISTORY_STATUSES)[number]

/** 분석 이력 한 줄 · 화면 14. */
export interface AnalysisHistoryItem {
  analysisId: string
  /**
   * 분석 시각. UTC ISO-8601이다(명세 공통 규약).
   *
   * fixture가 `오늘 10:42` 같은 문자열을 갖고 있던 것과 다르다. 상대 시각은 보는
   * 시점에 따라 달라지므로 서버가 만들 수 없다 — 화면이 환산한다.
   */
  analyzedAt: string
  /** 대상 저장소 이름. 화면이 쉼표로 잇는다. */
  repositories: string[]
  /** 결과 요약 문구. 무엇이 몇 개 확인됐는지는 서버가 센다. */
  resultText: string
  status: AnalysisHistoryStatus
}

export interface AnalysisHistory {
  items: AnalysisHistoryItem[]
  /** 0-base. 명세 v0.1 */
  page: number
  size: number
  totalCount: number
}

/** `GET /me/analyses` 질의 인자. */
export interface AnalysisHistoryParams {
  page?: number
  size?: number
}
