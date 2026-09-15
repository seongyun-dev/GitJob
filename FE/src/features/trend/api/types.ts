import type { DataStatus } from '@/shared/types/domain'

/**
 * 기술 트렌드 조회 응답 타입 · 티켓 S15P21E102-281.
 *
 * BE 미구현 상태에서 먼저 고정하는 계약이다. 근거는 B조 API 명세서 v0.1.
 *
 *   - B-FN-020 기술 트렌드 개요 조회   `GET /trends`                    (화면 12)
 *   - B-FN-020 출처별 기술 추세 조회   `GET /technologies/{techId}/trends` (화면 13)
 *   - B-FN-021 후보 기술 교차 비교     `GET /trends/compare`
 *
 * ## 이 계열의 확정 규칙 두 가지
 *
 * **1. 출처를 합치지 않는다.** 명세 확정 범위가 "채용·GitHub·Stack Overflow를 서로
 * 다른 단위로 분리하고 종합 점수를 제외한다"고 정했다. 그래서 응답에 종합 점수 필드가
 * 없고, 출처마다 `unit`·`axisLabel`을 따로 받는다. 화면도 한 축에 겹쳐 그리지 않는다.
 * 비중이 `share: string`인 것이 그 결과다 — 출처마다 분모가 달라 수 하나로 비교할 수
 * 없고, 숫자로 두면 다음 사람이 비교하는 화면을 만들게 된다.
 *
 * **2. 값이 없으면 비운다.** 준비 중·표본 부족·미지원은 오류가 아니라 200 + `status`로
 * 온다(명세 §2-3). 상태가 `READY`가 아니면 `points`는 빈 배열이고 `latestText`는 null이다.
 * 0으로 채우면 화면이 "0건"이라는 없는 사실을 말한다.
 *
 * ## 성장 단계(S6)는 여기 없다
 *
 * `src/mocks/fixtures/growthStage.ts`가 그리는 성장 단계 카드에 대응하는 엔드포인트가
 * **명세 v0.1에 없다.** 세 축을 묶어 단계를 정하는 규칙은 제품 결정이고 아직 없다.
 * 계약을 지어내지 않고 fixture로 남겨 둔다 — 자세한 것은 `docs/fe/shared-api-contract.md`
 * 미결 항목에 적었다.
 */

/** 트렌드 출처. 셋을 합치지 않는다. */
export const TREND_SOURCE_IDS = ['JOB', 'GITHUB', 'STACK_OVERFLOW'] as const
export type TrendSourceId = (typeof TREND_SOURCE_IDS)[number]

export const TREND_DIRECTIONS = ['UP', 'DOWN'] as const
export type TrendDirection = (typeof TREND_DIRECTIONS)[number]

/** 출처별 순위 한 줄 · 화면 12. */
export interface TrendRankRow {
  rank: number
  /**
   * Registry `tech_id`. 상세 화면 링크가 이 값을 쓴다.
   *
   * 표시 이름에서 만들어내지 않는다. `Apache Kafka` → `apache-kafka`가 되는데 실제
   * id는 `kafka`라 상세 화면이 기술을 못 찾는다. 표시 이름과 식별자는 다른 값이다.
   */
  techId: string
  techName: string
  /** 비중 표기. 출처마다 분모가 달라 문자열이다(머리말 1번). */
  share: string
  /** 변화 표기. `↑ 7.1%`. */
  delta: string
  direction: TrendDirection
}

/** 출처 하나 · 화면 12. */
export interface TrendSource {
  id: TrendSourceId
  label: string
  /** 무엇을 세는지. 출처 간 비교를 막는 이름이라 반드시 표시한다. */
  unit: string
  status: DataStatus
  /** 측정 범위와 기간. */
  basis: string
  /**
   * 이 출처의 지원 범위 한계. 없으면 null.
   *
   * GitHub이 이 필드를 쓴다 — Innovation Graph는 **언어 지표만** 지원하고 Kafka 같은
   * 라이브러리는 `NOT_SUPPORTED`다. 이것을 상태가 아니라 배지로 그리면 화면이
   * "데이터가 있는데 일부만"이라고 말하게 된다.
   */
  scopeNote: string | null
  rows: TrendRankRow[]
  footnote: string
}

export interface TrendOverview {
  dataStatus: DataStatus
  sources: TrendSource[]
}

/** 기간별 값 한 점 · 화면 13. */
export interface TrendPoint {
  /** 표시용 기간 라벨. `9월`. 언어 지표는 월이 아니라 분기다. */
  period: string
  value: number
}

/** 출처별 시계열 · 화면 13. */
export interface TrendSeries {
  sourceId: TrendSourceId
  label: string
  status: DataStatus
  /** Y축이 무엇인지. 출처마다 독립이라 한 축에 겹쳐 그리지 않는다. */
  axisLabel: string
  /** 최근 값 표기. 상태가 READY가 아니면 null. */
  latestText: string | null
  /** 전기 대비 변화 표기. 상태가 READY가 아니면 null. */
  deltaText: string | null
  /** 상태가 READY가 아니면 빈 배열. 값을 지어내지 않는다. */
  points: TrendPoint[]
  note: string
}

/** 기술 하나의 출처별 추세 · `GET /technologies/{techId}/trends`. */
export interface TechnologyTrend {
  techId: string
  techName: string
  dataStatus: DataStatus
  series: TrendSeries[]
}

/** 후보 기술 교차 비교 · `GET /trends/compare`. 같은 출처끼리만 나란히 놓는다. */
export interface TrendComparison {
  dataStatus: DataStatus
  sourceId: TrendSourceId
  axisLabel: string
  technologies: TechnologyTrend[]
}
