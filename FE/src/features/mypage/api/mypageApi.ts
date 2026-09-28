import {
  ANALYSIS_HISTORY_STATUSES,
  type AnalysisHistory,
  type AnalysisHistoryItem,
  type AnalysisHistoryParams,
} from '@/features/mypage/api/types'
import { get } from '@/shared/api/client'
import { readers } from '@/shared/api/parse'
import { toQuery } from '@/shared/api/query'

/**
 * 마이페이지 HTTP 계층 · 티켓 S15P21E102-281.
 *
 * 이 파일만 경로 문자열을 안다. 엔드포인트는 BE에 아직 없다(명세 상태 `시작 전`).
 *
 * 파서를 별도 파일로 두지 않은 이유는 타입이 하나뿐이어서다. 매칭·트렌드는
 * `parseMatching.ts`·`parseTrend.ts`로 나눴는데 그쪽은 파싱 함수가 각각 열 개를 넘는다.
 */

const r = readers('mypage')

function parseStringArray(source: Record<string, unknown>, field: string, at: string): string[] {
  return r.array(source, field, at).map((item, index) => {
    if (typeof item !== 'string') {
      throw r.fail(`${at}.${field}[${index}]가 문자열이 아닙니다`)
    }
    return item
  })
}

function parseHistoryItem(value: unknown, at: string): AnalysisHistoryItem {
  const source = r.item(value, at)
  return {
    analysisId: r.string(source, 'analysisId', at),
    analyzedAt: r.string(source, 'analyzedAt', at),
    repositories: parseStringArray(source, 'repositories', at),
    resultText: r.string(source, 'resultText', at),
    status: r.enum(source, 'status', at, ANALYSIS_HISTORY_STATUSES),
  }
}

function parseAnalysisHistory(value: unknown): AnalysisHistory {
  const at = 'analysisHistory'
  const source = r.root(value, at)
  return {
    items: r.array(source, 'items', at).map((item, i) => parseHistoryItem(item, `${at}.items[${i}]`)),
    page: r.number(source, 'page', at),
    size: r.number(source, 'size', at),
    totalCount: r.number(source, 'totalCount', at),
  }
}

/** 분석 이력 목록 · 명세 B-FN-009 (화면 14). */
export async function fetchAnalysisHistory(
  params: AnalysisHistoryParams = {},
): Promise<AnalysisHistory> {
  const query = toQuery({ page: params.page, size: params.size })
  return parseAnalysisHistory(await get<unknown>(`/me/analyses${query}`))
}
