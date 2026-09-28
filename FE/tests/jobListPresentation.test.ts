import assert from 'node:assert/strict'
import test from 'node:test'

import {
  JOBS_PER_PAGE,
  formatJobPagePosition,
} from '../src/features/matching/model/jobListPresentation.ts'

test('공고 목록은 한 페이지에 10건만 요청한다', () => {
  assert.equal(JOBS_PER_PAGE, 10)
})

test('총 공고 수와 페이지 크기로 현재 페이지와 전체 페이지를 함께 표시한다', () => {
  assert.equal(formatJobPagePosition(1, 320), '1 / 32')
  assert.equal(formatJobPagePosition(32, 320), '32 / 32')
})

test('빈 결과와 총계 미집계 상태를 과장하지 않는다', () => {
  assert.equal(formatJobPagePosition(1, 0), '1 / 1')
  assert.equal(formatJobPagePosition(2, null), '2쪽')
})
