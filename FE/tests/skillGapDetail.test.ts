import assert from 'node:assert/strict'
import test from 'node:test'

import { skillGapDetailRows } from '../src/features/matching/model/skillGapDetail.ts'
import type { SkillGapRowView } from '../src/features/matching/model/view.ts'

function row(techName: string, verdict: SkillGapRowView['verdict']): SkillGapRowView {
  return {
    techName,
    requiredCount: 1,
    preferredCount: null,
    personalLevel: null,
    verdict,
    verdictText: verdict,
    fillDelta: null,
  }
}

const ROWS = [
  row('Docker', 'MET'),
  row('Kafka', 'LEVEL_SHORT'),
  row('Redis', 'NO_EVIDENCE'),
  row('C++', 'UNDETERMINED'),
]

test('each stat opens exactly the rows its caption counts', () => {
  assert.deepEqual(
    skillGapDetailRows(ROWS, 'required').map((r) => r.techName),
    ['Docker', 'Kafka', 'Redis', 'C++'],
  )
  assert.deepEqual(skillGapDetailRows(ROWS, 'met').map((r) => r.techName), ['Docker'])
  assert.deepEqual(skillGapDetailRows(ROWS, 'gap').map((r) => r.techName), ['Kafka', 'Redis'])
  assert.deepEqual(skillGapDetailRows(ROWS, 'undetermined').map((r) => r.techName), ['C++'])
})

test('undetermined rows are never counted as gap', () => {
  const gap = skillGapDetailRows(ROWS, 'gap')
  assert.ok(gap.every((r) => r.verdict !== 'UNDETERMINED'))
})
