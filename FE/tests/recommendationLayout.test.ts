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

test('추천 카드는 필수 공고를 우선하고 우대 공고를 별도로 표시한다', () => {
  const summary = withoutComments(source('features/matching/components/ConditionImpactSummary.tsx'))

  assert.match(summary, />필수 공고</)
  assert.match(summary, /\{requiredCount\.toLocaleString\('ko-KR'\)\}건/)
  assert.match(summary, /우대 공고 \{preferredCount\.toLocaleString\('ko-KR'\)\}건/)
  assert.equal(summary.includes('affectedCount'), false)
  assert.equal(summary.includes('새로 맞'), false)
  assert.equal(summary.includes('다른 조건은 별도 확인'), false)
})

test('What-if 후보 선택칸도 합집합 크기를 주 수치로 다시 내세우지 않는다', () => {
  const page = withoutComments(source('features/matching/pages/WhatIfPage.tsx'))

  assert.match(page, /필수 \{candidate\.requiredImpactCount\?\.toLocaleString\('ko-KR'\)\}건/)
  assert.match(page, /우대 \{candidate\.preferredImpactCount\?\.toLocaleString\('ko-KR'\)\}건/)
  assert.equal(page.includes('formatImpactIncrease(candidate.affectedJobCount)'), false)
})

test('What-if의 개인 수준 미판정은 미보유와 구분한다', () => {
  const page = withoutComments(source('features/matching/pages/WhatIfPage.tsx'))

  assert.match(page, /PERSONAL_LEVEL_UNKNOWN: '내 수준 미판정'/)
  assert.match(page, /NOT_HELD: '미보유'/)
  assert.equal(page.includes('현재 근거 없음'), false)
})

test('관련 공고 화면의 긴 추천 이유도 접혀 있다', () => {
  const page = withoutComments(source('features/matching/pages/WhatIfPage.tsx'))

  assert.match(page, /<ReasonsDisclosure reasons=\{selected\.reasons\} \/>/)
  // 표기를 그 자리에 다시 적으면 두 화면이 또 갈린다.
  assert.equal(page.includes('<details'), false)
})

/*
 * 접힘 표시는 브라우저 기본값이 아니라 서비스 것이다 · 티켓 S15P21E102-377.
 *
 * 기본 `summary` 는 검은 삼각형과 검은 outline 을 그려서, 닫힌 상태의 "추천 이유"
 * 만 남의 화면처럼 보였다.
 */

test('추천 이유 토글은 기본 marker 를 쓰지 않고 초점 표시는 서비스 링이다', () => {
  const page = withoutComments(source('shared/ui/ReasonsDisclosure.tsx'))

  // 기본 삼각형을 끄고 같은 자리에 우리 글리프를 둔다.
  assert.match(page, /list-none/)
  assert.match(page, /\[&::-webkit-details-marker\]:hidden/)
  assert.match(page, /group-open:rotate-90/)
  // 초점 표시를 지우지 않는다. 지우면 키보드 사용자가 현재 위치를 잃는다.
  assert.match(page, /gj-focus-ring/)
  assert.equal(page.includes('outline-none'), false)
})

test('gj-focus-ring 은 링 값을 복제하지 않고 기존 선언을 함께 쓴다', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
  const rule = css.slice(
    css.indexOf('.gj-clickable:focus-visible'),
    css.indexOf('.gj-clickable:focus-visible') + 400,
  )

  // 같은 선언 블록 안에 있어야 링 색이 바뀔 때 한 곳만 고친다.
  assert.match(rule, /\.gj-focus-ring:focus-visible/)
  assert.match(rule, /outline: 3px solid color-mix\(in srgb, var\(--color-brand-400\) 38%, transparent\)/)
})

test('관련 공고 2열도 카드 높이를 목록 높이에 맞추지 않는다', () => {
  const page = withoutComments(source('features/matching/pages/WhatIfPage.tsx'))

  /*
   * `gj-trio` 가 추천 화면에서 세운 규칙과 같다 — 높이는 내용이 정한다.
   * stretch 면 공고가 수십 건일 때 왼쪽 카드가 그 높이까지 늘어나 아래가 빈 면이 된다.
   */
  assert.match(page, /className="grid grid-cols-1 items-start gap-4 lg:grid-cols-\[571px_minmax\(0,1fr\)\]"/)
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

test('세 카드의 긴 추천 이유는 기본적으로 접혀 있다', () => {
  const card = withoutComments(source('features/matching/components/NextSkillCard.tsx'))

  assert.match(card, /<ReasonsDisclosure reasons=\{skill\.reasons\} \/>/)
  assert.equal(card.includes('<details'), false)
  assert.equal(card.includes('leadReasons'), false)
  assert.equal(card.includes('restReasons'), false)
})

/*
 * 같은 흐름의 두 화면이 같은 토글을 쓴다 · 티켓 S15P21E102-377.
 *
 * 각자 적어 두었더니 한쪽만 고친 날 학습 추천은 브라우저 기본 검은 삼각형,
 * 관련 공고는 브랜드 표기로 갈렸다.
 */

test('학습 추천과 관련 공고는 같은 추천 이유 토글을 공유한다', () => {
  const shared = "from '@/shared/ui/ReasonsDisclosure'"
  for (const path of [
    'features/matching/pages/WhatIfPage.tsx',
    'features/matching/components/NextSkillCard.tsx',
  ]) {
    assert.equal(source(path).includes(shared), true, path)
  }
})

test('부분 분석 배너는 추천 화면에서 면적만 줄이고 경고 색을 유지한다', () => {
  const panel = source('shared/ui/ComputeStatePanel.tsx')
  const page = source('features/matching/pages/RecommendationPage.tsx')

  assert.match(page, /<PartialNotice state=\{data\} compact \/>/)
  // 색과 문구는 그대로다. 줄이는 것은 면적뿐이다.
  assert.match(panel, /compact\s*\?\s*'w-fit rounded-full border border-tone-caution-bg bg-tone-caution-bg/)
})
