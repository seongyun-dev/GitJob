import assert from 'node:assert/strict'
import test from 'node:test'

/**
 * 공고 목록 렌더 게이트 (S15P21E102-324).
 *
 * `JobMatchPage` 가 목록을 여는 조건을 그대로 옮겨 고정한다. 화면을 import 하면
 * `@/` alias 때문에 `node --test` 가 읽지 못하므로, 판정식만 같은 형태로 둔다.
 *
 * 고정하는 사실은 하나다 -- BE 는 `INSUFFICIENT_DATA`·`INSUFFICIENT_EVIDENCE` 에서도
 * items 를 싣는다(`JobMatchResponse.of`). 그 상태에서 목록을 막으면 수집된 공고가
 * 있는데도 안내 문구만 남는다.
 */

type State = { dataStatus: string; items: unknown[] }

/** `shared/api/computeState.ts` 의 판정. */
function hasComputedValue(state: State | undefined): boolean {
  return state !== undefined && (state.dataStatus === 'READY' || state.dataStatus === 'PARTIAL')
}

/** `JobMatchPage` 가 목록을 여는 조건. */
function opensJobList(data: State | undefined): boolean {
  const hasJobItems = data !== undefined && Array.isArray(data.items) && data.items.length > 0
  return (hasComputedValue(data) || hasJobItems) && data !== undefined
}

/** 통계는 계산 상태를 그대로 따른다. 표본이 부족하면 비율을 보여주지 않는다. */
function opensStats(data: State | undefined): boolean {
  return hasComputedValue(data)
}

const oneItem = [{ id: 'job-1' }]

test('PARTIAL + items 는 기존대로 목록과 통계를 모두 연다', () => {
  const data = { dataStatus: 'PARTIAL', items: oneItem }
  assert.equal(opensJobList(data), true)
  assert.equal(opensStats(data), true)
})

test('READY + items 는 기존대로 목록과 통계를 모두 연다', () => {
  const data = { dataStatus: 'READY', items: oneItem }
  assert.equal(opensJobList(data), true)
  assert.equal(opensStats(data), true)
})

test('INSUFFICIENT_DATA + items 는 목록을 연다', () => {
  const data = { dataStatus: 'INSUFFICIENT_DATA', items: oneItem }
  assert.equal(opensJobList(data), true)
})

test('INSUFFICIENT_EVIDENCE + items 는 목록을 연다', () => {
  const data = { dataStatus: 'INSUFFICIENT_EVIDENCE', items: oneItem }
  assert.equal(opensJobList(data), true)
})

test('INSUFFICIENT 상태에서 통계는 열지 않는다', () => {
  for (const dataStatus of ['INSUFFICIENT_DATA', 'INSUFFICIENT_EVIDENCE']) {
    assert.equal(opensStats({ dataStatus, items: oneItem }), false)
  }
})

test('READY + 0건은 여전히 열려 EMPTY 카드가 자리를 채운다', () => {
  assert.equal(opensJobList({ dataStatus: 'READY', items: [] }), true)
})

test('INSUFFICIENT + 0건은 목록을 열지 않는다 -- 안내 카드만 남는다', () => {
  assert.equal(opensJobList({ dataStatus: 'INSUFFICIENT_DATA', items: [] }), false)
})

test('응답이 없으면 아무것도 열지 않는다', () => {
  assert.equal(opensJobList(undefined), false)
  assert.equal(opensStats(undefined), false)
})
