import {
  PROMETHEUS_STATE_DISPLAY,
  stateCardKindFor,
} from '@/features/admin/monitoring/model/monitoringState'
import type { DisconnectedState, PrometheusState } from '@/features/admin/monitoring/model/monitoringState'
import { Pill } from '@/shared/ui/Pill'
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

/** 상태 배지. 도메인 상태를 있는 그대로 말한다. */
export function PrometheusStateBadge({ state }: { state: PrometheusState }) {
  const display = PROMETHEUS_STATE_DISPLAY[state]
  return <Pill tone={display.tone}>{display.label}</Pill>
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
    return <Pill tone="neutral">UNKNOWN</Pill>
  }
  return <Pill tone={up ? 'success' : 'danger'}>{up ? 'UP' : 'DOWN'}</Pill>
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
