import { API_BASE_URL } from '@/shared/api/client'

/**
 * OAuth 진입 URL · 티켓 S15P21E102-156.
 *
 * 진입 엔드포인트는 302로 GitHub에 넘긴다. 그래서 `fetch`로 부르면 안 된다 —
 * 리다이렉트를 따라간 XHR은 CORS로 막히고, 따라가더라도 GitHub 로그인 화면의
 * HTML을 받게 된다. 브라우저 최상위 이동(`<a href>`)으로만 호출한다.
 *
 * 이 파일이 URL만 만들고 `client.ts`의 `get`을 쓰지 않는 이유가 그것이다.
 *
 * GitHub authorize URL을 FE에서 조립하지 않는다. `client_id`·`scope`·`state`는
 * BE가 정하며, state는 CSRF 검증 대상이라 FE가 만들면 검증이 무의미해진다.
 */

/**
 * `redirectTo`가 없을 때의 목적지.
 * BE `OAUTH_ALLOWED_REDIRECT_PATHS`의 첫 항목이 기본값이라는 규칙과 맞춰 둔다.
 */
export const DEFAULT_REDIRECT = '/onboarding/repositories'

/**
 * 로그인과 재인증이 같은 경로다.
 *
 * 별도의 재연결 엔드포인트를 두지 않는다. `completeLogin`의 upsert가 기존 사용자
 * 갈래에서도 `access_token`을 저장하므로, 로그인 자체가 이미 토큰 갱신이다. 토큰이
 * 폐기·만료되면 다시 로그인하면 낫는다.
 *
 * @param redirectTo 완료 후 돌아갈 FE 경로.
 *   BE가 `OAUTH_ALLOWED_REDIRECT_PATHS`와 정확히 일치할 때만 통과시키므로,
 *   허용 목록에 없는 값을 넘기면 BE가 기본 목적지로 대체한다.
 */
export function githubLoginUrl(redirectTo?: string): string {
  return withRedirect(`${API_BASE_URL}/auth/github`, redirectTo)
}

function withRedirect(base: string, redirectTo?: string): string {
  if (redirectTo === undefined) {
    return base
  }
  return `${base}?redirectTo=${encodeURIComponent(redirectTo)}`
}

/**
 * 같은 오리진 절대경로만 통과시킨다.
 *
 * BE가 허용 목록으로 이미 검증하지만 주소창의 쿼리는 사용자가 고칠 수 있다.
 * `//host`는 프로토콜 상대 URL이라 라우터가 외부로 내보낸다.
 *
 * 콜백 화면과 재연결 안내 화면이 같은 판정을 쓰므로 여기에 둔다.
 */
export function safeRedirect(value: string | null): string {
  if (value === null || !value.startsWith('/') || value.startsWith('//')) {
    return DEFAULT_REDIRECT
  }
  return value
}
