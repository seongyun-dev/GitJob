/**
 * 공통 응답 봉투. BE `global/response/ApiResponse`·`ErrorResponse`가 원본이다.
 * 계약은 docs/fe/shared-api-contract.md 1-1.
 *
 * 명세의 `meta`(generatedAt·fetchedAt·cached·registryVersion)는 BE 응답에 없으므로
 * 두지 않는다. BE가 추가하면 optional 필드로 복원한다.
 */
export interface ApiSuccess<T> {
  message: string
  data: T
}

export interface ApiFailure {
  code: string
  message: string
}

/**
 * 페이징 응답. BE `analysis/controller/dto/PageResponse`와 같은 모양이다(계약 1-2).
 *
 * GitHub이 전체 개수를 주지 않아 총 페이지 수를 만들 수 없고,
 * 받은 항목 수가 페이지 크기와 같은지로 `hasNext`만 알린다. 명세의
 * `page`(0-base)·`size`·`totalCount`와 다르므로 BE 쪽을 따른다.
 */
export interface PageResponse<T> {
  items: T[]
  /** 1-base. BE 기본값 1 */
  page: number
  /** BE 기본값 30(브랜치 100), 최대 100 */
  perPage: number
  hasNext: boolean
}

export interface PageParams {
  page?: number
  perPage?: number
}

/**
 * 총 개수를 주는 페이징 응답 · 티켓 S15P21E102-281.
 *
 * `PageResponse`와 **일부러 다른 타입이다.** 저 타입은 저장소 목록이 쓰는 모양이고,
 * GitHub이 전체 개수를 주지 않아 `hasNext`만 알린다. 반면 공고·수요 집계처럼 BE가
 * 자기 DB에서 세는 목록은 명세 v0.1이 `page`·`size`·`totalCount`로 정했고, 화면도
 * "87건 중 12건 표시" 같은 문구에 총 개수를 쓴다.
 *
 * 둘을 하나로 합치면 한쪽은 항상 거짓말을 한다 — 저장소 목록에 `totalCount`를 두면
 * 채울 값이 없고, 공고 목록에서 `totalCount`를 빼면 화면이 개수를 셀 수 없다.
 *
 * `page`는 명세대로 0-base다(`PageResponse.page`는 1-base). 두 규칙이 공존하는 것은
 * 계약 문서 1-2의 미결 항목이며, BE 구현 시 한쪽으로 맞춘다.
 */
export interface CountedPage<T> {
  items: T[]
  /** 0-base. 명세 v0.1 */
  page: number
  size: number
  totalCount: number
}

/** `CountedPage`를 쓰는 조회의 페이징 인자. */
export interface CountedPageParams {
  page?: number
  size?: number
}
