import { Link, NavLink } from 'react-router'
import { HeaderAuthArea } from '@/features/auth/components/HeaderAuthArea'
import { PRIMARY_NAV, SERVICE_INTRO_HASH } from '@/shared/config/primaryNav'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * 로그인 이후 화면의 서비스 헤더.
 *
 * 치수·색은 `GitJob Desktop UI Final.html`의 로그인 이후 섹션 헤더 computed style이다.
 *   height 72px · padding 0 48px
 *   background rgba(255,255,255,0.62) · border-bottom 1px solid rgba(224,231,241,0.9)
 *
 * 티켓 246: 메뉴를 랜딩과 통일한다. 이름·순서·개수·목적지는 `shared/config/primaryNav`
 * 한곳에서 오고, 랜딩 헤더도 같은 config를 쓴다. 마이페이지는 상단에서 빼 프로필
 * 드롭다운(`HeaderAuthArea` → `UserMenu`)으로 옮겼다.
 *
 * 오른쪽 사용자 영역은 이제 `GET /auth/me`(246)로 실제 로그인 사용자를 그린다. 값이
 * 없던 이전과 달리 이름·아바타·GitHub 연결 상태가 실데이터다.
 */

export function AppHeader() {
  // 티켓 246: 순백 대신 옅은 blue-gray 불투명 배경 + 은은한 테두리·그림자로 콘텐츠와
  // 구분한다. 강한 blur/glass 는 쓰지 않는다(거의 불투명이라 불필요). 높이는 랜딩과
  // 공유하는 토큰(`.gj-header-bar`)에서 온다.
  return (
    <header
      className="gj-header-bar sticky top-0 z-10 border-b backdrop-blur-[10px]"
      style={{
        background: 'var(--gj-header-bg-inner)',
        borderColor: 'var(--gj-header-border)',
        // Tailwind 임의 shadow 값이 빌드에서 누락돼(backdrop-filter 와 같은 이슈) 인라인으로 준다.
        // 흰색이 살짝 비쳐 그라데이션과 이어지되, 은은한 그림자로 콘텐츠 위에 떠 있음을 보인다.
        boxShadow: '0 1px 6px rgba(16, 24, 40, 0.04)',
      }}
    >
      <div className="mx-auto flex h-full w-full max-w-[1520px] items-center gap-6 px-5 sm:px-8 lg:px-12">
        <Link to="/" className="flex shrink-0 items-center" aria-label="GitJob 홈으로">
          {/* Final v2 앱 헤더는 로고 26px. */}
          <BrandLogo className="h-[26px]" />
        </Link>

        {/*
          네비게이션은 남는 폭을 차지하고 그 안에서 가운데 정렬한다. active 메뉴는
          `NavLink`가 현재 경로를 굵게+진하게 표시한다(밑줄 대신 굵기·색 — 기존 톤 유지).
        */}
        <nav aria-label="주요 화면" className="min-w-0 flex-1">
          <ul className="flex items-center justify-center gap-5 overflow-x-auto lg:gap-8">
            {PRIMARY_NAV.map((item) => (
              <li key={item.label} className="shrink-0">
                {'kind' in item ? (
                  // 서비스 소개는 랜딩의 섹션이라 내부 페이지에서는 랜딩으로 이동한다.
                  // 전체 이동(`<a>`)이라 브라우저가 로드 후 해당 앵커로 스크롤한다.
                  <a
                    href={`/${SERVICE_INTRO_HASH}`}
                    className="text-[14px] font-medium whitespace-nowrap text-brand-faint transition-colors hover:text-brand-ink"
                  >
                    {item.label}
                  </a>
                ) : (
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      // active = primary blue + weight 600(과하지 않게). hover 는 기본보다
                      // 진한 색으로만 — active 와 혼동되지 않게 background pill 은 쓰지 않는다.
                      `text-[14px] whitespace-nowrap transition-colors ${
                        isActive
                          ? 'font-semibold text-brand-600'
                          : 'font-medium text-brand-faint hover:text-brand-ink'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                )}
              </li>
            ))}
          </ul>
        </nav>

        <div className="hidden shrink-0 justify-end lg:flex lg:min-w-[120px]">
          <HeaderAuthArea tone="dark" />
        </div>
      </div>
    </header>
  )
}
