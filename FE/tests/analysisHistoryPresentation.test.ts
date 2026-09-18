import assert from 'node:assert/strict'
import test from 'node:test'

import { newestAnalysisFirst } from '../src/features/mypage/model/analysisHistoryPresentation.ts'
import type { AnalysisHistoryItem } from '../src/features/mypage/api/types.ts'

function historyItem(analysisId: string, analyzedAt: string): AnalysisHistoryItem {
  return {
    analysisId,
    analyzedAt,
    repositories: ['team/service'],
    resultText: '분석 완료',
    status: 'SUCCEEDED',
  }
}

test('완료 시각을 기준으로 최신 분석부터 정렬한다', () => {
  const input = [
    historyItem('requested-later', '2026-09-18T10:51:00+09:00'),
    historyItem('completed-latest', '2026-09-18T10:56:00+09:00'),
    historyItem('completed-middle', '2026-09-18T10:55:00+09:00'),
  ]

  assert.deepEqual(
    newestAnalysisFirst(input).map((item) => item.analysisId),
    ['completed-latest', 'completed-middle', 'requested-later'],
  )
})

test('정렬 과정에서 API 응답 배열을 변경하지 않는다', () => {
  const input = [
    historyItem('older', '2026-09-18T10:51:00+09:00'),
    historyItem('newer', '2026-09-18T10:56:00+09:00'),
  ]

  newestAnalysisFirst(input)

  assert.deepEqual(input.map((item) => item.analysisId), ['older', 'newer'])
})

test('시각을 해석할 수 없는 이력은 정상 이력 뒤에 안정적으로 둔다', () => {
  const input = [
    historyItem('invalid-first', 'not-a-date'),
    historyItem('valid', '2026-09-18T10:56:00+09:00'),
    historyItem('invalid-second', ''),
  ]

  assert.deepEqual(
    newestAnalysisFirst(input).map((item) => item.analysisId),
    ['valid', 'invalid-first', 'invalid-second'],
  )
})
