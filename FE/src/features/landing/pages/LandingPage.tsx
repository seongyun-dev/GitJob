import { LandingStory } from '@/features/landing/story/LandingStory'
import '@/features/landing/landing.css'

/**
 * S1 Landing · 확정 디자인 `GitJob Landing Storytelling v2` (티켓 S15P21E102-298).
 *
 * `AppLayout`을 쓰지 않는 유일한 화면이다. 배경이 장마다 화면 전체를 덮어야 하는데
 * AppLayout은 흰 배경에 고정 폭 본문을 강제한다. 골격이 다르므로 라우터에서 레이아웃
 * 밖에 둔다.
 *
 * 화면 자체는 {@link LandingStory} 가 갖는다. 이 파일은 라우트가 무엇을 그리는지만
 * 말한다 — 이전 판은 여기서 장면 상태(고른 직무)까지 들고 있었는데, 그 상태를 쓰는 장이
 * 하나뿐이라 페이지가 들고 있을 이유가 없었다.
 */
export function LandingPage() {
  return <LandingStory />
}
