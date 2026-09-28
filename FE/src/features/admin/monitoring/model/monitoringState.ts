import type { StateKind } from '@/shared/ui/StateCard'
import type { Tone } from '@/shared/ui/Pill'

/**
 * 모니터링 도메인 상태 · 티켓 S15P21E102-210.
 *
 * **도메인 상태와 공용 UI 상태를 같은 개념으로 다루지 않는다.**
 *
 * `shared/ui/StateCard`의 `StateKind`는 "데이터가 어떤 상태인가"를 다섯 색 규칙으로
 * 말하는 공용 어휘이고, 그 파일은 값 목록을 임의로 늘리지 말라고 못 박아 두었다. 여기
 * 있는 `PrometheusState`는 그것과 층이 다르다 — 운영자가 "무엇이 고장났고 누가 고쳐야
 * 하는가"를 알아야 하는, 이 화면만의 사실이다.
 *
 * 그래서 `NOT_CONFIGURED`를 곧바로 `PREPARING`으로 바꾸지 않는다. "이 배포에 Prometheus
 * 주소가 설정되지 않았다"와 "지표가 준비 중이다"는 다른 말이고, 앞의 것은 배포 담당자가
 * env 하나를 채우면 끝나는 일이다. 화면은 그 구분을 `StatusBadge`·`StatusPanel`로 직접
 * 보여준다.
 *
 * {@link stateCardKindFor}는 오직 **공용 `StateCard`를 재사용해야 하는 empty/error
 * 영역에서만** 쓰는 UI fallback이다. 도메인 의미를 바꾸는 변환이 아니라, 그 카드가 가진
 * 세 가지 색 중 무엇을 쓸지 고르는 것이다.
 *
 * 값은 BE 계약(`docs/be/admin-monitoring-api.md`, 티켓 S15P21E102-209)의 enum과 같다.
 * 서버가 주는 문자열을 화면에서 다시 이름 짓지 않는다.
 */
export type PrometheusState = 'CONNECTED' | 'NOT_CONFIGURED' | 'UNREACHABLE' | 'INVALID_RESPONSE'

/** 연결되지 않은 상태만. `CONNECTED`에는 상태 카드를 그리지 않는다. */
export type DisconnectedState = Exclude<PrometheusState, 'CONNECTED'>

/** 지표 범위가 실제로 수집되고 있는지. BE `CoverageState`와 같다. */
export type CoverageState = 'COLLECTED' | 'NOT_COLLECTED'

interface StateDisplay {
  /** 배지에 쓰는 짧은 말 */
  label: string
  /** 무엇이 일어났는지 한 줄 */
  description: string
  tone: Tone
}

/**
 * 상태별 표기. 문구를 여기 모아 두는 이유는 같은 상태가 배지·패널·요약 카드 세 곳에
 * 나타나는데 각각 다른 말로 적히면 운영자가 같은 사실인지 알 수 없기 때문이다.
 */
export const PROMETHEUS_STATE_DISPLAY: Readonly<Record<PrometheusState, StateDisplay>> = {
  CONNECTED: {
    label: '정상',
    description: 'Prometheus가 지표를 수집하고 있습니다.',
    tone: 'success',
  },
  NOT_CONFIGURED: {
    label: '연결 설정 없음',
    description: '이 배포에 Prometheus 주소가 설정되지 않았습니다. 서버 환경 변수를 확인해 주세요.',
    tone: 'neutral',
  },
  UNREACHABLE: {
    label: '연결 실패',
    description: 'Prometheus 주소는 있으나 응답하지 않습니다. 관리자망과 Prometheus 상태를 확인해 주세요.',
    tone: 'danger',
  },
  INVALID_RESPONSE: {
    label: '응답 오류',
    description: 'Prometheus에 연결했으나 응답을 해석할 수 없습니다. 주소와 버전을 확인해 주세요.',
    tone: 'danger',
  },
}

/**
 * 공용 `StateCard` 재사용 시의 UI fallback.
 *
 * 미설정은 아직 갖춰지지 않은 것이므로 `PREPARING`, 도달 실패와 응답 이상은 실제로
 * 잘못된 것이므로 `ERROR`다. 이 함수를 거쳐도 도메인 상태는 그대로 남아 있고, 카드
 * 본문에는 {@link PROMETHEUS_STATE_DISPLAY}의 문구를 함께 보여준다.
 */
export function stateCardKindFor(state: DisconnectedState): StateKind {
  return state === 'NOT_CONFIGURED' ? 'PREPARING' : 'ERROR'
}

/**
 * 상태 점에 쓸 값.
 *
 * `NOT_CONFIGURED`가 `false`가 아닌 이유가 이 함수의 존재 이유다. 주소가 설정되지
 * 않은 것은 Prometheus가 죽은 것이 아니므로 빨간 점을 켜면 안 된다. 반대로
 * `UNREACHABLE`·`INVALID_RESPONSE`는 실제로 응답하지 않는 상태여서 `false`다.
 */
export function monitoringDotState(state: PrometheusState): boolean | null {
  if (state === 'CONNECTED') {
    return true
  }
  return state === 'NOT_CONFIGURED' ? null : false
}
