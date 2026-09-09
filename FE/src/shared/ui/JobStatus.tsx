import { lookupLabel } from '@/shared/ui/lookupLabel'
import { Pill } from '@/shared/ui/Pill'
import type { Tone } from '@/shared/ui/Pill'
import type { JobStatus as Status } from '@/shared/types/domain'

/** 분석 잡 상태 배지. 표기와 톤은 와이어프레임 1-2 확정값이다. */
const LABELS: Readonly<Record<Status, { text: string; tone: Tone }>> = {
  QUEUED: { text: '대기 중', tone: 'neutral' },
  RUNNING: { text: '분석 중', tone: 'accent' },
  RATE_LIMITED: { text: '호출 한도 대기', tone: 'caution' },
  SUCCEEDED: { text: '완료', tone: 'success' },
  FAILED: { text: '실패', tone: 'danger' },
  CANCELED: { text: '취소됨', tone: 'neutral' },
}

export function JobStatus({ status }: { status: Status }) {
  const label = lookupLabel(LABELS, status, 'JobStatus')
  if (!label) {
    return null
  }
  return <Pill tone={label.tone}>{label.text}</Pill>
}
