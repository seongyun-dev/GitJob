import type { CSSProperties, ReactNode } from 'react'

/**
 * 소개 장들이 함께 쓰는 흐름 부품 · Landing Redesign.
 *
 * 여러 장이 `동그라미 — 선 — 동그라미`로 한 방향의 처리를 말한다. 생김새가 같은
 * 것을 각자 적어 두면 색과 그림자 값이 서서히 갈라지므로 여기 한 곳에 둔다.
 *
 * 크기는 `circleClassName`으로 받는다. 마지막 장이 끝 단계를 일부러 크게 그려
 * "넓어졌다"를 크기로 말하기 때문에 고정 크기로는 부족하다.
 */

/**
 * 동그라미 세 종류. 디자인이 이 셋으로 단계의 성격을 구분한다.
 *
 *   glass — 바깥에서 들어오거나 나가는 것
 *   dark  — GitJob이 직접 하는 일. 화면에서 가장 진해 시선이 여기 멈춘다
 *   solid — 결과로 손에 쥐는 것
 */
const TONE = {
  glass:
    'border border-white/55 bg-white/[0.18] text-white shadow-[0_20px_50px_rgba(23,45,83,0.16)] backdrop-blur-[20px]',
  dark: 'border border-[rgba(145,189,255,0.5)] bg-[linear-gradient(160deg,#233A6B,#101A2E)] text-white shadow-[0_26px_60px_rgba(16,26,46,0.4)]',
  solid:
    'border border-white/90 bg-white/[0.86] text-[#2F5EEB] shadow-[0_20px_50px_rgba(23,45,83,0.18)]',
} as const

export type FlowTone = keyof typeof TONE

export function FlowNode({
  tone,
  label,
  icon,
  circleClassName = 'h-[84px] w-[84px] lg:h-[104px] lg:w-[104px]',
  ring = false,
  children,
}: {
  tone: FlowTone
  label: string
  icon: ReactNode
  circleClassName?: string
  /** 퍼지는 링. GitJob이 지금 처리 중이라는 표시라 dark 동그라미에만 붙인다. */
  ring?: boolean
  /** 동그라미 안에 겹쳐 그릴 것. 마지막 장의 동심원처럼 한 곳에서만 필요한 장식이다. */
  children?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 lg:gap-4">
      <span
        className={`relative grid place-items-center rounded-full ${TONE[tone]} ${circleClassName}`}
      >
        {ring ? (
          <i
            aria-hidden="true"
            className="lp-ring absolute inset-0 rounded-full border-[1.5px] border-[rgba(145,189,255,0.6)]"
          />
        ) : null}
        {children}
        {/*
          `relative`인 것은 위 장식들이 절대 배치이기 때문이다. 절대 배치 요소는
          DOM 순서와 무관하게 정적 요소 위에 그려지므로, 아이콘도 위치를 가져야
          퍼지는 링과 동심원 위에 온다.
        */}
        <span className="relative grid place-items-center">{icon}</span>
      </span>
      <span className="text-[15px] font-bold text-white sm:text-[17px] lg:text-[19px]">{label}</span>
    </div>
  )
}

/**
 * 단계를 잇는 선. 선 위를 빛이 한 방향으로 지나간다.
 *
 * `aria-hidden`인 것은 이 선이 장식이기 때문이다. 순서는 단계 이름이 나열된 순서로
 * 이미 읽히고, 스크린 리더에 "선"을 읽어 줄 이유가 없다.
 *
 * 좁은 화면에서는 호출부가 아예 그리지 않는다. 세로로 쌓인 단계 사이에 가로선을
 * 두면 방향이 거꾸로 읽힌다.
 */
export function FlowConnector({
  direction = 'out',
  delay = '0ms',
  className = '',
}: {
  /** out은 흰색에서 파랑으로, in은 파랑에서 흰색으로. 빛이 향하는 쪽이 진하다. */
  direction?: 'out' | 'in'
  /** 선마다 어긋내지 않으면 빛 여럿이 한 줄로 붙어 하나처럼 보인다. */
  delay?: string
  className?: string
}) {
  const gradient =
    direction === 'out'
      ? 'bg-[linear-gradient(90deg,rgba(255,255,255,0.3),rgba(145,189,255,0.9))]'
      : 'bg-[linear-gradient(90deg,rgba(145,189,255,0.9),rgba(255,255,255,0.3))]'

  return (
    <div aria-hidden="true" className={`relative h-[3px] rounded-sm ${gradient} ${className}`}>
      {/*
        `left`를 움직이는 애니메이션이라 부모가 기준이다. 부모에 `relative`가 없으면
        빛이 화면 왼쪽 끝에서 출발한다.
      */}
      <i
        className="lp-travel absolute -top-[5px] h-[13px] w-[13px] rounded-full bg-white shadow-[0_0_22px_6px_rgba(145,189,255,0.85)]"
        style={{ '--lp-delay': delay } as CSSProperties}
      />
    </div>
  )
}
