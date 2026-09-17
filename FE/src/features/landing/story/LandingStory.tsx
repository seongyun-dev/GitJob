import {
  EvidenceScene,
  JobMatchScene,
  ProblemScene,
  StartScene,
  WhatIfScene,
} from '@/features/landing/story/StoryContent'
import { Link } from 'react-router'
import { SCENES } from '@/features/landing/story/storyScenes'
import { useStartPath } from '@/features/landing/story/useStartPath'
import { StoryScene } from '@/features/landing/story/StoryScene'
import { useStoryScenes } from '@/features/landing/story/useStoryScenes'
import { BrandSymbol } from '@/shared/ui/BrandSymbol'

/**
 * 랜딩 스크롤 스토리 · 확정 디자인 `GitJob Landing Storytelling v2` (티켓 S15P21E102-298).
 *
 * <h2>다섯 장이 하나의 문장이다</h2>
 *
 * 문제 → 근거 → 대조 → 다음 → 시작. 각 장이 다음 장의 질문을 만든다. 그래서 스냅으로
 * 한 장씩 끊어 보여주고, 장마다 배경 밝기를 바꿔 "넘어갔다"는 것을 색으로 먼저 알린다.
 *
 * <h2>헤더가 장의 밝기를 따라간다</h2>
 *
 * 밝은 장 위에서 흰 로고를 쓰면 사라진다. 장마다 `chrome` 을 적어 두고 헤더·인디케이터가
 * 현재 장의 값을 읽는다. 색만 바뀌고 위치는 고정이라 스크롤 중에 흔들리지 않는다.
 */
const SCENE_VIEWS = [ProblemScene, EvidenceScene, JobMatchScene, WhatIfScene, StartScene]

export function LandingStory() {
  const { active, seen, scrollRef, sceneRef, goTo } = useStoryScenes(SCENES.length)
  const start = useStartPath()
  const onDark = SCENES[active]?.chrome !== 'onLight'
  const ink = onDark ? 'text-white' : 'text-brand-ink'

  return (
    <div className="relative h-dvh overflow-hidden">
      <header
        className={`absolute inset-x-0 top-0 z-20 flex h-[84px] items-center justify-between px-[clamp(24px,4vw,64px)] transition-colors duration-500 ${ink}`}
      >
        {/*
          로고는 어느 화면에서든 메인으로 간다. 이 화면에서만 "첫 장으로 스크롤"로
          두면 같은 로고가 화면마다 다르게 동작한다.
        */}
        <Link to={start} aria-label="메인으로" className="flex items-center gap-2.5">
          <BrandSymbol className="h-[30px]" />
          <span className="text-[22px] font-extrabold tracking-[-0.04em]">GitJob</span>
        </Link>

        <Link
          to={start}
          className={`inline-flex items-center gap-2 rounded-xl border px-4.5 py-2.5 text-[14px] font-bold backdrop-blur-[14px] transition-colors duration-500 ${
            onDark
              ? 'border-white/20 bg-white/10 text-white'
              : 'border-transparent bg-brand-600 text-white'
          }`}
        >
          바로 시작하기
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M5 12h14" />
            <path d="m12 5 7 7-7 7" />
          </svg>
        </Link>
      </header>

      {/*
        장면 인디케이터. 지금 어디쯤인지와 남은 장의 수를 같이 알린다 — 스냅 스크롤은
        페이지 길이를 스크롤바로 가늠할 수 없어서 이 표시가 없으면 끝을 모른다.
      */}
      <nav
        aria-label="장면 이동"
        className={`absolute top-1/2 right-[clamp(20px,3vw,44px)] z-20 hidden -translate-y-1/2 flex-col gap-4.5 transition-colors duration-500 md:flex ${ink}`}
      >
        {SCENES.map((scene, index) => {
          const current = index === active
          return (
            <button
              key={scene.id}
              type="button"
              onClick={() => goTo(index)}
              aria-label={scene.title}
              aria-current={current ? 'true' : undefined}
              className="flex cursor-pointer items-center justify-end gap-2.5"
            >
              <span
                className={`text-[11px] font-extrabold tracking-[0.14em] whitespace-nowrap transition-opacity duration-300 ${
                  current ? 'opacity-100' : 'opacity-0'
                }`}
              >
                {scene.label}
              </span>
              <span className="relative grid h-[26px] w-[26px] place-items-center">
                <i
                  className={`absolute inset-0 rounded-full border-[1.5px] border-current transition-all duration-300 ${
                    current ? 'scale-100 opacity-100' : 'scale-50 opacity-0'
                  }`}
                />
                <i
                  className={`h-2 w-2 rounded-full bg-current transition-opacity duration-300 ${
                    current ? 'opacity-100' : 'opacity-40'
                  }`}
                />
              </span>
            </button>
          )
        })}
      </nav>

      {/* 마지막 장에서는 더 내려갈 곳이 없으므로 감춘다. */}
      <div
        aria-hidden
        className={`pointer-events-none absolute bottom-7 left-1/2 z-20 flex -translate-x-1/2 flex-col items-center gap-1.5 transition-opacity duration-500 ${ink} ${
          active === SCENES.length - 1 ? 'opacity-0' : 'opacity-70'
        }`}
      >
        <span className="text-[11px] font-bold tracking-[0.18em]">SCROLL</span>
        <svg
          className="lp-bob h-[18px] w-[18px]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      <div ref={scrollRef} className="lp-scroll">
        {SCENES.map((scene, index) => {
          const View = SCENE_VIEWS[index]
          return (
            <StoryScene
              key={scene.id}
              scene={scene}
              seen={seen[index] ?? false}
              innerRef={sceneRef(index)}
            >
              {View !== undefined && <View />}
            </StoryScene>
          )
        })}
      </div>

    </div>
  )
}
