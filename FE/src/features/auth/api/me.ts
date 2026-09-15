import { ApiError, get, post } from '@/shared/api/client'

/**
 * 로그인 사용자 조회·로그아웃 · 티켓 S15P21E102-246.
 *
 * 세션이 HttpOnly 쿠키라 FE가 직접 읽을 수 없다. 그래서 로그인 여부의 단일 출처는
 * `GET /auth/me`의 성공/401이다 — 200이면 로그인, 401이면 로그아웃으로 읽는다.
 * BE는 세션이 유효하지만 사용자 행이 없는 경우(만료 전 삭제)도 401로 접는다.
 */

export interface Me {
  /** 프로필 이름. 없으면 BE가 GitHub 핸들로 대체하므로 빈 값은 아니다. */
  displayName: string
  /** GitHub 아바타. 없으면 `null` — 화면은 이름 첫 글자로 대체한다. */
  avatarUrl: string | null
  /** 저장된 access token 유무. 실제 데이터라 "GitHub 연결됨" 표기의 근거가 된다. */
  githubConnected: boolean
  /**
   * 권한. 헤더 프로필이 ADMIN에게만 관리자 페이지 진입 링크를 보이는 데 쓴다.
   * 라우트 보호가 아니라 진입점 노출용 — 실제 접근 제한은 BE `/api/v1/admin/**`가 한다.
   */
  role: 'USER' | 'ADMIN'
}

/**
 * 401은 오류가 아니라 "로그아웃 상태"다. `null`로 접어 화면이 로그인 버튼을 그리게 한다.
 * 그 외 오류(네트워크·500 등)는 그대로 던져 상위가 판단한다.
 */
export async function fetchMe(): Promise<Me | null> {
  try {
    return await get<Me>('/auth/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

/** 세션 쿠키를 서버가 만료시킨다. 인증 없이도 동작하는 공개 경로다. */
export function logout(): Promise<void> {
  return post<void>('/auth/logout')
}
