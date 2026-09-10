import { Link, NavLink } from 'react-router'

/**
 * 로그인 이후 화면의 서비스 헤더.
 *
 * 치수·색은 `GitJob Desktop UI Final.html`의 로그인 이후 섹션 헤더 computed style이다.
 *   height 72px · padding 0 48px
 *   background rgba(255,255,255,0.62) · border-bottom 1px solid rgba(224,231,241,0.9)
 *   로고 gap 10px · 네비게이션 14px / weight 500 / #7C8A9E / gap 32px
 *
 * 117 시점에는 네비게이션을 두지 않았다. 갈 수 있는 경로가 `/`와 저장소 선택뿐이라
 * 메뉴를 그리면 동작하지 않는 가짜 기능이 되기 때문이다. 192에서 Evidence·공고 매칭·
 * 다음 기술·트렌드·마이페이지 라우트가 실제로 생겼으므로 이제 네비게이션이 실재한다.
 *
 * 마이페이지는 Final 헤더에는 없지만 추가했다. Final은 4개만 두는데 그러면
 * `/mypage`에 도달할 방법이 없어 전체 흐름 탐색이 끊긴다(192의 완료 기준).
 *
 * 오른쪽 사용자 영역은 여전히 비워 둔다. Final은 `마지막 분석 오늘 10:42`를 두지만
 * 그 값을 주는 API가 없고(`GET /analyses/{id}` 미구현), 사용자 이름도 `GET /me`가
 * 없어 얻을 수 없다. 없는 값을 demo 문자열로 채우지 않는다.
 */

const NAV: ReadonlyArray<{ to: string; label: string }> = [
  { to: '/evidence', label: 'My Evidence' },
  { to: '/jobs', label: '공고 매칭' },
  { to: '/recommendations', label: '다음 기술' },
  { to: '/trends', label: '트렌드' },
  { to: '/mypage', label: '마이페이지' },
]

export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-[rgba(224,231,241,0.9)] bg-white/[0.62] backdrop-blur-[14px]">
      {/* 71px + bottom border 1px = Final의 header 총 높이 72px. */}
      <div className="mx-auto flex h-[71px] w-full max-w-[1440px] items-center gap-8 px-6 lg:px-12">
        <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label="GitJob 홈으로">
          <span className="grid size-[30px] place-items-center rounded-[10px] bg-[linear-gradient(145deg,#1B2B4A,#4F82FF)] text-[13px] font-extrabold tracking-[-0.03em] text-white shadow-[0_8px_18px_rgba(26,53,110,0.20)]">
            G
          </span>
          <span className="text-[17px] font-extrabold tracking-[-0.035em] text-brand-ink-soft">
            GitJob
          </span>
        </Link>

        <nav aria-label="주요 화면" className="min-w-0 flex-1">
          <ul className="flex items-center gap-5 overflow-x-auto lg:gap-8">
            {NAV.map((item) => (
              <li key={item.to} className="shrink-0">
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    `text-[14px] font-medium whitespace-nowrap transition-colors ${
                      isActive ? 'text-brand-600' : 'text-brand-faint hover:text-brand-ink'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  )
}
