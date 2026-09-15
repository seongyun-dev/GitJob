import { NavLink, Outlet, Link } from 'react-router'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * 관리자 화면 셸 · 티켓 S15P21E102-210.
 *
 * 관리자 화면은 사용자 여정의 일부가 아니라 운영 화면이다. 그런데 지금까지 유일한 관리자
 * 화면(기술 후보 검토)이 `AppLayout` 아래에 있어 "My Evidence · 공고 매칭 · 트렌드"
 * 헤더를 달고 있었다. 확정 디자인 `GitJob Admin Monitoring v2`의 헤더는 `ADMIN` 배지와
 * 관리자 화면 두 개만 갖는다.
 *
 * 이 레이아웃이 그 헤더를 갖는다. Monitoring이 기본 진입 화면이고 Technology Registry는
 * 서브 관리자 화면이며, 둘이 서로 오갈 수 있어야 한다는 것이 이 티켓의 요구다.
 *
 * 접근 제어는 하지 않는다. 라우트를 숨겨도 보호가 되지 않고, 실제 제한은 BE가
 * `/api/v1/admin/**`를 ADMIN으로 막아서 한다(`SecurityConfig`). 권한이 없으면 화면이
 * 데이터를 못 받고 그 사실을 표시한다 — 기존 `admin/technology-candidates` 라우트가
 * 세운 판단을 그대로 따른다.
 *
 * 배경과 셸 치수는 `AppLayout`과 같은 값을 쓴다. 관리자 화면이라고 다른 제품처럼 보일
 * 이유는 없다.
 */

const NAV: ReadonlyArray<{ to: string; label: string; end: boolean }> = [
  // `end`가 필요한 이유는 `/admin`이 하위 경로의 접두이기 때문이다. 없으면
  // Technology Registry에 있을 때 Monitoring도 활성으로 보인다.
  { to: '/admin', label: 'Monitoring', end: true },
  { to: '/admin/technology-candidates', label: 'Technology Registry', end: false },
]

const ADMIN_BACKDROP = [
  'radial-gradient(780px 560px at 92% 0%,rgba(158,184,221,0.38),rgba(0,0,0,0) 62%)',
  'radial-gradient(620px 460px at 2% 100%,rgba(186,170,159,0.30),rgba(0,0,0,0) 62%)',
  'linear-gradient(118deg,#F1EEEB 0%,#EEEDEE 50%,#E7EDF7 100%)',
].join(',')

function AdminHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-[rgba(224,231,241,0.9)] bg-white/[0.62] backdrop-blur-[20px]">
      {/* 71px + 아래 테두리 1px = 확정 디자인의 헤더 높이 72px. AppHeader와 같다. */}
      <div className="mx-auto flex h-[71px] w-full max-w-[1520px] items-center gap-6 px-5 sm:px-8 lg:px-12">
        <div className="flex shrink-0 items-center gap-3.5">
          <Link to="/" className="flex items-center" aria-label="GitJob 홈으로">
            <BrandLogo className="h-[30px] lg:h-9" />
          </Link>
          <span className="rounded-[6px] border border-brand-line bg-[#F5F7FA] px-2 py-1 text-[11px] font-extrabold tracking-[0.1em] text-brand-muted">
            ADMIN
          </span>
        </div>

        <nav aria-label="관리자 화면" className="min-w-0 flex-1">
          <ul className="flex items-center justify-center gap-5 overflow-x-auto lg:gap-8">
            {NAV.map((item) => (
              <li key={item.to} className="shrink-0">
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `text-[14px] whitespace-nowrap transition-colors ${
                      isActive
                        ? 'font-[750] text-brand-ink-soft'
                        : 'font-medium text-brand-faint hover:text-brand-ink'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/*
          확정 디자인 헤더 오른쪽의 `admin-ops · 시스템 관리자` 자리. 로그인한 관리자
          정보를 주는 API가 없어(`GET /me` 미구현) 아무것도 렌더하지 않고 자리만 비워
          nav 가운데 정렬을 유지한다. AppHeader와 같은 판단이다.
        */}
        <div className="hidden shrink-0 lg:block lg:w-[132px]" aria-hidden />
      </div>
    </header>
  )
}

export function AdminLayout() {
  return (
    <div className="min-h-full text-brand-ink" style={{ background: ADMIN_BACKDROP }}>
      <AdminHeader />
      {/* 앱 셸(1520)이 아니라 관리자 디자인의 1328. 이유는 `index.css` `.gj-shell-admin`. */}
      <main className="gj-shell-admin">
        <Outlet />
      </main>
    </div>
  )
}
