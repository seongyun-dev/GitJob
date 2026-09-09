import { lookupLabel } from '@/shared/ui/lookupLabel'
import { Pill } from '@/shared/ui/Pill'
import type { Tone } from '@/shared/ui/Pill'
import type { ContributionLabel as Value } from '@/shared/types/domain'

/**
 * 기여 라벨 배지.
 *
 * **숫자 prop이 없다.** 기여 비율을 노출하면 다시 점수 평가가 되므로
 * 와이어프레임 1-1이 금지한 항목이다. 값 4종만 받는다.
 *
 * hideSoleAuthor는 목록(S4-B, 생략)과 상세(S5, 표시)의 차이를 다룬다.
 */
const LABELS: Readonly<Record<Value, { text: string; tone: Tone }>> = {
  SOLE_AUTHOR: { text: '주 작성자', tone: 'neutral' },
  CO_AUTHORED: { text: '공동 작업', tone: 'caution' },
  PARTIAL_EDIT: { text: '일부 수정', tone: 'caution' },
  UNVERIFIED: { text: '팀 저장소 · 본인 기여 미확인', tone: 'neutral' },
}

export function ContributionLabel({
  value,
  hideSoleAuthor = false,
}: {
  value: Value
  hideSoleAuthor?: boolean
}) {
  const label = lookupLabel(LABELS, value, 'ContributionLabel')
  if (!label || (hideSoleAuthor && value === 'SOLE_AUTHOR')) {
    return null
  }
  return <Pill tone={label.tone}>{label.text}</Pill>
}
