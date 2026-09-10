import type { CSSProperties } from 'react'
import { githubLoginUrl } from '@/features/auth/api/authUrls'
import { HERO_HIGHLIGHTS } from '@/features/landing/landingPreviewData'

/**
 * Hero 좌측 열. 카피와 CTA만 담당하고 미리보기 패널은 ProductPreview가 그린다.
 *
 * `GitHub` 한 단어만 soft blue인 것은 디자인의 의도다(Final 01 Landing).
 * 강조를 늘리면 시선이 흩어져 CTA가 약해진다.
 */
export function HeroSection() {
  return (
    <div>
      <div
        className="lp-rise mb-5 text-xs font-extrabold tracking-[0.22em] text-white/75"
        style={{ '--lp-delay': '60ms' } as CSSProperties}
      >
        DEVELOP YOUR NEXT
      </div>

      <h1
        className="lp-rise m-0 text-[40px] leading-[1.1] font-extrabold tracking-[-0.055em] text-white [text-shadow:0_8px_28px_rgba(25,37,67,0.14)] sm:text-[52px] lg:text-[64px]"
        style={{ '--lp-delay': '140ms' } as CSSProperties}
      >
        내 <span className="text-[#91BDFF]">GitHub</span>로 찾는
        <br />
        맞춤 채용공고
      </h1>

      <p
        className="lp-rise mt-6 mb-[34px] max-w-[470px] text-[17px] leading-[1.78] text-pretty text-white/90"
        style={{ '--lp-delay': '240ms' } as CSSProperties}
      >
        {/* 줄바꿈은 데스크톱 카피의 리듬이다. 좁은 화면에서는 접고 자연스럽게 흘린다. */}
        내 GitHub 기술을 분석해 실제 채용공고와 비교하고,{' '}
        <br className="hidden sm:inline" />
        다음에 어떤 기술을 준비하면 좋을지까지 한눈에 확인하세요.
      </p>

      <div className="lp-rise flex flex-wrap gap-3" style={{ '--lp-delay': '330ms' } as CSSProperties}>
        {/*
          티켓 156에서 연결했다. `<a>`인 것은 진입 엔드포인트가 302로 GitHub에 넘기기
          때문이다. `redirectTo`를 넘기지 않아 목적지는 BE 허용 목록의 첫 항목이 된다.
          기본값을 양쪽에 적어 두면 갈라지므로 BE 한 곳만 갖게 한다.
        */}
        <a
          href={githubLoginUrl()}
          className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-[26px] py-4 text-[15px] font-bold text-white shadow-[0_14px_30px_rgba(31,60,140,0.34)] transition-shadow hover:shadow-[0_18px_38px_rgba(31,60,140,0.42)]"
        >
          GitHub 연동 시작
        </a>
        {/*
          둘러보기의 목적지 화면(S4 공고 매칭)은 아직 라우트가 없다.
          가짜 경로로 보내 404를 띄우는 대신 같은 화면의 미리보기로 스크롤한다.
        */}
        <a
          href="#landing-preview"
          className="rounded-xl border border-white/35 bg-white/10 px-6 py-4 text-[15px] font-bold text-white backdrop-blur-[14px] transition-[background-color,transform] duration-200 hover:-translate-y-px hover:bg-white/20 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
        >
          서비스 둘러보기
        </a>
      </div>

      <div
        className="lp-rise mt-[38px] flex flex-wrap gap-[22px]"
        style={{ '--lp-delay': '420ms' } as CSSProperties}
      >
        {HERO_HIGHLIGHTS.map((text) => (
          <span key={text} className="flex items-center gap-2 text-[13px] text-white/80">
            <i className="h-[5px] w-[5px] rounded-full bg-[#C9DCFF]" />
            {text}
          </span>
        ))}
      </div>
    </div>
  )
}
