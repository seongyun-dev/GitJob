import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router'
import { HeaderAuthArea } from '@/features/auth/components/HeaderAuthArea'
import { handleLandingTopClick } from '@/features/landing/scrollToHash'
import {
  findActiveNav,
  isNavChildActive,
  PRIMARY_NAV,
  type PrimaryNavItem,
} from '@/shared/config/primaryNav'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * 서비스 헤더 · 랜딩과 로그인 이후 화면이 **같은 컴포넌트**를 쓴다.
 *
 * 이전에는 `AppHeader`와 `LandingHeader`가 따로 있었다. 메뉴 목록과 인증 영역은
 * 이미 공유했지만 골격이 각자여서 조금씩 어긋났다 — 좁은 폭에서 한쪽은 메뉴를
 * 가로 스크롤(스크롤바가 보인다)시키고 다른 쪽은 감췄고, 로그인 버튼도 한쪽만
 * 사라졌다. 화면을 오갈 때 헤더가 다른 물건처럼 보였다.
 *
 * 그래서 **치수·간격·반응형 규칙은 여기 한 곳**에 두고, variant는 두 가지만 바꾼다.
 *   - 배치: 내부는 sticky + 반투명 배경, 랜딩은 hero 위에 얹히는 투명 헤더
 *   - 톤: 내부는 진한 글씨(dark), 랜딩은 흰 글씨(light)
 *
 * 폭(`maxWidth`)만 variant마다 다르다. 헤더는 자기 아래 페이지 컨테이너와 로고가
 * 세로로 맞아야 하는데 그 컨테이너가 서로 다르다 — 내부는 `.gj-shell`(1520px),
 * 랜딩 hero는 1440px이다. 같은 숫자로 맞추면 한쪽에서 로고가 본문 밖으로 밀린다.
 * 1520px 뷰포트 아래에서는 어차피 둘 다 같은 폭이다.
 */

type Variant = 'app' | 'landing'

/*
  현재 메뉴는 **색으로만** 구분한다. 굵기를 함께 올리면 그 항목의 글자 폭이 늘어나
  메뉴가 이동할 때마다 헤더가 몇 px 흔들린다 — 메뉴가 가운데 정렬이라 늘어난 폭이
  양옆으로 퍼져 더 눈에 띈다. 한글은 500과 600의 폭 차이가 특히 크다.

  확정 디자인도 메뉴 네 개가 모두 `font-weight:500`이고 활성 굵기 구분이 없다.
  굵기를 포기해도 색 대비(faint → 600)만으로 현재 위치는 충분히 읽힌다.
*/
const NAV_TONE = {
  landing: {
    base: 'font-medium text-white/85 hover:text-white',
    active: 'font-medium text-white',
  },
  app: {
    base: 'font-medium text-brand-faint hover:text-brand-ink',
    active: 'font-medium text-brand-600',
  },
} as const

/**
 * 서브 내비게이션 · 티켓 S15P21E102-291.
 *
 * 지금 단계에 속한 화면을 헤더 바로 아래 한 줄로 편다. 상단이 "어느 단계인가"를,
 * 이 줄이 "그 안 어디인가"를 말한다.
 *
 * 헤더가 `sticky top-0` 이므로 이 줄도 그 아래에 붙는다(`top-[72px]`). 72px 은 헤더
 * 높이(71px + 아래 테두리 1px)이고 `AppLayout` 이 본문 오프셋에 쓰는 값과 같다.
 * 한쪽만 바뀌면 스크롤할 때 두 줄 사이로 본문이 비친다.
 *
 * 랜딩에서는 그리지 않는다. 로그인 전에는 들어갈 수 있는 화면이 트렌드뿐이라
 * 단계 안을 나눌 것이 없다.
 */
