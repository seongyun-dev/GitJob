import type { ReactNode } from 'react'

/**
 * 데이터 영역과 각주 · 티켓 S15P21E102-192.
 *
 * `GitJob Desktop UI Final.html`의 로그인 이후 화면은 hero 아래를 카드 한 줄로
 * 채우지 않는다. 지표 행 · 목록 · 우측 패널 같은 **영역**으로 나누고 각 영역이
 * 자기 제목을 갖는다. 아래가 그 영역의 껍데기다.
 *
 * 이렇게 나누는 이유가 시각만은 아니다. 조회 API가 없는 화면에서 `StateCard`를
 * 화면 최상위에 덩그러니 두면 "화면 전체가 준비 중"으로 읽힌다. 영역을 먼저 세우고
 * 그 **안쪽**에 준비 중 상태를 넣으면 무엇이 들어올 자리인지가 드러난다.
 *
 * 표면 값은 Final 카드와 같다. radius 18px · border 1px #E0E7F1 · 흰 배경 ·
 * shadow rgba(25,47,81,0.07) 0 10px 28px.
 */
export function DataRegion({
  eyebrow,
  title,
  hint,
  action,
  children,
}: {
  eyebrow: string
  title: string
  /** 영역 제목 옆 보조 설명. 정적 문구만 넣는다 */
  hint?: string
  /** 제목 줄 오른쪽 영역. 실제 데이터가 없으면 넘기지 않는다 */
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)] 3xl:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">{eyebrow}</p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            {title}
          </h2>
          {hint !== undefined && (
            <p className="mt-1.5 text-[13px] leading-[1.6] text-brand-muted">{hint}</p>
          )}
        </div>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

/**
 * 화면 맨 아래 각주.
 *
 * Final의 evidence · nextskill · trenddetail이 모두 본문 아래 한 줄 각주로 판정의
 * 한계를 밝힌다. 점수로 환산하지 않는다는 제품 원칙을 화면에 남기는 자리다.
 */
export function PageFootnote({ children }: { children: ReactNode }) {
  return <p className="mt-4 text-[12.5px] leading-[1.7] text-brand-faint">{children}</p>
}
