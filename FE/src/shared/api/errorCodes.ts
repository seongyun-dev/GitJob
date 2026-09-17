/**
 * 오류 코드 → 화면 처리 매핑.
 *
 * 코드는 BE `global/exceptions/ErrorCode`가 원본이다. Notion 명세와 다른 부분은
 * BE 실구현을 따르기로 했다(2026-09-09). 대응표와 근거는
 * docs/fe/shared-api-contract.md 1-3, 명세와의 차이는 같은 문서 2장.
 *
 * 컴포넌트에 `if (code === '...')`를 흩어놓지 않는 것이 이 파일의 목적이다.
 */

export type ErrorAction =
  /** 세션 없음·만료 → 사용자 캐시를 비우고 로그인으로 이동 */
  | 'REDIRECT_TO_ONBOARDING'
  /** GitHub 권한 거부·토큰 폐기 → 재연결 안내 */
  | 'RECONNECT_GITHUB'
  /** 본인 리소스가 아님 → 접근 불가 화면 */
  | 'SHOW_FORBIDDEN'
  /** 대상 없음 → 404 화면 */
  | 'SHOW_NOT_FOUND'
  /** 성공한 Snapshot 없음 → 빈 상태 + "분석 시작" CTA */
  | 'SHOW_EMPTY_WITH_CTA'
  /**
   * 근거 0건 → 행 자체를 렌더하지 않는다. 오류가 아니므로 토스트도 띄우지 않는다.
   *
   * 티켓 208 기준으로 이 액션에 매핑된 코드가 없다. 예전 명세의 `EVD-404-3`이
   * 유일한 사용처였는데 v0.1의 B-FN-011 실패 표에서 빠졌고, 그 자리를 `EVD-404-1`이
   * 대신하면서 처리도 `SHOW_EMPTY_WITH_CTA`로 바뀌었다. 액션 자체를 지우려면
   * `QueryStatePanel`의 표기 표까지 함께 고쳐야 해서(137·138 소유) 여기서는 남겨
   * 둔다. 계약 문서 미결에 올렸다.
   */
  | 'SILENT_EMPTY'
  /** 호출 한도 초과 → 재시도 시각 안내, 자동 재시도 안 함 */
  | 'SHOW_RATE_LIMIT'
  /** 의존 서비스 장애 → 재시도 버튼 */
  | 'SHOW_RETRY'
  /** 입력 오류 → 폼 인라인 메시지 */
  | 'SHOW_INLINE_ERROR'
  /** 보관·비활성 저장소 → 분석 불가 사유 표시 */
  | 'SHOW_UNANALYZABLE'
  /** 매핑되지 않은 코드 → 일반 오류 안내 */
  | 'SHOW_GENERIC_ERROR'

/**
 * 서버 응답이 봉투가 아닐 때 FE가 만드는 코드.
 * BE 코드와 섞이지 않게 `CLIENT-` 접두를 쓴다.
 */
export const CLIENT_NETWORK = 'CLIENT-NETWORK'
export const CLIENT_ENVELOPE = 'CLIENT-ENVELOPE'

/** 비2xx인데 실패 봉투가 아닌 응답(프록시 오류, Spring 기본 오류 페이지 등). */
export function httpFallbackCode(status: number): string {
  return `HTTP-${status}`
}

