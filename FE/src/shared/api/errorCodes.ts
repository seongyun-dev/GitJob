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
  /** 세션 없음·만료 → 온보딩으로 이동 */
  | 'REDIRECT_TO_ONBOARDING'
  /** GitHub 권한 거부·토큰 폐기 → 재연결 안내 */
  | 'RECONNECT_GITHUB'
  /** 본인 리소스가 아님 → 접근 불가 화면 */
  | 'SHOW_FORBIDDEN'
  /** 대상 없음 → 404 화면 */
  | 'SHOW_NOT_FOUND'
  /** 성공한 Snapshot 없음 → 빈 상태 + "분석 시작" CTA */
  | 'SHOW_EMPTY_WITH_CTA'
  /** 근거 0건 → 행 자체를 렌더하지 않는다. 오류가 아니므로 토스트도 띄우지 않는다 */
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

  // FE 합성
  [CLIENT_NETWORK]: 'SHOW_RETRY',
  [CLIENT_ENVELOPE]: 'SHOW_GENERIC_ERROR',

  // 증거 조회 — BE 미구현. 137·138 착수 전 BE 구현을 확인한다 (설계 6-3장)
  'EVD-404-1': 'SHOW_EMPTY_WITH_CTA',
  'EVD-404-2': 'SHOW_NOT_FOUND',
  'EVD-404-3': 'SILENT_EMPTY',
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
