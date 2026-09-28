import { lookupLabel } from '@/shared/ui/lookupLabel'
import { Pill } from '@/shared/ui/Pill'
import type { Tone } from '@/shared/ui/Pill'

/**
 * 기술 후보의 검토 상태 배지.
 *
 * 임의 문자열을 배지로 만들지 않기 위해 값 목록을 가진 전용 컴포넌트로 둔다(설계 §5-4).
 * BE가 상태를 추가하면 `lookupLabel`이 개발 중에만 경고하고 아무것도 그리지 않는다.
 *
 * REVIEWING 은 DB CHECK 제약과 BE 열거형에는 있지만 **이 값을 쓰는 코드가 없다.**
 * 후보는 NEW 로 만들어지고 결정은 PROMOTED·REJECTED 로만 간다. 그래서 별도 표기를
 * 두지 않고 NEW 와 같이 "검토 대기"로 보인다 — 아무도 만들지 않는 상태를 화면에
 * 이름으로 남겨 두면 다음 사람이 그 상태를 만드는 경로를 찾다가 헛수고를 한다.
 *
 * 값 자체는 살려 둔다. 손으로 고친 행이나 나중에 담당자 기능이 생겨 이 값이 오면
 * 배지만 사라지는 대신 미결정으로 읽혀야 한다.
 */
const LABELS: Readonly<Record<string, { text: string; tone: Tone }>> = {
  NEW: { text: '검토 대기', tone: 'accent' },
  REVIEWING: { text: '검토 대기', tone: 'accent' },
  PROMOTED: { text: '승격됨', tone: 'success' },
  REJECTED: { text: '거절됨', tone: 'neutral' },
}

export function CandidateStatus({ status }: { status: string }) {
  const label = lookupLabel(LABELS, status, 'CandidateStatus')
  if (!label) {
    return null
  }
  return <Pill tone={label.tone}>{label.text}</Pill>
}
