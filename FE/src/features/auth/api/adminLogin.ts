import { post } from '@/shared/api/client'

/**
 * 관리자 전용 ID/PW 로그인.
 *
 * BE `POST /api/v1/auth/admin-login`이 원본이다. 성공하면 응답에 SESSION 쿠키가 실려
 * 오고(HttpOnly), 이후 요청은 GitHub 로그인과 구분 없이 그 세션으로 동작한다. 실패는
 * 원인을 구분하지 않고 401(`ApiError`)로 던져지므로, 호출부는 성공/실패만 구분하면 된다.
 *
 * 자격 증명은 요청 본문으로만 보내고 어디에도 저장하지 않는다.
 */
export function adminLogin(id: string, password: string): Promise<void> {
  return post<void>('/auth/admin-login', { id, password })
}
