/**
 * 프로필 드롭다운의 이동 항목 · 티켓 S15P21E102-317.
 *
 * <h2>왜 목록을 컴포넌트 밖에 두나</h2>
 *
 * 관리자에게만 보이는 항목이 생겼다. 무엇이 누구에게 보이는지는 화면을 띄우지 않고 표로
 * 확인할 수 있어야 하는 규칙이다 — 틀리면 일반 사용자에게 관리자 진입로가 보이거나,
 * 관리자가 콘솔로 돌아갈 길을 잃는다.
 *
 * 로그아웃은 여기 없다. 이동이 아니라 동작이고(요청을 보내고 캐시를 비운다) 목적지도
 * 없어 같은 목록에 둘 수 없다. 드롭다운의 마지막 자리는 컴포넌트가 직접 그린다.
 *
 * <h2>역할 판정의 출처</h2>
 *
 * `/auth/me` 가 주는 `role` 하나만 본다. `AdminLayout` 의 role guard 와 같은 값이라
 * 화면에 보이는 것과 실제로 들어갈 수 있는 것이 어긋나지 않는다. 이름 문자열이나 계정을
 * 보고 관리자를 알아내지 않고, FE 전용 플래그를 새로 만들지도 않는다.
 *
 * 메뉴를 감추는 것은 UX 계층이다. 실제 접근 제한은 `AdminLayout` 의 role guard 와 BE 가
 * 계속 담당한다 — 항목이 보이지 않아도 `/admin` 에 직접 들어가면 거기서 막힌다.
 *
 * 아무것도 import 하지 않는다. `@/` 별칭은 Vite 가 푸는 것이라 별칭을 쓰면
 * `node --test` 에서 해석되지 않는다.
 */

/** 관리자 콘솔. `/admin` index 가 System Monitoring 화면이라 별도 경로를 두지 않는다. */
const ADMIN_CONSOLE_PATH = '/admin'

export interface UserMenuLink {
  id: string
  label: string
  to: string
}

const MYPAGE: UserMenuLink = { id: 'mypage', label: '마이페이지', to: '/mypage' }

/** 관리자만 본다. 서비스 화면에서 콘솔로 돌아가는 유일한 길이다. */
const MONITORING: UserMenuLink = {
  id: 'monitoring',
  label: '모니터링',
  to: ADMIN_CONSOLE_PATH,
}

export function userMenuLinks(
  me: { role: 'USER' | 'ADMIN' } | null | undefined,
): readonly UserMenuLink[] {
  if (me === null || me === undefined) {
    return []
  }
  return me.role === 'ADMIN' ? [MYPAGE, MONITORING] : [MYPAGE]
}
