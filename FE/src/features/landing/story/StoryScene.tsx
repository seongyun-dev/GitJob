import type { ReactNode } from 'react'
import type { Scene } from '@/features/landing/story/storyScenes'

/**
 * 장 하나의 껍데기 · 확정 디자인 `GitJob Landing Storytelling v2`.
 *
 * 높이는 뷰포트 한 장이고 스냅이 걸린다. 배경은 장마다 다르다 — 이 스토리는 밝음과
 * 어두움을 번갈아 두어 장이 바뀌었다는 것을 색으로 먼저 알린다.
 *
 * 등장은 `seen` 한 번으로 끝난다. 되돌아 올라갈 때 다시 숨기면 방금 읽은 문장이
 * 사라진다.
 */
export function StoryScene({
  scene,
  seen,
  innerRef,
  children,
}: {
  scene: Scene
  seen: boolean
  innerRef: (node: HTMLElement | null) => void
  children: ReactNode
}) {
  return (
    <section
      ref={innerRef}
      id={scene.id}
      aria-label={scene.title}
      className="lp-snap relative grid h-dvh place-items-center overflow-hidden px-6 pt-[84px] pb-14"
      style={{ background: scene.background }}
    >
      {/*
        장 전체를 한 덩어리로 올리지 않는다. 그러면 다섯 장이 슬라이드처럼 한 장씩
        나타났다 사라지는 발표 자료로 읽힌다. `seen` 이 켜지는 순간 안쪽 요소들이
        각자의 `--lp-delay` 로 차례로 올라오고, 그 시간차가 읽는 순서를 만든다.
      */}
      <div className="grid flex-1 place-items-center">
        <div key={seen ? 'in' : 'out'} className="relative w-full">
          {seen && children}
        </div>
      </div>
    </section>
  )
}

/**
 * 순서를 가진 등장.
 *
 * `lp-rise` 는 이미 랜딩이 쓰던 애니메이션이고 `--lp-delay` 로 시작 시각을 민다.
 * 장마다 같은 리듬(눈썹 → 제목 → 설명 → 행동)을 쓰려고 감싸는 컴포넌트로 둔다.
 */
export function Rise({
  delay = 0,
  className,
  children,
}: {
  /** 밀리초. 같은 장 안에서 읽는 순서대로 늘린다. */
  delay?: number
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={`lp-rise ${className ?? ''}`}
      style={{ '--lp-delay': `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </div>
  )
}
