import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * PARTIAL 추천은 후보를 감추지 않는다 (S15P21E102-354).
 *
 * C 가 후보를 냈는데 Evidence coverage 가 불완전하면 snapshot 상태는 `PARTIAL` 이
 * 되고, BE 는 그것을 `dataStatus=PARTIAL` 로 옮긴다. 이때 화면이 `READY` 만 보고
 * 본문을 닫으면 사용자는 존재하는 Top3 를 보지 못한 채 빈 화면을 받는다 -- 이
 * 이슈가 고친 증상이 정확히 그것이므로 회귀를 여기서 막는다.
 *
 * 화면을 import 하면 `@/` alias 때문에 `node --test` 가 읽지 못하므로, 판정식은 같은
 * 형태로 두고 실제 소스는 텍스트로 확인한다.
 */

function source(path: string): string {
  return readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
}

type State = { dataStatus: string; statusReason?: string }

/** `shared/api/computeState.ts` 의 판정. */
function hasComputedValue(state: State | undefined): boolean {
  return state !== undefined && (state.dataStatus === 'READY' || state.dataStatus === 'PARTIAL')
}

test('PARTIAL 추천 응답은 본문을 연다', () => {
  assert.equal(hasComputedValue({ dataStatus: 'PARTIAL', statusReason: 'PARTIAL_ANALYSIS' }), true)
})

test('INSUFFICIENT_EVIDENCE 는 여전히 본문을 열지 않는다', () => {
  const state = { dataStatus: 'INSUFFICIENT_DATA', statusReason: 'INSUFFICIENT_EVIDENCE' }
  assert.equal(hasComputedValue(state), false)
})

test('추천 화면은 READY 를 직접 비교하지 않고 공용 판정을 쓴다', () => {
  const page = source('features/matching/pages/RecommendationPage.tsx')

  assert.match(page, /const ready = hasComputedValue\(data\)/)
  assert.equal(page.includes("dataStatus === 'READY'"), false)
})

test('추천 화면은 부분 분석 배너를 후보와 함께 띄운다', () => {
  const page = source('features/matching/pages/RecommendationPage.tsx')

  // 배너는 본문을 가리지 않고 위에 한 줄로만 붙는다. 면적은 화면이 정한다(`compact`).
  assert.match(page, /<PartialNotice state=\{data\}/)
})

test('What-if 는 추천 상태와 무관하게 후보에서 기본 선택을 만든다', () => {
  const page = source('features/matching/pages/WhatIfPage.tsx')

  assert.match(page, /candidates\.find\(\([\s\S]{0,80}\) => [\s\S]{0,80}\) \?\? candidates\[0\]/)
  assert.equal(page.includes("dataStatus === 'READY'"), false)
})

test('PARTIAL 은 오류 문구가 아니라 부분 안내로만 설명된다', () => {
  const panel = source('shared/ui/ComputeStatePanel.tsx')

  assert.match(panel, /state\.dataStatus !== 'PARTIAL'/)
  assert.match(panel, /PARTIAL: \{[\s\S]{0,200}kind: 'PARTIAL'/)
})
