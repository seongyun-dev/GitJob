import type { ReactNode } from 'react'

/**
 * 톤 배지의 내부 구현.
 *
 * 이 파일 밖으로 export하지 않는다(설계 §5-4). 임의 문자열을 배지로 만들 수 있게 되면
 * EvidenceLevel·ContributionLabel·JobStatus의 enum 제약이 무의미해진다.
 * 새 배지가 필요하면 값 목록을 가진 전용 컴포넌트를 만든다.
 */
export type Tone = 'neutral' | 'accent' | 'caution' | 'success' | 'danger'

const TONE_CLASSES: Readonly<Record<Tone, string>> = {
  neutral: 'bg-tone-neutral-bg text-tone-neutral',
  accent: 'bg-tone-accent-bg text-tone-accent',
  caution: 'bg-tone-caution-bg text-tone-caution',
  success: 'bg-tone-success-bg text-tone-success',
  danger: 'bg-tone-danger-bg text-tone-danger',
}

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}
