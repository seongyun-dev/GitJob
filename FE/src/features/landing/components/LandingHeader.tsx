import { Link } from 'react-router'
import { githubLoginUrl } from '@/features/auth/api/authUrls'
import { LANDING_NAV } from '@/features/landing/landingPreviewData'
import { handleHashLinkClick } from '@/features/landing/scrollToHash'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * Landing 전용 헤더. 유리 배경 위에 얹히는 흰 글씨 조합이라
 * 로그인 후 화면의 헤더와 톤이 달라 공용으로 올리지 않는다.
 *
 * 내비게이션 항목은 티켓 212에서 링크로 바꿨다. 191의 근거가 "목적지 라우트가 없다"
 * 였는데 192·204에서 모두 생겨 조건이 풀렸다.
 *
 * 로그인 버튼은 티켓 156에서 연결했다. 비활성으로 둔 근거가 "인증 흐름 확정 후"였고,
 * GitHub 단독 로그인으로 확정되어 조건이 풀렸다. 204가 "GitHub Login이 서비스
 * 진입점"을 Production 계약으로 못 박았으므로 그대로 둔다 — Final v2의 `04 Login`
 * 화면은 SSAFY 인증 정책(S15P21E102-182)이 확정된 뒤 그 티켓이 정한다.
 *
 * `<a>`인 것은 진입 엔드포인트가 302로 GitHub에 넘기기 때문이다. 브라우저 최상위
 * 이동이어야 하므로 `<button onClick>`으로 `fetch`하면 안 된다.
 */
export function LandingHeader() {
  return (
    <header className="lp-rise relative z-[5] flex h-[72px] items-center justify-between lg:h-[88px]">
      {/* Final v2 랜딩 헤더는 로고 36px. 헤더가 88px에서 72px로 접힐 때 함께 줄인다. */}
      <BrandLogo className="h-[30px] lg:h-9" />

      {/*
        티켓 212에서 링크로 바꿨다. 191의 근거가 "목적지 화면이 없어 죽은 링크가
        된다"였는데 192·204에서 라우트가 모두 생겨 조건이 풀렸다.

        `서비스 소개`만 같은 화면 안의 앵커라 `<a href="#...">`이고 나머지는 라우트
        이동이라 `<Link>`다. 앵커를 `<Link>`로 만들면 라우터가 `/#landing-preview`를
        경로로 해석해 스크롤이 아니라 이동이 된다.
      */}
      {/* 레이블을 `서비스 소개`로 두면 그 안의 같은 이름 링크와 겹쳐 읽힌다. */}
      <nav aria-label="랜딩 안내" className="hidden items-center gap-[38px] lg:flex">
        {LANDING_NAV.map((item) =>
          'hash' in item ? (
            <a
              key={item.label}
              href={item.hash}
              onClick={handleHashLinkClick}
              className="text-sm font-medium text-white/85 transition-colors hover:text-white"
            >
              {item.label}
            </a>
          ) : (
            <Link
              key={item.label}
              to={item.to}
              className="text-sm font-medium text-white/85 transition-colors hover:text-white"
            >
              {item.label}
            </Link>
          ),
        )}
      </nav>

      {/*
        `<a>`인 것은 진입 엔드포인트가 302로 GitHub에 넘기기 때문이다. 브라우저 최상위
        이동이어야 하므로 `<Link>`나 `fetch`로 부르면 안 된다.
      */}
      <a
        href={githubLoginUrl()}
        className="rounded-xl border border-white/40 bg-white/10 px-5 py-[11px] text-[13.5px] font-bold text-white backdrop-blur-[14px] transition-colors hover:bg-white/20"
      >
        로그인
      </a>
    </header>
  )
}
