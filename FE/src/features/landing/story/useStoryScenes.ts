import { useEffect, useRef, useState } from 'react'

/**
 * 스크롤 스토리의 현재 장과 "이미 본 장" 기록 · 티켓 S15P21E102-298.
 *
 * <h2>왜 스크롤 좌표가 아니라 IntersectionObserver 인가</h2>
 *
 * 확정 디자인(`GitJob Landing Storytelling v2`)은 `onScroll`에서 스크롤 좌표를 읽어
 * 장 번호를 계산한다. 그 방식은 매 프레임 레이아웃을 읽어 장면 높이·패딩이 바뀔 때마다
 * 계산식을 같이 고쳐야 하고, 스냅이 걸린 컨테이너에서는 관성 스크롤 도중 값이 튄다.
 *
 * 관찰자는 "이 장이 화면 가운데에 있나"만 묻는다. 높이가 바뀌어도 고칠 곳이 없다.
 *
 * <h2>한 번 본 장은 다시 숨기지 않는다</h2>
 *
 * 되돌아 올라갈 때 사라졌다 다시 나타나면 읽던 사람이 방금 읽은 문장을 잃는다.
 * `seen` 은 한 방향으로만 켜진다.
 */
export interface StoryScenes {
  /** 지금 화면을 차지한 장의 번호(0-base). */
  active: number
  /** 한 번이라도 화면에 들어온 장. 등장 애니메이션의 조건이다. */
  seen: readonly boolean[]
  /** 스크롤 컨테이너. 장 이동 버튼이 이 요소를 움직인다. */
  scrollRef: React.RefObject<HTMLDivElement | null>
  /** 장마다 붙이는 ref 콜백. */
  sceneRef: (index: number) => (node: HTMLElement | null) => void
  /** 인디케이터가 부르는 이동. */
  goTo: (index: number) => void
}

export function useStoryScenes(count: number): StoryScenes {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const nodes = useRef<(HTMLElement | null)[]>([])
  const [active, setActive] = useState(0)
  const [seen, setSeen] = useState<boolean[]>(() =>
    Array.from({ length: count }, (_, index) => index === 0),
  )

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const index = nodes.current.indexOf(entry.target as HTMLElement)
          if (index < 0 || !entry.isIntersecting) {
            continue
          }
          setActive(index)
          setSeen((current) =>
            current[index] ? current : current.map((value, i) => (i === index ? true : value)),
          )
        }
      },
      {
        root: scrollRef.current,
        // 화면 한가운데 띠만 본다. 장이 반쯤 걸쳐 있을 때 두 장이 동시에 켜지지 않는다.
        rootMargin: '-45% 0px -45% 0px',
        threshold: 0,
      },
    )

    for (const node of nodes.current) {
      if (node !== null) {
        observer.observe(node)
      }
    }
    return () => observer.disconnect()
  }, [count])

  function sceneRef(index: number) {
    return (node: HTMLElement | null) => {
      nodes.current[index] = node
    }
  }

  function goTo(index: number) {
    nodes.current[index]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return { active, seen, scrollRef, sceneRef, goTo }
}
