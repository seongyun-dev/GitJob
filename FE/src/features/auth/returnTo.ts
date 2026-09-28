/**
 * 로그인 후 돌아갈 자리 · 티켓 S15P21E102-303.
 *
 * <h2>왜 FE 가 들고 있나 (BE OAuth `redirectTo` 와 섞지 않는다)</h2>
 *
 * BE 의 OAuth 허용 목록(`OAUTH_ALLOWED_REDIRECT_PATHS`)은 **정확히 일치하는 경로만**
 * 통과시킨다. 그래서 `/jobs/123` 같은 동적 경로를 OAuth 왕복에 실어 나를 수 없고,
 * 실으면 `AUTH-400-1` 로 끊긴다.
 *
 * 목적지는 FE 가 들고 있다가 콜백 화면에서 쓴다. OAuth 시작 URL 은 `/auth/github` 그대로
 * 둔다. 두 가지를 섞지 않는 것이 이 모듈의 존재 이유다. BE 계약은 변경하지 않는다.
 *
 * <h2>왜 sessionStorage 인가</h2>
 *
 * 한 번의 로그인 왕복 동안만 살아 있으면 되는 값이다. 탭을 닫으면 사라지는 편이 맞고,
 * 다른 탭의 로그인과 섞이지도 않는다. 인증·개인정보를 담지 않는다.
 *
 * <h2>왜 읽을 때도 검사하나</h2>
 *
 * 주소창의 쿼리와 sessionStorage 는 사용자가 고칠 수 있다. 저장할 때만 막으면 손으로 넣은
 * 바깥 주소가 로그인 직후 열린 리다이렉트가 된다. 쓸 때와 읽을 때 같은 판정을 건다.
 *
 * 아무것도 import 하지 않는다. `@/` 별칭은 Vite 가 푸는 것이라 별칭을 쓰면
 * `node --test` 에서 해석되지 않는다 — 화면 없이 검증할 수 있어야 하는 규칙이다.
 */

export const RETURN_TO_STORAGE_KEY = 'gitjob.auth.return-to.v1'

/**
 * 인증 왕복 자체의 경로. 목적지가 될 수 없다 — 로그인 직후 다시 로그인 화면이 열린다.
 * 왕복이 끝난 자리로 돌아가는 것이 이 값의 의미다.
 */
const AUTH_ROUND_TRIP = ['/login', '/auth/callback', '/admin/login', '/onboarding/github']

export interface ReturnToStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

/** 브라우저의 sessionStorage. 쓸 수 없으면 `null`. */
export function browserReturnToStorage(): ReturnToStorage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/**
 * 이 앱 안의 경로인지. 아니면 `null`.
 *
 * `/` 로 시작하는 절대경로만 받는다. `//host` 와 `/\host` 는 프로토콜 상대 URL 로 읽혀
 * 바깥으로 나가고, `javascript:` · `data:` · `https:` 는 애초에 `/` 로 시작하지 않는다.
 */
export function safeReturnTo(value: string | null | undefined): string | null {
  if (typeof value !== 'string' || !value.startsWith('/')) {
    return null
  }
  if (value.startsWith('//') || value.startsWith('/\\')) {
    return null
  }
  const path = value.split(/[?#]/)[0]
  if (AUTH_ROUND_TRIP.includes(path ?? '')) {
    return null
  }
  return value
}

/**
 * 지금 가려던 자리를 적어 둔다.
 *
 * `pathname + search + hash` 를 그대로 보존한다. 공고 상세의 탭(`?tab=requirements`)이나
 * 근거 화면의 앵커(`#skills`)까지 돌아가야 "원래 보려던 것"으로 돌아간 것이다.
 *
 * 안전하지 않은 값은 적지 않는다. 저장에 실패해도 삼킨다 — 부르는 쪽은 로그인 화면으로
 * 가는 길목이고, 자리를 기억하지 못했다고 로그인을 막을 이유는 없다.
 */
export function rememberReturnTo(
  storage: ReturnToStorage | null | undefined,
  location: { pathname: string; search: string; hash: string },
): void {
  if (storage === null || storage === undefined) {
    return
  }
  const target = safeReturnTo(`${location.pathname}${location.search}${location.hash}`)
  if (target === null) {
    return
  }
  try {
    storage.setItem(RETURN_TO_STORAGE_KEY, target)
  } catch {
    /* 자리를 기억하지 못해도 로그인은 계속한다. */
  }
}

/**
 * 적어 둔 자리를 꺼내고 **즉시 지운다**. 없거나 손상됐으면 `null`.
 *
 * 한 번 쓰면 사라져야 다음 로그인이 지난 목적지를 다시 만나지 않는다. 손상된 값도
 * 돌려주지 않고 지운다 — 남겨 두면 다음 로그인에서 같은 값을 또 만난다.
 */
export function consumeReturnTo(storage: ReturnToStorage | null | undefined): string | null {
  if (storage === null || storage === undefined) {
    return null
  }
  try {
    const stored = storage.getItem(RETURN_TO_STORAGE_KEY)
    storage.removeItem(RETURN_TO_STORAGE_KEY)
    return safeReturnTo(stored)
  } catch {
    return null
  }
}
