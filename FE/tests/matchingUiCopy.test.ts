import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function source(path: string): string {
  return readFileSync(new URL(`../src/features/matching/${path}`, import.meta.url), 'utf8')
}

test('공고 화면은 내부 판정 보류와 조건부 제외 문구를 사용자에게 노출하지 않는다', () => {
  const jobScreens = [
    source('pages/JobMatchPage.tsx'),
    source('pages/JobPostingDetailPage.tsx'),
    source('components/JobRequirementDrawer.tsx'),
  ].join('\n')

  assert.equal(jobScreens.includes('자동 판정이 필요한 요구사항'), false)
  assert.equal(jobScreens.includes('조건부 제외'), false)
})

test('부족한 기술 화면은 행동할 수 없는 미판정 분류표를 숨긴다', () => {
  const page = source('pages/SkillGapPage.tsx')
  assert.equal(page.includes('판단 근거 부족'), false)
  assert.equal(page.includes('LEGEND'), false)
})

test('추천과 배웠을 때 변화의 빈 상태는 다음 행동을 제공한다', () => {
  const recommendation = source('pages/RecommendationPage.tsx')
  const whatIf = source('pages/WhatIfPage.tsx')

  assert.match(recommendation, /title="추천할 기술이 없어요"[\s\S]{0,500}action=/)
  assert.match(whatIf, /title="가정해 볼 후보가 없어요"[\s\S]{0,500}action=/)
  assert.match(whatIf, /title="새로 부합하는 공고가 없어요"[\s\S]{0,500}action=/)
})
