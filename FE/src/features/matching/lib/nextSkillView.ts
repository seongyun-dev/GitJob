import type { NextSkill } from '@/features/matching/api/types'

/**
 * 학습 기술 후보의 표시 모양 · 티켓 S15P21E102-281.
 *
 * 계약(`api/types.ts`)에 `rank`가 없는 이유는 그것이 판정이 아니라 **목록에서 몇
 * 번째인가**이기 때문이다. 서버가 보내면 배열 순서와 어긋날 수 있는 값이 하나 는다.
 * 순서 자체는 서버가 정하고(추천 순위는 C조 계산), 화면은 그 순서에 라벨만 붙인다.
 *
 * **네 화면이 이 한 함수를 쓴다** — 화면 10(추천)·03(What-if)·17(Skill Gap 하단)·
 * 11(기술 상세). 화면마다 라벨을 만들면 같은 기술이 화면마다 다른 번호로 보일 수 있다.
 */
export interface NextSkillView extends NextSkill {
  /** `#1` 형태의 순위 라벨. 배열 순서에서 나온다. */
  rank: string
}

export function toNextSkillViews(skills: readonly NextSkill[] | undefined): NextSkillView[] {
  return (skills ?? []).map((skill, index) => ({ ...skill, rank: `#${index + 1}` }))
}
