import assert from 'node:assert/strict'
import test from 'node:test'

import type {
  AnalysisAccepted,
  AnalysisRequestOutcome,
  RepositorySummary,
} from '../src/features/analysis/api/types.ts'
import {
  ANALYSIS_SELECTION_HISTORY_KEY,
  branchesFromDraft,
  createAnalysisSelectionDraft,
  outcomesFromDraft,
  readAnalysisSelectionDraft,
  selectedFromDraft,
} from '../src/features/analysis/model/selectionHistory.ts'

const repository: RepositorySummary = {
  githubRepositoryId: 101,
  fullName: 'team/service',
  name: 'service',
  owner: 'team',
  isPrivate: true,
  defaultBranch: 'develop',
  description: null,
  language: 'TypeScript',
  updatedAt: '2026-09-17T00:00:00Z',
  analyzable: true,
}

const accepted: AnalysisAccepted = {
  analysisId: 'analysis-1',
  status: 'QUEUED',
  repositoryFullName: repository.fullName,
  branchName: 'develop',
  commitSha: '0123456789abcdef',
  pollAfterSec: 2,
  statusUrl: '/api/v1/analyses/analysis-1',
}

test('선택·브랜치·성공한 분석을 history state로 왕복한다', () => {
  const outcome: AnalysisRequestOutcome = {
    target: { repositoryFullName: repository.fullName, branchName: 'develop' },
    ok: true,
    accepted,
  }
  const draft = createAnalysisSelectionDraft(
    [repository],
    new Map([[repository.fullName, 'develop']]),
    new Map([[repository.fullName, outcome]]),
  )

  const restored = readAnalysisSelectionDraft({ [ANALYSIS_SELECTION_HISTORY_KEY]: draft })

  assert.deepEqual([...selectedFromDraft(restored).values()], [repository])
  assert.equal(branchesFromDraft(restored).get(repository.fullName), 'develop')
  assert.deepEqual(outcomesFromDraft(restored).get(repository.fullName), outcome)
})

test('직렬화할 수 없는 실패 객체는 저장하지 않는다', () => {
  const failed: AnalysisRequestOutcome = {
    target: { repositoryFullName: repository.fullName, branchName: 'develop' },
    ok: false,
    error: new Error('request failed'),
  }
  const draft = createAnalysisSelectionDraft(
    [repository],
    new Map([[repository.fullName, 'develop']]),
    new Map([[repository.fullName, failed]]),
  )

  assert.deepEqual(draft.accepted, [])
  assert.equal(outcomesFromDraft(draft).size, 0)
})

test('버전이나 필드가 손상된 history state는 무시한다', () => {
  assert.equal(readAnalysisSelectionDraft(null), null)
  assert.equal(
    readAnalysisSelectionDraft({
      [ANALYSIS_SELECTION_HISTORY_KEY]: { version: 2, repositories: [], branches: [], accepted: [] },
    }),
    null,
  )
  assert.equal(
    readAnalysisSelectionDraft({
      [ANALYSIS_SELECTION_HISTORY_KEY]: {
        version: 1,
        repositories: [{ fullName: 'broken' }],
        branches: [],
        accepted: [],
      },
    }),
    null,
  )
})
