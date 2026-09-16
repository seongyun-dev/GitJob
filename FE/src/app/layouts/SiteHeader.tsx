import { Link, NavLink } from 'react-router'
import { HeaderAuthArea } from '@/features/auth/components/HeaderAuthArea'
import { handleLandingTopClick } from '@/features/landing/scrollToHash'
import { PRIMARY_NAV } from '@/shared/config/primaryNav'
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

const NAV_TONE = {
  landing: {
    base: 'font-medium text-white/85 hover:text-white',
    active: 'font-semibold text-white',
  },
  app: {
    base: 'font-medium text-brand-faint hover:text-brand-ink',
    active: 'font-semibold text-brand-600',
  },
} as const

export function SiteHeader({ variant }: { variant: Variant }) {
  const isLanding = variant === 'landing'
  const tone = NAV_TONE[variant]

  /*
    랜딩 헤더는 hero 컨테이너(`px-5 sm:px-8 lg:px-14`) 안에 있으므로, 음수 마진으로
    그 패딩을 상쇄한 뒤 아래 컨테이너가 내부 헤더와 같은 리듬(px-5/8/12)으로 다시
    패딩한다. 배경이 없어도 이렇게 해야 로고·메뉴·프로필이 내부 헤더와 겹친다.
  */
  const shell = isLanding
    ? 'relative z-[5] -mx-5 sm:-mx-8 lg:-mx-14'
    : 'sticky top-0 z-20 border-b backdrop-blur-[10px]'

  return (
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
        <nav aria-label="주요 화면" className="hidden min-w-0 flex-1 lg:block">
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
                    className={({ isActive }) =>
                      // active 는 색+굵기로만 표시한다. background pill 은 쓰지 않는다.
                      `text-[15px] whitespace-nowrap transition-colors ${
                        isActive ? tone.active : tone.base
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
}
