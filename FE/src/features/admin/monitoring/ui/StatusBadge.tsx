import type { ReactNode } from 'react'
import {
  PROMETHEUS_STATE_DISPLAY,
  stateCardKindFor,
} from '@/features/admin/monitoring/model/monitoringState'
import type { DisconnectedState, PrometheusState } from '@/features/admin/monitoring/model/monitoringState'
import type { Tone } from '@/shared/ui/Pill'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 모니터링 전용 상태 표시 · 티켓 S15P21E102-210.
 *
 * 공용 `StateCard`를 그대로 쓰지 않고 전용 배지를 두는 이유는, 이 화면이 답해야 하는
 * 질문이 "데이터가 있나"가 아니라 "무엇이 고장났고 누가 고쳐야 하나"이기 때문이다.
 * `NOT_CONFIGURED`(env 미설정)와 `UNREACHABLE`(관리자망 단절)은 담당자가 다른데, 공용
 * 어휘로 옮기면 둘 다 같은 카드가 된다.
 *
 * 도메인 상태를 그대로 보여주고, 공용 카드가 필요한 자리에서만 fallback 매핑을 쓴다.
 */

/**
 * 관리자 화면의 상태 배지.
 *
 * 공용 `Pill`(둥근 필 · 12px · weight 500)이 아니라 확정 디자인 `Admin Monitoring v2`의
 * `badge()` 형태다 — 11px · weight 800 · letter-spacing .06em · padding 5px 9px · radius 6px.
 * 운영 화면은 상태 글자가 표·카드 사이에서 한눈에 잡혀야 해서 디자인이 일부러 각지고
 * 진하게 그렸다. 톤 색은 `Pill`과 같은 토큰을 써서 의미 체계는 공유한다.
 *
 * `Pill`을 고치지 않는 이유: 그 컴포넌트는 EvidenceLevel·JobStatus 등 사용자 화면 전체가
 * 쓰는 공용 어휘라 여기 형태로 바꾸면 그 화면들의 디자인이 어긋난다.
 */
const BADGE_TONE: Readonly<Record<Tone, string>> = {
  neutral: 'bg-tone-neutral-bg text-tone-neutral',
  accent: 'bg-tone-accent-bg text-tone-accent',
  caution: 'bg-tone-caution-bg text-tone-caution',
  success: 'bg-tone-success-bg text-tone-success',
  danger: 'bg-tone-danger-bg text-tone-danger',
}

export function AdminBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-[6px] px-[9px] py-[5px] text-[11px] font-extrabold tracking-[0.06em] ${BADGE_TONE[tone]}`}
    >
      {children}
    </span>
  )
}

/** 상태 배지. 도메인 상태를 있는 그대로 말한다. */
export function PrometheusStateBadge({ state }: { state: PrometheusState }) {
  const display = PROMETHEUS_STATE_DISPLAY[state]
  return <AdminBadge tone={display.tone}>{display.label}</AdminBadge>
}

/**
 * 서버·서비스의 UP/DOWN 점.
 *
 * `up`이 `null`이면 회색이다. Prometheus에 닿지 못한 동안은 서버가 살았는지 알 수 없고,
 * 그때 빨간 점을 켜면 화면이 장애를 만들어 낸다.
 */
export function UpDot({ up, label }: { up: boolean | null; label: string }) {
  const tone =
    up === null ? 'bg-tone-neutral' : up ? 'bg-tone-success' : 'bg-tone-danger'
  const text = up === null ? '상태 알 수 없음' : up ? '정상' : '중단'
  return (
    <span
      className={`inline-block size-2 shrink-0 rounded-full ${tone}`}
      role="img"
      aria-label={`${label} ${text}`}
    />
  )
}

/** UP/DOWN 배지. 점만으로는 표에서 값을 읽기 어렵다. */
export function UpBadge({ up }: { up: boolean | null }) {
  if (up === null) {
    return <AdminBadge tone="neutral">UNKNOWN</AdminBadge>
  }
  return <AdminBadge tone={up ? 'success' : 'danger'}>{up ? 'UP' : 'DOWN'}</AdminBadge>
}

/**
 * Prometheus가 연결되지 않았을 때 데이터 영역을 채우는 카드.
 *
 * 여기가 공용 `StateCard`를 재사용해야 하는 자리다. 그래서 {@link stateCardKindFor}로
 * UI fallback만 고르고, 카드 본문에는 도메인 상태의 문구와 상태 이름을 함께 남긴다.
 * 그러면 카드 색은 공용 규칙을 따르면서도 운영자는 실제 원인을 읽을 수 있다.
 */
export function DisconnectedStateCard({
  state,
  title,
}: {
  state: DisconnectedState
  title: string
}) {
  const display = PROMETHEUS_STATE_DISPLAY[state]
  return (
    <StateCard
      kind={stateCardKindFor(state)}
      title={title}
      description={display.description}
      meta={state}
    />
  )
}
