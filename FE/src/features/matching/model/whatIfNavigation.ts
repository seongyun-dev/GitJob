import type { NextSkillView } from '@/features/matching/model/view'

export type WhatIfImpactKind = 'ALL' | 'REQUIRED' | 'PREFERRED'

/**
 * 처음 여는 What-if 목록은 필수 요구를 우선한다.
 *
 * 필수 영향이 없을 때 REQUIRED를 기본으로 고정하면, 우대 공고가 있어도 빈 목록부터
 * 보게 된다. 두 영향이 모두 없을 때만 합집합 탭을 열어 "영향 없음"을 정확히 보인다.
 */
export function defaultWhatIfImpactKind(
  skill: Pick<NextSkillView, 'requiredImpactCount' | 'preferredImpactCount'>,
): WhatIfImpactKind {
  if ((skill.requiredImpactCount ?? 0) > 0) {
    return 'REQUIRED'
  }
  if ((skill.preferredImpactCount ?? 0) > 0) {
    return 'PREFERRED'
  }
  return 'ALL'
}

export function whatIfHref(skill: Pick<NextSkillView, 'techId' | 'requiredImpactCount' | 'preferredImpactCount'>): string {
  return `/what-if?tech=${encodeURIComponent(skill.techId)}&kind=${defaultWhatIfImpactKind(skill)}`
}
