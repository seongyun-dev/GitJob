import type { AnalysisHistoryItem } from '@/features/mypage/api/types'

/**
 * 화면에 표시하는 분석 완료 시각을 기준으로 최신 항목부터 정렬한다.
 *
 * 서버의 페이지 순서는 요청 시각 기준일 수 있지만 사용자가 보는 `analyzedAt`은 완료
 * 시각이다. 둘이 어긋나면 최근 분석 카드와 이력 첫 줄이 더 오래된 결과를 가리킨다.
 * 응답 배열은 React Query 캐시에 들어 있으므로 복사한 뒤 정렬한다.
 */
export function newestAnalysisFirst(
  items: readonly AnalysisHistoryItem[],
): AnalysisHistoryItem[] {
  return items
    .map((item, index) => ({ item, index, timestamp: Date.parse(item.analyzedAt) }))
    .sort((a, b) => {
      const aValid = Number.isFinite(a.timestamp)
      const bValid = Number.isFinite(b.timestamp)
      if (aValid && bValid) {
        return b.timestamp - a.timestamp || a.index - b.index
      }
      if (aValid) return -1
      if (bValid) return 1
      return a.index - b.index
    })
    .map(({ item }) => item)
}
