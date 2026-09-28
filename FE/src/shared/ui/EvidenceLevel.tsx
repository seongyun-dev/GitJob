import { lookupLabel } from '@/shared/ui/lookupLabel'
import { Pill } from '@/shared/ui/Pill'
import type { Tone } from '@/shared/ui/Pill'
import type { EvidenceLevel as Level } from '@/shared/types/domain'

/**
 * 근거 수준 배지. 톤은 값에서 자동 결정되며 밖에서 지정하는 prop이 없다(설계 §5-3).
 * 표기와 톤은 와이어프레임 1-2 확정값이다.
 */
const LABELS: Readonly<Record<Level, { text: string; tone: Tone }>> = {
  L0: { text: 'L0 없음', tone: 'neutral' },
  L1: { text: 'L1 노출', tone: 'neutral' },
  L2: { text: 'L2 구현', tone: 'accent' },
  L3: { text: 'L3 운영', tone: 'success' },
}

export function EvidenceLevel({ level }: { level: Level }) {
  const label = lookupLabel(LABELS, level, 'EvidenceLevel')
  if (!label) {
    return null
  }
  return <Pill tone={label.tone}>{label.text}</Pill>
}
