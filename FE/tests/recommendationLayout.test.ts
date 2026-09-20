import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * 추천 화면의 배치와 Evidence 표기 (S15P21E102-364).
 *
 * 화면을 import 하면 `@/` alias 때문에 `node --test` 가 읽지 못하므로, 판정식은 같은
 * 형태로 두고 실제 소스는 텍스트로 확인한다 — `recommendationPartialRender.test.ts` 와
 * 같은 방식이다.
 */

function source(path: string): string {
  return readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
}

/**
 * 주석을 뺀 소스.
 *
 * "이 문구를 쓰지 않는다" 류의 판정은 화면에 나가는 코드만 봐야 한다. 무엇을 왜
 * 그만뒀는지 적어 둔 주석까지 세면, 변경 이유를 설명할수록 테스트가 깨진다.
 */
function withoutComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('//'))
    .join('\n')
}

/** `features/matching/api/adapter.ts` 의 판정. */
const EVIDENCE_STATUSES = ['NOT_HELD', 'L0', 'PERSONAL_LEVEL_UNKNOWN']
function toEvidenceStatus(value: string | null | undefined): string | null {
  return EVIDENCE_STATUSES.includes(value as string) ? (value as string) : null
}

test('모르는 evidenceStatus 는 미보유로 떨어지지 않는다', () => {
  assert.equal(toEvidenceStatus('PERSONAL_LEVEL_UNKNOWN'), 'PERSONAL_LEVEL_UNKNOWN')
  assert.equal(toEvidenceStatus('NOT_HELD'), 'NOT_HELD')

  // 계약이 늘어나도 화면이 "보유하지 않았다"고 말하기 시작하면 안 된다.
  assert.equal(toEvidenceStatus('SOMETHING_NEW'), null)
  assert.equal(toEvidenceStatus(null), null)
  assert.equal(toEvidenceStatus(undefined), null)
})

test('adapter 는 계약의 evidenceStatus 를 화면 타입으로 옮긴다', () => {
  const adapter = source('features/matching/api/adapter.ts')
  const view = source('features/matching/model/view.ts')

  assert.match(adapter, /evidenceStatus: toEvidenceStatus\(candidate\.evidenceStatus\)/)
  assert.match(view, /evidenceStatus: NextSkillEvidenceStatus \| null/)
})

test('추천 카드는 미판정을 "분석 전"으로 뭉뚱그리지 않는다', () => {
  const card = source('features/matching/components/NextSkillCard.tsx')

  assert.equal(withoutComments(card).includes('분석 전'), false)
  assert.match(card, /PERSONAL_LEVEL_UNKNOWN: \{\s*label: '내 수준 미판정'/)
  assert.match(card, /NOT_HELD: \{\s*label: '미보유'/)
})

test('PERSONAL_LEVEL_UNKNOWN 을 L0 이나 미보유로 표현하지 않는다', () => {
  const card = source('features/matching/components/NextSkillCard.tsx')

  // 세 상태가 각각 다른 문구를 갖는다. 같은 문구가 두 상태에 걸리면 구분이 사라진다.
  const labels = [...card.matchAll(/label: '([^']+)'/g)].map((match) => match[1])
  assert.equal(labels.length, 3)
  assert.equal(new Set(labels).size, 3)

  // 계약에 없는 값은 아무 상태도 주장하지 않는다.
  assert.match(card, /skill\.evidenceStatus === null/)
})

test('추천 Top3 는 고정 폭 사이드 열이 아니라 공용 3열 규칙을 쓴다', () => {
  const page = withoutComments(source('features/matching/pages/RecommendationPage.tsx'))

  assert.match(page, /className="gj-trio"/)
  // 1순위만 남기고 후순위를 326px 고정 열에 몰아넣던 배치가 빈 공간의 원인이었다.
  assert.equal(page.includes('326px'), false)
  assert.equal(/grid-cols-\[/.test(page), false)
})

test('3열 규칙은 카드 높이를 늘리지 않고 열이 min-content 로 벌어지지 않는다', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
  const trio = css.slice(css.indexOf('.gj-trio {'))

  // stretch 면 짧은 카드가 옆 열 높이까지 늘어난다. 높이는 내용이 정한다.
  assert.match(trio, /align-items: start/)
  // minmax(0, …) 이 없으면 긴 근거 문장이 열을 밀어내 가로 스크롤이 생긴다.
  assert.match(css, /grid-template-columns: minmax\(0, 1\.25fr\) minmax\(0, 1fr\) minmax\(0, 1fr\)/)
})

test('세 카드가 같은 근거 노출 규칙을 쓴다', () => {
  const card = source('features/matching/components/NextSkillCard.tsx')

  // 1순위만 전부 펴고 후순위는 한 줄만 주던 규칙이 카드 높이를 벌려 놓았다.
  assert.equal(card.includes('emphasis ? skill.reasons : skill.reasons.slice(0, 1)'), false)
  assert.match(card, /const leadReasons = skill\.reasons\.slice\(0, 2\)/)
  assert.match(card, /const restReasons = skill\.reasons\.slice\(2\)/)
})

test('부분 분석 배너는 추천 화면에서 면적만 줄이고 경고 색을 유지한다', () => {
  const panel = source('shared/ui/ComputeStatePanel.tsx')
  const page = source('features/matching/pages/RecommendationPage.tsx')

  assert.match(page, /<PartialNotice state=\{data\} compact \/>/)
  // 색과 문구는 그대로다. 줄이는 것은 면적뿐이다.
  assert.match(panel, /compact\s*\?\s*'w-fit rounded-full border border-tone-caution-bg bg-tone-caution-bg/)
})
