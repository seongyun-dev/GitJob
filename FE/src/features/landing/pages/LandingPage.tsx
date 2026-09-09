import { HeroSection } from '@/features/landing/components/HeroSection'
import { LandingHeader } from '@/features/landing/components/LandingHeader'
import { ProductPreview } from '@/features/landing/components/ProductPreview'
import '@/features/landing/landing.css'

/**
 * S1 Landing · 티켓 S15P21E102-191.
 *
 * Final 디자인(`GitJob Desktop UI Final.dc.html`의 01 Landing 아트보드) 기준이며
 * 데스크톱 1440×940을 먼저 맞추고 아래로 접는다.
 *
 * `AppLayout`을 쓰지 않는 유일한 화면이다. 배경 그라데이션이 화면 전체를 덮어야 하는데
 * AppLayout은 흰 배경에 `max-w-5xl` 본문을 강제한다. 로그인 후 화면들과 골격이 다르므로
 * 라우터에서 레이아웃 밖에 둔다.
 */

/*
 * TODO(auth): SSAFY → GitHub 연결 흐름 확정 후 Landing CTA 연결.
 * Related: S15P21E102-181/182, S15P21E102-155/156
 *
 * 확정 전까지 Login·Primary CTA는 Final의 시각만 유지하고 동작을 막아 둔다.
 */

/**
 * 배경 레이어. 색 하나하나가 Final의 값이라 유틸리티로 쪼개면 오히려 읽기 어렵다.
 * 톤 토큰 5종은 근거·상태 배지의 의미 체계라 이 연출색과 섞지 않는다(index.css).
 */
const BACKDROP =
  'linear-gradient(100deg,rgba(60,50,48,.12),transparent 58%),' +
  'radial-gradient(820px 640px at 76% 22%,rgba(125,155,197,.7),transparent 64%),' +
  'radial-gradient(820px 380px at 48% 104%,rgba(186,170,159,.85),transparent 66%),' +
  'radial-gradient(520px 420px at 94% 90%,rgba(212,181,162,.42),transparent 62%),' +
  'radial-gradient(720px 620px at 0% 100%,rgba(166,148,138,.95),transparent 66%),' +
  'linear-gradient(112deg,#A9998F 0%,#B3A69C 22%,#BCB8B7 44%,#C0C0C5 56%,#AABDD9 78%,#9EB8DD 100%)'

export function LandingPage() {
  return (
    <section
      className="relative min-h-full w-full overflow-hidden lg:h-[940px]"
      style={{ background: BACKDROP }}
    >
      {/*
        장식 레이어. 겹침 순서가 Final과 같아야 한다. 링을 먼저 그리고 그 위에 흐린 빛
        덩어리를 얹어야 오른쪽 위 링의 흰 테두리가 적당히 씻긴다. 순서를 바꾸면 링이
        너무 또렷해진다. 좁은 화면에서는 본문을 가리는 두 장만 접는다.
      */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="lp-drift-alt absolute top-[66px] right-[-150px] h-[580px] w-[580px] rounded-full border border-white/70 shadow-[0_0_0_74px_rgba(255,255,255,.15),0_0_0_158px_rgba(255,255,255,.09)]" />
        <div className="lp-drift absolute bottom-[-190px] left-[-190px] h-[540px] w-[540px] rounded-full border border-white/20" />
        <div className="absolute right-[15%] bottom-[11%] hidden h-px w-[190px] rotate-[-24deg] bg-[linear-gradient(90deg,transparent,rgba(239,163,107,.9),transparent)] lg:block" />
        <div className="lp-drift absolute top-[-170px] right-[110px] h-[640px] w-[640px] rounded-full bg-[radial-gradient(circle_at_42%_42%,rgba(125,155,197,.95),rgba(125,155,197,.55)_46%,transparent_72%)] blur-[38px]" />
        <div className="absolute top-1/2 left-[30%] hidden h-[420px] w-[820px] rotate-[-15deg] rounded-full border border-transparent border-t-white/40 lg:block" />
        <div className="lp-drift-alt absolute top-[-260px] left-[-60px] h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle,rgba(212,181,162,.5),transparent_70%)] blur-[34px]" />
      </div>

      <div className="relative z-[4] mx-auto w-full max-w-[1440px] px-5 sm:px-8 lg:px-14">
        <LandingHeader />

        <div className="grid items-center gap-12 pt-8 pb-16 lg:min-h-[852px] lg:grid-cols-[44%_56%] lg:gap-11 lg:pt-0 lg:pb-20">
          <HeroSection />
          <ProductPreview />
        </div>
      </div>
    </section>
  )
}
