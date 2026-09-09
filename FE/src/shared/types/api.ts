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
