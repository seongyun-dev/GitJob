import assert from 'node:assert/strict'
import test from 'node:test'

import {
  careerSelectionFromValues,
  careerValues,
  normalizeTargetRole,
  TARGET_ROLES,
} from '../src/features/matching/model/targetOptions.ts'

test('target role choices use the five compute-supported canonical values', () => {
  assert.deepEqual(
    TARGET_ROLES.map(({ value, label }) => ({ value, label })),
    [
      { value: 'BACKEND', label: '백엔드' },
      { value: 'FRONTEND', label: '프론트엔드' },
      { value: 'AI_DATA', label: 'AI · 데이터' },
      { value: 'INFRASTRUCTURE', label: '인프라' },
      { value: 'MOBILE', label: '모바일' },
    ],
  )
})

test('legacy role aliases are restored into the selectable canonical value', () => {
  assert.equal(normalizeTargetRole('backend'), 'BACKEND')
  assert.equal(normalizeTargetRole('data'), 'AI_DATA')
  assert.equal(normalizeTargetRole('devops'), 'INFRASTRUCTURE')
  assert.equal(normalizeTargetRole('something-else'), null)
})

test('career control preserves the existing API array contract', () => {
  assert.equal(careerSelectionFromValues([]), 'ALL')
  assert.equal(careerSelectionFromValues(['신입']), 'ENTRY')
  assert.equal(careerSelectionFromValues(['경력 3년 이상']), 'EXPERIENCED')
  assert.deepEqual(careerValues('ALL'), [])
  assert.deepEqual(careerValues('ENTRY'), ['신입'])
  assert.deepEqual(careerValues('EXPERIENCED'), ['경력'])
})
