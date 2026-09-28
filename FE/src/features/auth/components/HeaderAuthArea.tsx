import { Link } from 'react-router'
import { UserMenu } from '@/features/auth/components/UserMenu'
import { useMe } from '@/features/auth/hooks/useMe'

/**
 * 헤더 우측 인증 영역 · 티켓 S15P21E102-246.
 *
 * 로그인 여부의 단일 출처는 `useMe`다(세션이 HttpOnly라 FE가 쿠키를 못 읽음).
 *   - 확인 중(`data === undefined`): 아무 버튼도 그리지 않는다. 새로고침 순간 로그인
 *     버튼이 잘못 번쩍이는 것을 막는다. 자리 폭은 유지해 레이아웃이 흔들리지 않게 한다.
 *   - 로그아웃(`data === null`): 로그인 버튼.
 *   - 로그인(`data` 있음): 프로필 메뉴. 관리자도 동일하게 프로필만 둔다 — 관리자 진입은
 *     헤더 버튼이 아니라 로그인 직후 자동으로 `/admin`으로 보내는 방식이다(`AuthCallbackPage`).
 *
 * 랜딩과 내부가 같은 컴포넌트를 쓰되 `tone`으로 스타일만 다르게 한다. 로그인 버튼도
 * 랜딩(유리 위 흰 테두리)과 내부(파란 버튼)가 톤만 다르다.
 */

export function HeaderAuthArea({ tone = 'dark' }: { tone?: 'light' | 'dark' }) {
  const { data: me } = useMe()

  if (me === undefined) {
    // 확인 중. 프로필/로그인 폭(약 120px)만큼 자리를 비워 두어 깜빡임을 막는다.
    return <div className="h-9 w-[120px]" aria-hidden />
  }

  if (me === null) {
    // 로그인 페이지(`/login`)를 거친다 — 곧바로 GitHub으로 넘기지 않고 무엇에 로그인하는지
    // 한 번 보여준 뒤 그 화면의 버튼이 GitHub 진입점을 연다. 라우트라 <Link>를 쓴다.
    return tone === 'light' ? (
      <Link
        to="/login"
        className="rounded-xl border border-white/40 bg-white/10 px-5 py-[11px] text-[13.5px] font-bold text-white backdrop-blur-[14px] transition-colors hover:bg-white/20"
      >
        로그인
      </Link>
    ) : (
      <Link
        to="/login"
        className="rounded-xl bg-linear-to-br from-brand-600 to-brand-400 px-5 py-2.5 text-[13.5px] font-bold text-white shadow-[0_10px_24px_rgba(47,94,235,0.22)] transition-shadow hover:shadow-[0_14px_30px_rgba(47,94,235,0.3)]"
      >
        로그인
      </Link>
    )
  }

  // 관리자도 프로필만 — 관리자 화면 진입은 로그인 직후 자동 이동으로 처리한다.
  return <UserMenu me={me} tone={tone} />
}
