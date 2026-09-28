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

test('공고 화면과 부족한 기술 화면은 다음 단계 유도 카드를 중복 노출하지 않는다', () => {
  const jobMatch = source('pages/JobMatchPage.tsx')
  const jobDetail = source('pages/JobPostingDetailPage.tsx')
  const skillGap = source('pages/SkillGapPage.tsx')

  assert.equal(jobMatch.includes('to="/recommendations"'), false)
  assert.equal(jobMatch.includes('to="/skill-gap"'), false)
  assert.equal(jobDetail.includes('to="/skill-gap"'), false)
  assert.equal(skillGap.includes('to="/recommendations"'), false)
})

test('추천과 관련 공고의 빈 상태는 다음 행동을 제공한다', () => {
  const recommendation = source('pages/RecommendationPage.tsx')
  const whatIf = source('pages/WhatIfPage.tsx')

  assert.match(recommendation, /title="추천할 기술이 없어요"[\s\S]{0,500}action=/)
  assert.match(whatIf, /title="추천 기술이 없어요"[\s\S]{0,500}action=/)
  assert.match(whatIf, /관련 공고가 없어요[\s\S]{0,700}action=/)
})

test('다음 기술은 필수·우대 공고 수를 합치지 않고 표시한다', () => {
  const card = source('components/NextSkillCard.tsx')
  const detail = source('pages/WhatIfPage.tsx')
  const summary = source('components/ConditionImpactSummary.tsx')
  const gapRows = source('components/SkillGapRows.tsx')
  const gap = source('pages/SkillGapPage.tsx')
  const recommendation = source('pages/RecommendationPage.tsx')
  const chain = source('components/RecommendationChain.tsx')

  assert.match(card, /<ConditionImpactSummary[\s\S]*requiredCount=\{requiredImpactCount\}[\s\S]*preferredCount=\{preferredImpactCount\}/)
  assert.match(detail, /<ConditionImpactSummary[\s\S]*requiredCount=\{impact\.requiredCount\}[\s\S]*preferredCount=\{impact\.preferredCount\}/)
  assert.match(summary, /return `\+\$\{count\.toLocaleString\('ko-KR'\)\}건`/)
  assert.equal(summary.includes('affectedCount'), false)
  assert.match(summary, />필수 공고</)
  assert.match(summary, /우대 공고 \{preferredCount\.toLocaleString\('ko-KR'\)\}건/)
  assert.equal(summary.includes('새로 맞'), false)
  assert.equal(summary.includes('다른 조건은 별도 확인'), false)
  assert.match(card, /공고 보기/)
  assert.equal(card.includes('현재 충족'), false)
  assert.equal(card.includes('확보 후'), false)
  assert.match(recommendation, /관련 공고가 많은 기술부터 보여드려요/)
  assert.match(detail, /관련 공고/)
  assert.match(chain, /label: '관련 공고'/)
  assert.equal([recommendation, detail, chain].join('\n').includes('새로 맞'), false)
  assert.equal([recommendation, detail, chain].join('\n').includes('L1 수준'), false)
  assert.match(detail, /\['ALL', `전체 \$\{formatImpactIncrease\(impact\.affectedCount\)\}`\]/)
  assert.match(detail, /\['REQUIRED', `필수 \$\{formatImpactIncrease\(impact\.requiredCount\)\}`\]/)
  assert.match(detail, /\['PREFERRED', `우대 \$\{formatImpactIncrease\(impact\.preferredCount\)\}`\]/)
  assert.match(gapRows, /formatImpactIncrease\(row\.fillDelta\)/)
  assert.match(detail, /조건 확인 필요/)
  assert.match(gap, /관련 공고/)
  assert.equal(gap.includes('공고 선택지가 많이 늘어나는'), false)
})
