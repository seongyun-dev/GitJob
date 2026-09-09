import { lookupLabel } from '@/shared/ui/lookupLabel'
import { Pill } from '@/shared/ui/Pill'
import type { Tone } from '@/shared/ui/Pill'

/**
 * 저장소 상태 배지 · 티켓 S15P21E102-117.
 *
 * `Pill`을 화면 코드에서 직접 쓰지 않기 위한 전용 컴포넌트다(설계 §5-4).
 * 값 목록을 닫아 두는 것이 목적이므로 임의 문자열을 받는 prop을 만들지 않는다.
 *
 * 두 값만 두는 이유: BE `RepositorySummaryResponse`가 화면에 주는 상태 정보는
 * `isPrivate`과 `analyzable` 뿐이다. fork·tutorial 여부는 응답에 없어서
 * 배지를 만들 근거가 없다(계약 2장).
 *
 * `language`는 배지로 만들지 않는다. GitHub이 주는 자유 문자열이라 값 목록을
 * 닫을 수 없고, 그러면 이 컴포넌트의 제약이 무의미해진다. 본문 텍스트로 쓴다.
 */
export type RepositoryState =
  /** 비공개 저장소. 정보 표시일 뿐 분석 가능 여부와 무관하다 */
  | 'PRIVATE'
  /** `analyzable === false`. BE 기준으로 보관(archived) 또는 비활성(disabled) */
  | 'UNANALYZABLE'
  /**
   * 이 저장소의 분석 등록 요청이 실패했다. 잡 상태가 아니라 요청 결과다.
   * `JobStatus`의 `FAILED`를 쓰지 않는 이유: 그 값은 서버가 만든 잡의 상태이고,
   * 여기서는 잡이 생기지도 않았다. 같은 배지를 쓰면 도메인을 섞는다.
   */
  | 'REQUEST_FAILED'

const LABELS: Readonly<Record<RepositoryState, { text: string; tone: Tone }>> = {
  PRIVATE: { text: '비공개', tone: 'neutral' },
  UNANALYZABLE: { text: '분석 불가', tone: 'caution' },
  REQUEST_FAILED: { text: '요청 실패', tone: 'danger' },
}

export function RepositoryStateBadge({ state }: { state: RepositoryState }) {
  const label = lookupLabel(LABELS, state, 'RepositoryStateBadge')
  if (!label) {
    return null
  }
  return <Pill tone={label.tone}>{label.text}</Pill>
}
