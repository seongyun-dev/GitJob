import { Link } from 'react-router'
import { HeaderAuthArea } from '@/features/auth/components/HeaderAuthArea'
import { handleLandingTopClick } from '@/features/landing/scrollToHash'
import { PRIMARY_NAV } from '@/shared/config/primaryNav'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * Landing 전용 헤더. 유리 배경 위 흰 글씨라 로그인 후 헤더와 톤이 달라 스타일은 따로
 * 두지만, 티켓 246에서 **메뉴 이름·순서·개수·목적지와 인증 영역은 내부 헤더와 통일**했다.
 * 둘 다 `shared/config/primaryNav`와 `HeaderAuthArea`를 쓴다.
 *
 * `서비스 소개`는 메인 화면 자체라 라우트 이동이 아니라 랜딩 맨 위로 스크롤한다
 * (`<a href="/">` + 스크롤 핸들러). 나머지는 실재 라우트라 `<Link>`다.
 *
 * 우측은 이전에 항상 `로그인` 버튼이었으나, 이제 `HeaderAuthArea`가 로그인 상태면
 * 프로필 메뉴를, 아니면 로그인 버튼을 그린다(랜딩도 로그인 상태로 들어올 수 있다).
 */
export function LandingHeader() {
  return (
    // 티켓 246: 메인 헤더는 원래대로 **투명**(배경·테두리 없음)이라 hero와 자연스럽게
    // 섞인다 — 흰 박스형 배경을 두지 않는다. 대비를 위해 글씨는 흰색이고, 로그인/프로필도
    // 밝은 톤(`tone="light"`)이다. 단, 메뉴 구조(PRIMARY_NAV)와 프로필 영역은 217에서
    // 통일한 상태를 유지하고, 높이·로고 크기·좌우 정렬은 내부 헤더와 같은 값으로 맞춘다.
    //
    // hero 컨테이너(`max-w-[1440px] px-5 sm:px-8 lg:px-14`)의 좌우 패딩을 음수 마진으로
    // 상쇄한 뒤 안쪽을 내부 헤더와 같은 리듬(px-5/8/12)으로 다시 패딩한다. 배경이 없어도
    // 이렇게 해야 로고·메뉴·프로필 위치가 내부 헤더와 1024~1440에서 정확히 겹친다.
    <header className="gj-header-bar lp-rise relative z-[5] -mx-5 flex items-center select-none sm:-mx-8 lg:-mx-14">
      <div className="mx-auto flex h-full w-full max-w-[1440px] items-center gap-6 px-5 sm:px-8 lg:px-12">
        {/* 로고 크기는 서브 페이지(앱 헤더·로그인)와 26px로 통일한다 — 화면을 오갈 때
            로고가 커졌다 작아지지 않게. 이미 랜딩이므로 로고 클릭은 이동이 아니라
            맨 위로 스크롤한다(서비스 소개와 동일). */}
        <a
          href="/"
          onClick={handleLandingTopClick}
          aria-label="GitJob 홈으로"
          className="flex shrink-0 items-center"
        >
          <BrandLogo className="h-[30px] lg:h-9" />
        </a>

        <nav aria-label="랜딩 안내" className="hidden min-w-0 flex-1 lg:block">
          <ul className="flex items-center justify-center gap-5 lg:gap-8">
            {PRIMARY_NAV.map((item) => (
              <li key={item.label} className="shrink-0">
                {'kind' in item ? (
                  // 서비스 소개는 메인 화면 처음(히어로)으로. 같은 페이지라 스크롤로 올린다.
                  <a
                    href="/"
                    onClick={handleLandingTopClick}
                    className="text-[15px] font-medium whitespace-nowrap text-white/85 transition-colors hover:text-white"
                  >
                    {item.label}
                  </a>
                ) : (
                  <Link
                    to={item.to}
                    className="text-[15px] font-medium whitespace-nowrap text-white/85 transition-colors hover:text-white"
                  >
                    {item.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        {/* 투명 헤더라 로그인 버튼·사용자 이름은 밝은 톤(흰 글씨). 구조는 내부와 동일. */}
        <div className="flex shrink-0 justify-end">
          <HeaderAuthArea tone="light" />
        </div>
      </div>
    </header>
  )
}
