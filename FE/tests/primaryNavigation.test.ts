import assert from 'node:assert/strict'
import test from 'node:test'

import { PRIMARY_NAV } from '../src/shared/config/primaryNav.ts'

test('사용자 내비게이션은 내부 영문 용어 대신 행동을 설명한다', () => {
  const labels = PRIMARY_NAV.flatMap((item) => [
    item.label,
    ...('kind' in item ? [] : (item.children ?? []).map((child) => child.label)),
  ])

  assert.equal(labels.includes('Skill Gap'), false)
  assert.equal(labels.includes('What-if'), false)
  assert.equal(labels.includes('부족한 기술'), false)
  assert.ok(labels.includes('배웠을 때 변화'))
})

test('모든 핵심 사용자 화면은 내비게이션 목적지로 남는다', () => {
  const destinations = PRIMARY_NAV.flatMap((item) =>
    'kind' in item ? [] : [item.to, ...(item.children ?? []).map((child) => child.to)],
  )

  for (const path of [
    '/onboarding/repositories',
    '/evidence',
    '/jobs',
    '/roles',
    '/recommendations',
    '/what-if',
    '/trends',
  ]) {
    assert.ok(destinations.includes(path), path)
  }
})
