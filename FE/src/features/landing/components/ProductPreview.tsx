import type { CSSProperties } from 'react'
import {
  PREVIEW_EVIDENCE,
  PREVIEW_STATS,
  PREVIEW_TITLE,
  PREVIEW_WHAT_IF,
} from '@/features/landing/landingPreviewData'

/** 유리 패널 안쪽 카드 3종이 공유하는 표면. 값이 흩어지면 유리 톤이 무너진다. */
const CARD = 'rounded-[18px] border border-white/60 shadow-[0_9px_26px_rgba(28,52,92,0.05)]'

/**
 * Hero 우측의 Frosted Glass 미리보기.
 *
 * 보여주는 숫자는 전부 `landingPreviewData`의 연출용 고정값이다. 로그인 전 화면이라
 * 조회할 사용자가 없고, What-if 증감은 C조 분석 결과라 FE가 만들지 않는다.
 *
 * 지표 카드는 공용 `CountStat`을 쓰지 않는다. 그쪽은 흰 배경 위 정수 전용이고
 * 여기는 유리 위 연출용 문자열이라 톤·타이포가 맞지 않는다.
 */
export function ProductPreview() {
  return (
    <div className="lp-float grid place-items-center">
      <div
        id="landing-preview"
        className="lp-panel-in w-full max-w-[700px] scroll-mt-24 rounded-[30px] border border-white/45 bg-white/20 p-[22px] shadow-[0_30px_80px_rgba(23,45,83,0.22),inset_0_1px_0_rgba(255,255,255,0.5)] backdrop-blur-[28px]"
        style={{ '--lp-delay': '380ms' } as CSSProperties}
      >
        <div className="flex items-center justify-between px-1.5 pt-0.5 pb-3.5">
          <b className="text-sm font-bold tracking-[-0.02em] text-white/95">{PREVIEW_TITLE}</b>
          <span className="rounded-full border border-white/70 bg-white/60 px-2.5 py-1.5 text-[11px] font-bold tracking-[0.08em] text-[#3F73FF]">
            LIVE PREVIEW
          </span>
        </div>

        <div className="grid grid-cols-1 gap-[11px] sm:grid-cols-3">
          {PREVIEW_STATS.map((stat, index) => (
            <div
              key={stat.label}
              className={`lp-rise ${CARD} bg-white/75 p-4`}
              style={{ '--lp-delay': `${620 + index * 90}ms` } as CSSProperties}
            >
              <div className="text-xs font-medium text-[#5F6F86]">{stat.label}</div>
              <div
                className={`mt-1 text-[32px] font-extrabold tracking-[-0.045em] ${
                  stat.accent ? 'text-[#2F5EEB]' : 'text-[#101A2E]'
                }`}
              >
                {stat.value}
                {stat.unit !== '' && <span className="text-base font-bold">{stat.unit}</span>}
              </div>
              <div className="mt-0.5 text-xs text-[#7C8A9E]">{stat.caption}</div>
            </div>
          ))}
        </div>

        <div
          className={`lp-rise ${CARD} mt-[11px] bg-white/80 px-5 py-[18px]`}
          style={{ '--lp-delay': '900ms' } as CSSProperties}
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="text-base font-bold tracking-[-0.02em] text-[#101A2E]">
                {PREVIEW_WHAT_IF.tech}
              </div>
              <div className="mt-[3px] text-xs text-[#5F6F86]">{PREVIEW_WHAT_IF.levelPath}</div>
            </div>
            <span className="shrink-0 rounded-full bg-[#EAF1FF] px-2.5 py-1.5 text-[11px] font-extrabold text-[#2F5EEB]">
              {PREVIEW_WHAT_IF.rank}
            </span>
          </div>

          <div className="mt-4 flex items-end justify-between gap-2">
            <div>
              <div className="text-xs whitespace-nowrap text-[#7C8A9E]">
                {PREVIEW_WHAT_IF.beforeLabel}
              </div>
              <div className="text-[30px] leading-[1.1] font-extrabold tracking-[-0.04em] text-[#1A2743]">
                {PREVIEW_WHAT_IF.before}
              </div>
            </div>

            <div className="flex flex-1 items-center gap-2.5 px-2 pb-1.5 lg:px-[18px]">
              <div className="h-0.5 flex-1 bg-[linear-gradient(90deg,#D7E4FF,#5B8DFF)]" />
              <div className="lp-glow-once text-[26px] font-extrabold tracking-[-0.04em] text-[#2F5EEB]">
                {PREVIEW_WHAT_IF.delta}
              </div>
              <div className="h-0.5 flex-1 bg-[linear-gradient(90deg,#5B8DFF,#D7E4FF)]" />
            </div>

            <div className="text-right">
              <div className="text-xs whitespace-nowrap text-[#7C8A9E]">
                {PREVIEW_WHAT_IF.afterLabel}
              </div>
              <div className="text-[30px] leading-[1.1] font-extrabold tracking-[-0.04em] text-[#1A2743]">
                {PREVIEW_WHAT_IF.after}
              </div>
            </div>
          </div>
        </div>

        <div
          className="lp-rise mt-[11px] flex items-center gap-3 rounded-[18px] border border-white/60 bg-white/70 px-4 py-3.5"
          style={{ '--lp-delay': '1010ms' } as CSSProperties}
        >
          <span className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-xl bg-[#EAF1FF] text-[11px] font-extrabold text-[#2F5EEB]">
            {PREVIEW_EVIDENCE.icon}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs text-[#7C8A9E]">{PREVIEW_EVIDENCE.label}</div>
            {/* 근거 위치는 고정폭이 이 제품의 시각 시그니처다(index.css --font-evidence). */}
            <div className="mt-0.5 truncate font-evidence text-[13.5px] font-bold text-[#1A2743]">
              {PREVIEW_EVIDENCE.location}
            </div>
          </div>
          <span className="hidden text-xs text-[#5F6F86] sm:inline">{PREVIEW_EVIDENCE.usage}</span>
          <span className="rounded-lg border border-[#E0E7F1] bg-[#F5F7FA] px-2.5 py-[5px] text-[11px] font-extrabold text-[#5F6F86]">
            {PREVIEW_EVIDENCE.level}
          </span>
        </div>
      </div>
    </div>
  )
}