function SubNav({
  item,
  pathname,
  offsetLeft,
}: {
  item: PrimaryNavItem
  pathname: string
  /** 활성 상단 메뉴의 왼쪽 x. 재지 못했으면 `null` 이고 그때는 가운데로 둔다. */
  offsetLeft: number | null
}) {
  if ('kind' in item || item.children === undefined || item.children.length < 2) {
    return null
  }

  return (
    <nav
      aria-label={`${item.label} 하위 화면`}
      className="sticky top-[72px] z-[19] border-b border-brand-line bg-white/85 backdrop-blur-[10px]"
    >
      {/*
        `.gj-shell` 을 쓰지 않는다. 그 클래스는 본문용이라 위아래 패딩(40px/96px)을
        갖고 있어 한 줄짜리 띠에 붙이면 빈 공간이 그만큼 생긴다. 여기서 필요한 것은
        가로 정렬뿐이라 max-width 와 좌우 패딩만 같은 값으로 맞춘다.

        **누른 메뉴 아래에 붙인다.** 왼쪽 끝에 붙여 두었을 때는 위 메뉴와 눈이 좌우로
        크게 오갔고, 가운데로 모았을 때는 어느 메뉴에 속한 줄인지가 흐렸다. 활성 메뉴의
        x 를 재서 그 자리에서 시작하게 하면 두 줄이 하나의 덩어리로 읽힌다.

        재지 못했으면(`null`) 가운데로 둔다 — 상단 메뉴가 감춰지는 좁은 폭이 그렇다.
        그때는 기준이 될 버튼 자체가 없다.

        안쪽이 `w-max` 인 이유는 넘칠 때다. 스크롤 컨테이너에 `justify-center` 를 걸면
        내용이 넘쳤을 때 앞쪽이 잘린 채 스크롤로도 닿지 않는다.
      */}
      <div className="w-full overflow-x-auto">
        <div
          className={`flex h-11 w-max items-center gap-1 ${
            offsetLeft === null ? 'mx-auto px-5 sm:px-8 lg:px-12' : ''
          }`}
          style={offsetLeft === null ? undefined : { marginLeft: offsetLeft }}
        >
          {item.children.map((child) => {
            const active = isNavChildActive(child, pathname)
            return (
              <Link
                key={child.to}
                to={child.to}
                aria-current={active ? 'page' : undefined}
                className={`shrink-0 rounded-lg px-3 py-1.5 text-[13.5px] whitespace-nowrap transition-colors ${
                  active
                    ? 'bg-tone-accent-bg font-[750] text-brand-600'
                    : 'font-medium text-brand-muted hover:bg-tone-neutral-bg hover:text-brand-ink'
                }`}
              >
                {child.label}
              </Link>
            )
          })}
        </div>
      </div>
    </nav>
  )
}

