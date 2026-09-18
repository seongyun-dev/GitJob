import assert from 'node:assert/strict'
import test from 'node:test'

import {
  evidenceSummaryText,
  missingEvidenceGuide,
} from '../src/features/evidence/model/summaryPresentation.ts'

test('요약의 한글 날짜 띄어쓰기를 자연스럽게 정리한다', () => {
  assert.equal(
    evidenceSummaryText('2026 년 4 월부터 9 월까지 꾸준히 사용했습니다.'),
    '2026년 4월부터 9월까지 꾸준히 사용했습니다.',
  )
})

test('내부 규칙 코드가 섞인 요약은 그대로 노출하지 않는다', () => {
  assert.equal(
    evidenceSummaryText('ASYNC_FUNCTION_DECLARATION 규칙을 충족했습니다.'),
    '확인된 파일과 사용 위치를 아래 근거 목록에서 확인해 보세요.',
  )
})

test('부족한 규칙의 원문 대신 사용자가 할 수 있는 행동을 안내한다', () => {
  assert.equal(
    missingEvidenceGuide('TRY_FINALLY, ASYNC_FUNCTION_DECLARATION'),
    '아직 확인되지 않은 사용 형태가 있어요. 아래 근거 목록에서 확인된 범위를 살펴보세요.',
  )
  assert.equal(missingEvidenceGuide(null), null)
})
