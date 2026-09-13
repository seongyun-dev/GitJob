import type { CSSProperties } from 'react'
import { SiteFooter } from '@/app/layouts/SiteFooter'
import { HeroSection } from '@/features/landing/components/HeroSection'
import { LandingHeader } from '@/features/landing/components/LandingHeader'
import { ProductPreview } from '@/features/landing/components/ProductPreview'
import { ServiceIntro } from '@/features/landing/components/ServiceIntro'
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
 * Landing CTA는 티켓 156(S15P21E102-155 `[FE] GitHub 연결 화면`의 하위)에서 연결했다.
 * 막아 둔 조건이 "인증 흐름 확정 후"였고, GitHub 단독 로그인으로 확정되어
 * Login·Primary CTA 모두 진입점을 갖는다.
 *
 * 둘 다 같은 곳(`/api/v1/auth/github`)으로 간다. 로그인 수단이 GitHub 하나뿐이라
 * 두 버튼이 갈라질 이유가 아직 없다. 공급자가 늘면 그때 로그인 전용 화면이
 * 선택을 맡는다 — 그 화면의 소유 티켓은 아직 모른다.
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
    /*
      티켓 212에서 Hero 한 장이 스크롤 페이지가 됐다.

      배경을 이 컨테이너 한 곳에 둔다. 스크롤 컨테이너의 배경은 내용과 함께 움직이지
      않으므로(`background-attachment` 기본값) 모든 장이 같은 그라데이션 위를 지나가고
      이음매가 생기지 않는다. 섹션마다 배경을 주면 장이 바뀔 때 경계가 보인다.

      스냅 규칙은 `landing.css`의 `.lp-scroll`·`.lp-snap`에 있다.
    */
    <div className="lp-scroll relative w-full" style={{ background: BACKDROP }}>
      <section className="lp-snap relative flex min-h-dvh w-full flex-col overflow-hidden">
        {/*
        장식 레이어. 겹침 순서가 Final과 같아야 한다. 링을 먼저 그리고 그 위에 흐린 빛
        덩어리를 얹어야 오른쪽 위 링의 흰 테두리가 적당히 씻긴다. 순서를 바꾸면 링이
        너무 또렷해진다. 좁은 화면에서는 본문을 가리는 두 장만 접는다.
      */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        {/*
          오른쪽 큰 링. 티켓 212에서 같은 중심으로 퍼지는 파동을 얹었다.

          링과 파동을 한 상자에 묶어 두는 이유는 둘이 함께 떠다녀야 하기 때문이다.
          바깥 상자가 `lp-drift-alt`로 아주 느리게 흐르고, 그 안에서 파동이 제자리
          중심으로 퍼진다. 파동에 직접 drift를 걸면 두 transform이 한 속성을 두고
          겹쳐 서로를 덮어쓴다.
        */}
        <div className="lp-drift-alt absolute top-[66px] right-[-150px] h-[580px] w-[580px]">
          <div className="absolute inset-0 rounded-full border border-white/70 shadow-[0_0_0_74px_rgba(255,255,255,.15),0_0_0_158px_rgba(255,255,255,.09)]" />
          {/*
            파동 3장. 한 주기가 7초이므로 7/3초씩 어긋내면 간격이 고르게 이어진다.
            테두리만 있는 원이라 뒤의 미리보기 패널을 가리지 않는다.
          */}
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="lp-ripple absolute inset-0 rounded-full border border-white/55"
              style={{ '--lp-delay': `${Math.round((index * 7000) / 3)}ms` } as CSSProperties}
            />
          ))}
        </div>
        <div className="lp-drift absolute bottom-[-190px] left-[-190px] h-[540px] w-[540px] rounded-full border border-white/20" />
        <div className="absolute right-[15%] bottom-[11%] hidden h-px w-[190px] rotate-[-24deg] bg-[linear-gradient(90deg,transparent,rgba(239,163,107,.9),transparent)] lg:block" />
        <div className="lp-drift absolute top-[-170px] right-[110px] h-[640px] w-[640px] rounded-full bg-[radial-gradient(circle_at_42%_42%,rgba(125,155,197,.95),rgba(125,155,197,.55)_46%,transparent_72%)] blur-[38px]" />
        <div className="absolute top-1/2 left-[30%] hidden h-[420px] w-[820px] rotate-[-15deg] rounded-full border border-transparent border-t-white/40 lg:block" />
        <div className="lp-drift-alt absolute top-[-260px] left-[-60px] h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle,rgba(212,181,162,.5),transparent_70%)] blur-[34px]" />
      </div>

        <div className="relative z-[4] mx-auto flex w-full max-w-[1440px] flex-1 flex-col px-5 sm:px-8 lg:px-14">
          <LandingHeader />

          {/*
            `flex-1`로 남는 높이를 채운다. 191은 `lg:min-h-[852px]`로 Final의 940px
            아트보드를 맞췄는데, 이제 이 장이 뷰포트 높이(`min-h-dvh`)를 채워야 스냅
            경계와 화면 경계가 같아진다. 고정 높이를 남겨 두면 창 높이에 따라 다음
            장이 미리 보이거나 잘린다.
          */}
          <div className="grid flex-1 items-center gap-12 pt-8 pb-16 lg:grid-cols-[44%_56%] lg:gap-11 lg:pt-0 lg:pb-20">
            <HeroSection />
            <ProductPreview />
          </div>
        </div>
      </section>

      {/*
        하단바는 마지막 장 안으로 넘긴다. 여기서 `<ServiceIntro />` 뒤에 두면
        데스크톱 스크롤 스냅이 꼬리 요소를 붙잡아 두지 못한다 — 이유는
        `ServiceIntro`의 마지막 장 주석에 있다.

        `onDark`인 것은 이 페이지 배경이 짙은 그라데이션이기 때문이다. 기본
        `light`를 쓰면 진한 글씨가 배경에 묻힌다.
      */}
      <ServiceIntro footer={<SiteFooter tone="onDark" />} />
    </div>
  )
}