export function SiteHeader({ variant }: { variant: Variant }) {
  const isLanding = variant === 'landing'
  const tone = NAV_TONE[variant]
  const { pathname } = useLocation()
  /*
    상단에서 켜야 할 단계를 경로로 직접 찾는다. `NavLink` 의 기본 판정은 자기 `to` 만
    보기 때문에 공고 상세(`/jobs/:jobId`)나 판정 근거(`/evidence/:techId`) 에서 상단이
    전부 꺼진다 — 어느 단계에 있는지 모르는 화면이 된다.
  */
  const activeItem = findActiveNav(pathname)

  /*
    활성 상단 메뉴의 x 를 재서 서브 줄을 그 아래에 붙인다.

    `useLayoutEffect` 인 이유는 그린 뒤에 재면 한 프레임 동안 서브 줄이 다른 자리에
    있다가 튀기 때문이다. 폭이 바뀌면 메뉴 위치도 바뀌므로 resize 에서 다시 잰다.
  */
  const navRef = useRef<HTMLElement>(null)
  const [offsetLeft, setOffsetLeft] = useState<number | null>(null)

  const measure = useCallback(() => {
    const nav = navRef.current
    const active = nav?.querySelector<HTMLElement>('[data-nav-active="true"]')
    // 상단 메뉴가 감춰지는 폭에서는 `offsetParent` 가 없다. 기준이 없으니 가운데로 둔다.
    if (active === null || active === undefined || active.offsetParent === null) {
      setOffsetLeft(null)
      return
    }
    setOffsetLeft(active.getBoundingClientRect().left)
  }, [])

  useLayoutEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure, pathname, activeItem])

  /*
    랜딩 헤더는 hero 컨테이너(`px-5 sm:px-8 lg:px-14`) 안에 있으므로, 음수 마진으로
    그 패딩을 상쇄한 뒤 아래 컨테이너가 내부 헤더와 같은 리듬(px-5/8/12)으로 다시
    패딩한다. 배경이 없어도 이렇게 해야 로고·메뉴·프로필이 내부 헤더와 겹친다.
  */
  const shell = isLanding
    ? 'relative z-[5] -mx-5 sm:-mx-8 lg:-mx-14'
    : 'sticky top-0 z-20 border-b backdrop-blur-[10px]'

  const bar = (
    <header
      className={`gj-header-bar flex items-center select-none ${shell}`}
      style={
        isLanding
          ? undefined
          : {
              background: 'var(--gj-header-bg-inner)',
              borderColor: 'var(--gj-header-border)',
              // Tailwind 임의 shadow 값이 빌드에서 누락돼(backdrop-filter 와 같은 이슈) 인라인으로 준다.
              boxShadow: '0 1px 6px rgba(16, 24, 40, 0.04)',
            }
      }
    >
      <div
        className={`mx-auto flex h-full w-full items-center gap-6 px-5 sm:px-8 lg:px-12 ${
          isLanding ? 'max-w-[1440px]' : 'max-w-[1520px]'
        }`}
      >
        {/* 로고 크기는 두 헤더가 같다 — 화면을 오갈 때 커졌다 작아지지 않게. 랜딩에서는
            이미 그 페이지이므로 클릭이 라우트 이동이 아니라 맨 위로 스크롤이다. */}
        {isLanding ? (
          <a
            href="/"
            onClick={handleLandingTopClick}
            aria-label="GitJob 홈으로"
            className="flex shrink-0 items-center"
          >
            <BrandLogo className="h-[30px] lg:h-9" />
          </a>
        ) : (
          <Link to="/" className="flex shrink-0 items-center" aria-label="GitJob 홈으로">
            <BrandLogo className="h-[30px] lg:h-9" />
          </Link>
        )}

        {/*
          메뉴는 남는 폭을 차지하고 그 안에서 가운데 정렬한다. 다섯 개가 한 줄에
          들어가지 않는 좁은 폭에서는 **가로 스크롤 대신 감춘다** — 스크롤바가 보이고
          로고·로그인이 밀려 헤더가 깨져 보였다(랜딩이 쓰던 규칙으로 통일).
        */}
        <nav ref={navRef} aria-label="주요 화면" className="hidden min-w-0 flex-1 lg:block">
          <ul className="flex items-center justify-center gap-5 lg:gap-8">
            {PRIMARY_NAV.map((item) => (
              <li key={item.label} className="shrink-0">
                {'kind' in item ? (
                  // 서비스 소개는 메인(랜딩) 화면 자체다. 랜딩에서는 맨 위로 스크롤하고,
                  // 내부 페이지에서는 랜딩으로 이동한다(새로 마운트돼 히어로부터 보인다).
                  isLanding ? (
                    <a
                      href="/"
                      onClick={handleLandingTopClick}
                      className={`text-[15px] whitespace-nowrap transition-colors ${tone.base}`}
                    >
                      {item.label}
                    </a>
                  ) : (
                    <Link
                      to="/"
                      className={`text-[15px] whitespace-nowrap transition-colors ${tone.base}`}
                    >
                      {item.label}
                    </Link>
                  )
                ) : (
                  <NavLink
                    to={item.to}
                    data-nav-active={item === activeItem ? 'true' : undefined}
                    // active 는 색+굵기로만 표시한다. background pill 은 쓰지 않는다.
                    className={`text-[15px] whitespace-nowrap transition-colors ${
                      item === activeItem ? tone.active : tone.base
                    }`}
                  >
                    {item.label}
                  </NavLink>
                )}
              </li>
            ))}
          </ul>
        </nav>

        {/*
          인증 영역은 좁은 폭에서도 남긴다 — 메뉴를 감춘 화면에서 로그인 진입점까지
          사라지면 안 된다. 폭을 미리 잡아 두어야 로그인/프로필 전환에 메뉴 가운데
          정렬이 흔들리지 않는다(`HeaderAuthArea`도 같은 이유로 자리를 비워 둔다).
        */}
        <div className="flex flex-1 shrink-0 justify-end lg:flex-none lg:min-w-[120px]">
          <HeaderAuthArea tone={isLanding ? 'light' : 'dark'} />
        </div>
      </div>
    </header>
  )

  return isLanding ? (
    bar
  ) : (
    <>
      {bar}
      {activeItem !== undefined && (
        <SubNav item={activeItem} pathname={pathname} offsetLeft={offsetLeft} />
      )}
    </>
  )
}
