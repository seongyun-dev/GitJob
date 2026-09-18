import assert from 'node:assert/strict'
import test from 'node:test'

import { buildEvidenceOverviewPanels } from '../src/features/evidence/model/overview.ts'

test('evidence side panels are derived from the profile response without fixture values', () => {
  const panels = buildEvidenceOverviewPanels(
    [
      {
        techId: 'spring-boot',
        displayName: 'Spring Boot',
        personalLevel: 'L1',
        repositoryLevel: 'L2',
        evidenceCount: 8,
        repositoryCount: 2,
        registryVersion: '2026-09-01',
      },
      {
        techId: 'postgresql',
        displayName: 'PostgreSQL',
        personalLevel: null,
        repositoryLevel: 'L2',
        evidenceCount: 3,
        repositoryCount: 1,
        registryVersion: '2026-09-01',
      },
    ],
    [
      {
        repositoryId: '101',
        fullName: 'team/backend',
        commitSha: 'abcdef123456',
        analyzedAt: '2026-09-16T08:00:00Z',
        evidenceCount: 11,
      },
    ],
  )

  assert.deepEqual(panels.reinforcements, [
    {
      techId: 'spring-boot',
      techName: 'Spring Boot',
      personalLevel: 'L1',
      repoLevel: 'L2',
      reason: '저장소에서는 확인됐지만 내가 작성한 코드에서는 아직 확인되지 않았어요.',
    },
  ])
  assert.deepEqual(panels.repositories, [
    {
      repositoryId: '101',
      name: 'team/backend',
      commitSha: 'abcdef123456',
      analyzedAt: '2026-09-16T08:00:00Z',
      evidenceCount: 11,
    },
  ])
})

test('legacy analyses without repository names remain explicit instead of inventing a name', () => {
  const panels = buildEvidenceOverviewPanels([], [
    {
      repositoryId: '202',
      fullName: null,
      commitSha: '1234567',
      analyzedAt: '2026-09-15T08:00:00Z',
      evidenceCount: 0,
    },
  ])

  assert.equal(panels.repositories[0]?.name, '이름이 기록되지 않은 저장소')
})