const ERROR_ACTIONS: Readonly<Record<string, ErrorAction>> = {
  // 공통 — BE는 COMMON-*이 아니라 G-* 를 쓴다
  'G-400-1': 'SHOW_INLINE_ERROR',
  'G-400-2': 'SHOW_INLINE_ERROR',
  'G-500': 'SHOW_GENERIC_ERROR',

  // 세션 — 다시 로그인시키는 것 말고 할 수 있는 게 없다
  'AUTH-401-1': 'REDIRECT_TO_ONBOARDING',
  'AUTH-401-2': 'REDIRECT_TO_ONBOARDING',
  'AUTH-401-3': 'REDIRECT_TO_ONBOARDING',
  'AUTH-400-2': 'REDIRECT_TO_ONBOARDING',
  'AUTH-400-1': 'SHOW_GENERIC_ERROR',

  // 인가 — 로그인은 됐지만 관리자가 아니다. 권한은 DB에서 부여하므로 재로그인·재시도로는
  // 풀리지 않는다. 세션 만료(AUTH-401-*)와 같은 안내를 하면 사용자가 없는 관리자 로그인을 찾는다.
  'AUTH-403-2': 'SHOW_FORBIDDEN',

  // GitHub 연결 — 권한을 다시 받아야 한다
  'AUTH-403-3': 'RECONNECT_GITHUB',
  'AUTH-403-4': 'RECONNECT_GITHUB',
  'AUTH-401-4': 'RECONNECT_GITHUB',
  'AUTH-503-1': 'SHOW_RETRY',

  // 저장소
  'REPO-403-1': 'SHOW_FORBIDDEN',
  // 선택 폼에서 고른 직후 나는 오류라 404 화면이 아니라 항목 옆에 표시한다
  'REPO-404-1': 'SHOW_INLINE_ERROR',
  'REPO-404-2': 'SHOW_INLINE_ERROR',
  'REPO-409-1': 'SHOW_UNANALYZABLE',
  'REPO-429-1': 'SHOW_RATE_LIMIT',
  'REPO-503-1': 'SHOW_RETRY',

  // 기술 후보 검토(관리자) — 넷 다 해당 행 옆에 붙인다. 화면 전체를 오류로
  // 덮으면 다른 후보를 계속 처리할 수 없고, 실제로 막힌 것은 그 한 행이다.
  'ADMIN-400-1': 'SHOW_INLINE_ERROR',
  'ADMIN-404-1': 'SHOW_INLINE_ERROR',
  'ADMIN-409-1': 'SHOW_INLINE_ERROR',
  'ADMIN-409-2': 'SHOW_INLINE_ERROR',

  // FE 합성
  [CLIENT_NETWORK]: 'SHOW_RETRY',
  [CLIENT_ENVELOPE]: 'SHOW_GENERIC_ERROR',

  // 기술 프로필 조회 — BE 미구현. 명세 B-FN-010 `실패 응답 정의` (티켓 208)
  // 종료된 분석이 없으면 오류 화면이 아니라 "분석 시작" 유도가 맞다. 명세도
  // "분석 요청 유도 화면으로 이동"이라고 적었다.
  'PRF-404-1': 'SHOW_EMPTY_WITH_CTA',
  // 지정한 분석이 아직 진행 중. 잠시 뒤 다시 부르면 낫는 상태라 재시도로 둔다.
  // 진행 상태 화면(S3)으로 보내는 편이 더 낫지만 그건 136이 정할 몫이라
  // 대응 화면이 없는 액션을 지금 만들지 않는다(계약 1-3의 SHOW_SELECTION_LOCKED 선례).
  'PRF-409-1': 'SHOW_RETRY',
  // 남의 analysisId를 지정한 경우. 명세 B-FN-010 403.
  'ANL-403-1': 'SHOW_FORBIDDEN',

  // C 계산 결과 조회 (S15P21E102-279). 계산 대기·미준비·표본 부족은 여기 없다 --
  // 그것들은 오류가 아니라 200 응답의 dataStatus 로 온다.
  //
  // 목표 직무를 고르지 않은 것은 실패가 아니라 다음 할 일이 정해진 상태다.
  'MATCH-404-1': 'SHOW_EMPTY_WITH_CTA',
  'MATCH-404-2': 'SHOW_NOT_FOUND',
  'MATCH-400-1': 'SHOW_INLINE_ERROR',
  // 재시도하면 풀릴 수 있다. 일반 오류로 두면 화면이 재시도를 권하지 못한다.
  'MATCH-503-1': 'SHOW_RETRY',
  'TREND-400-1': 'SHOW_INLINE_ERROR',

  // 증거 조회 — BE 미구현. 명세 B-FN-011 `실패 응답 정의` (티켓 208)
  // 404지만 "그 기술의 근거가 0건"이다. 사용자가 특정 기술 상세로 들어온 상황이라
  // 빈 화면을 조용히 두지 않고 재분석 CTA를 준다.
  'EVD-404-1': 'SHOW_EMPTY_WITH_CTA',
  'EVD-404-2': 'SHOW_NOT_FOUND',
}

export function resolveErrorAction(code: string): ErrorAction {
  return ERROR_ACTIONS[code] ?? 'SHOW_GENERIC_ERROR'
}

/**
 * 오류가 아니라 정상적인 빈 결과인지 판정한다.
 * 이 경우 토스트를 띄우지 않고 해당 영역을 렌더하지 않는다(금지 규칙 4).
 */
export function isSilentEmpty(code: string): boolean {
  return resolveErrorAction(code) === 'SILENT_EMPTY'
}
