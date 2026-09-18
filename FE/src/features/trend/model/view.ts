import type { DataStatus } from '@/shared/types/domain'

/**
 * Trend 화면이 그리는 값의 타입 (S15P21E102-279).
 *
 * `src/mocks/types.ts`에 있던 것을 여기로 옮겼다. `features/`가 `@/mocks`를 import하지
 * 않는 것이 규칙이고, 그래야 운영 빌드에 fixture가 섞이지 않는다.
 *
 * **출처를 하나로 합치는 필드를 두지 않는다.** 세 출처는 세는 대상과 분모가 달라
 * (주간 활동 저장소 · 월별 commit 관측 · 월별 공고 요구) 한 축에 겹쳐 그릴 수 없다.
 * 합성 점수를 담을 자리가 없으면 화면이 그것을 만들 수도 없다.
 */

/** 출처. BE 응답의 `sourceId`와 같은 값이다. */
export type TrendSourceId = 'GITHUB_WEEKLY' | 'GITHUB_ARCHIVE' | 'JOB'

/** 출처별 순위 한 줄 · 화면 12. */
export interface TrendRankRow {
  rank: number
  /**
   * Registry `tech_id`. 상세 화면 링크가 이 값을 쓴다.
   *
   * 표시 이름에서 만들어내지 않는다. `Apache Kafka` → `apache-kafka`가 되는데 실제
   * id는 `kafka`라 상세 화면이 기술을 못 찾는다.
   */
  techId: string
  techName: string
  /**
   * 순위에 올라도 상태는 따라온다 (티켓 -327). 순위는 값이 있느냐로 가르고,
   * 근거가 얼마나 두터운지는 이 필드가 말한다 — 카드가 행마다 이것을 표시한다.
   */
  dataStatus: DataStatus
  statusReason: string
  /** Raw observed value; strings are presentation only and must not drive bars. */
  observedValue: number
  /** 비중 표기. 출처마다 분모가 달라 문자열로 둔다. 값이 없으면 `—`. */
  share: string
  /** 변화 표기. 값이 없으면 `—`. 0으로 채우지 않는다. */
  delta: string
  direction: 'UP' | 'DOWN' | null
}

export interface TrendUnobservedRow {
  techId: string
  techName: string
  dataStatus: DataStatus
  statusReason: string
}

/** 출처 하나 · 화면 12. */
export interface TrendSourceView {
  id: TrendSourceId
  label: string
  /** 무엇을 세는지. 출처 간 비교를 막는 이름이라 반드시 표시한다. */
  unit: string
  status: DataStatus
  /** 측정 범위와 기간. */
  basis: string
  /** 이 출처의 지원 범위 한계. 없으면 `null`. */
  scopeNote: string | null
  /** Maximum among actual ranked observations in this source only. */
  maximumObservedValue: number | null
  rows: TrendRankRow[]
  /**
   * 값이 없는 행만 순위가 없다 (티켓 -327). 표본이 엉은 것은 이제 여기로 오지 않는다 —
   * 측정하지 못한 것과 얇은 근거로 측정한 것은 다른 사실이다.
   */
  unobservedRows: TrendUnobservedRow[]
  footnote: string
}

/** 기간별 값 한 점 · 화면 13. */
export interface TrendPointView {
  period: string
  /** 미집계 기간은 `null`이다. 0으로 채우면 "그 기간에는 없었다"가 된다. */
  value: number | null
}

/** 출처별 시계열 · 화면 13. */
export interface TrendSeriesView {
  sourceId: TrendSourceId
  label: string
  status: DataStatus
  /** Y축이 무엇인지. 출처마다 독립이라 한 축에 겹쳐 그리지 않는다. */
  axisLabel: string
  /** 최근 값 표기. 값이 없으면 `null`. */
  latestText: string | null
  /** 전기 대비 변화 표기. 값이 없으면 `null`. */
  deltaText: string | null
  /** 값이 없으면 빈 배열. 값을 지어내지 않는다. */
  points: TrendPointView[]
  note: string
}
