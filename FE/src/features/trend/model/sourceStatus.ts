import type { DataStatus } from '@/shared/types/domain'

/**
 * 서버 판정 보존과 부분 실패 판정 · 티켓 S15P21E102-329.
 *
 * <h2>왜 화면이 상태를 새로 만들면 안 되는가</h2>
 *
 * 준비 중이나 표본 부족은 오류가 아니라 **HTTP 200 + `dataStatus`** 로 온다
 * (`shared/types/domain`의 `DATA_STATUSES` 주석, 명세 §2-3). 그래서 요청이 성공했다는
 * 사실만으로는 그 원천이 정상이라고 말할 수 없다. 200 안의 `FAILED` 를 화면이
 * `NO_DATA` 로 바꿔 적으면 장애가 "아직 집계된 기간이 없습니다" 로 읽힌다.
 *
 * point 가 하나도 없는 원천이 정확히 그 경우다. 값이 없다는 것과 어째서 없는지는
 * 다른 정보이고, 후자는 `dataStatus` 로 따로 온다. 이 모듈은 그것을 버리지 않는다.
 *
 * <h2>순수 함수로 둔 이유</h2>
 *
 * 타입만 import 한다. `node --test` 는 `@/` alias 를 해석하지 못하므로 런타임 import 가
 * 있는 모듈은 테스트에서 불러올 수 없다. 이 판정은 화면 회귀가 실제로 발생한 곳이라
 * 테스트로 고정할 값이 있다.
 */

/**
 * 한 원천의 상태를 하나로 줄일 때의 우선순위. 앞이 더 심각하다.
 *
 * 카드는 원천당 배지 하나만 보여주므로 여러 기술의 판정을 하나로 줄여야 한다. 그때
 * **축소하지 않는 쪽**을 택한다 — 열 기술 중 하나가 `FAILED` 인데 카드가 `NO_DATA` 라고
 * 말하면 그 하나는 영구히 보이지 않는다. 반대로 과하게 말하면 사용자가 다시 시도하고,
 * 그것은 복구 가능한 오해다.
 *
 * `NOT_SUPPORTED` 가 `NO_DATA` 보다 약한 이유: 미지원은 그 기술 하나의 사실이고, 다른
 * 기술이 "데이터가 없다"고 말하는 쪽이 원천 전체를 더 정확히 설명한다.
 */
const SEVERITY: readonly DataStatus[] = [
  'FAILED',
  'PREPARING',
  'INSUFFICIENT_DATA',
  'PARTIAL',
  'NO_DATA',
  'NOT_SUPPORTED',
  'READY',
]

/** 판정별로 사용자에게 보일 이유. 실패를 "데이터가 없다"로 설명하지 않는다. */
const SCOPE_NOTE: Readonly<Record<DataStatus, string>> = {
  READY: '이 출처에는 아직 집계된 기간이 없습니다.',
  PREPARING: '이 출처의 데이터를 준비하고 있습니다. 집계가 끝나면 표시됩니다.',
  PARTIAL: '이 출처는 일부 기간만 집계돼 있어 아직 표시할 기간이 없습니다.',
  INSUFFICIENT_DATA: '이 출처에는 비교할 기간이 아직 부족합니다.',
  NOT_SUPPORTED: '이 출처는 비교 대상 기술을 지원하지 않습니다.',
  NO_DATA: '이 출처에는 아직 집계된 기간이 없습니다.',
  FAILED: '이 출처의 데이터를 불러오지 못했습니다.',
}

/**
 * 여러 기술의 판정 중 가장 심각한 것. 하나도 없으면 `null`.
 *
 * "하나도 없음"과 "모두 정상"을 구별하기 위해 `null` 을 쓴다. 전자는 그 원천이 어느
 * 상답에도 없었다는 뜻이고, 그때만 요청 수준 실패를 따져야 한다.
 */
export function mostSevereStatus(statuses: readonly DataStatus[]): DataStatus | null {
  return SEVERITY.find((candidate) => statuses.includes(candidate)) ?? null
}

export interface EmptySourceJudgement {
  status: DataStatus
  scopeNote: string
}

/**
 * point 가 없는 원천의 상태를 정한다.
 *
 * `statuses` 는 그 원천에 대해 서버가 기술별로 내린 판정이다. 비어 있다는 것은 어느
 * 상답에도 그 원천이 없었다는 뜻이고, 그때만 요청 수준 실패(`requestFailed`)로
 * 판정한다 — 서버가 말한 것이 있으면 그것이 먼저다.
 */
export function resolveEmptySourceStatus(
  statuses: readonly DataStatus[],
  requestFailed: boolean,
): EmptySourceJudgement {
  const status = mostSevereStatus(statuses) ?? (requestFailed ? 'FAILED' : 'NO_DATA')
  return { status, scopeNote: SCOPE_NOTE[status] }
}

export interface TrendLoadSummary {
  kind: 'PARTIAL' | 'FAILED'
  loaded: number
  total: number
  title: string
  description: string
}

/**
 * 기술별 조회의 부분 실패를 화면에 드러낼 값 · 티켓 S15P21E102-329 D2.
 *
 * 개요 화면은 기술당 상세 조회를 하나씩, 최대 `COMPARE_LIMIT` 개 병렬로 던진다. 한
 * 기술이 실패해도 나머지로 순위를 만들 수 있고 그 **부분 성공 자체는 허용한다** —
 * 하나 때문에 화면 전체를 비우면 볼 수 있었던 아홉 개도 사라진다.
 *
 * 허용하지 않는 것은 그 사실을 숨기는 것이다. 9개로 만든 순위가 10개 완전 성공처럼
 * 보이면 사용자는 빠진 기술을 알 방법이 없다. 그래서 성공 수를 문구에 넣는다.
 *
 * <h2>`loaded` 는 오류 플래그가 아니라 순위에 실제로 들어간 기술 수다</h2>
 *
 * 화면이 세어 넘기는 값은 `query.data` 가 있는 상답의 수다. 오류가 난 요청 수를 대신
 * 쓰면 안 된다 — 조회 훅은 `retry: false` 에 `staleTime` 이 5분이라, 캐시를 들고 있던
 * 기술이 재조회에서 실패하면 `isError` 가 켜진 채로도 값은 그대로 순위에 남는다.
 * 그때 "10개 중 9개만 조회에 성공했고 빠진 기술이 있다" 고 적으면, 열 개가 다 보이는
 * 화면에 없는 실패를 지어내는 것이 된다. 실패를 숨기는 것과 같은 종류의 거짓이다.
 *
 * 알릴 것이 없으면 `null` 이다. 조회 대상이 없을 때도 `null` 이다 — 빠진 기술이 없는
 * 것과 시도한 기술이 없는 것은 둘 다 알릴 내용이 아니다.
 */
export function summarizeTrendLoad(total: number, loaded: number): TrendLoadSummary | null {
  if (total === 0 || loaded >= total) {
    return null
  }
  if (loaded === 0) {
    return {
      kind: 'FAILED',
      loaded,
      total,
      title: '기술 트렌드를 불러오지 못했어요',
      description: '잠시 후 다시 시도해 주세요.',
    }
  }
  return {
    kind: 'PARTIAL',
    loaded,
    total,
    title: '일부 기술을 불러오지 못했어요',
    description: `기술 ${total}개 중 ${loaded}개만 조회에 성공했습니다. 아래 순위에는 불러오지 못한 기술이 빠져 있습니다.`,
  }
}
