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
  dismissedBatchFromDraft,
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
  statusUrl: '/api/v1/analyses/analysis-1',
}

test('선택·브랜치·성공한 분석을 history state로 왕복한다', () => {
  const outcome: AnalysisRequestOutcome = {
    target: { repositoryFullName: repository.fullName, branchName: 'develop' },
    ok: true,
    reused: false,
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

test('실패한 저장소는 draft에 남기지 않아 다시 시도할 수 있다', () => {
  const failed: AnalysisRequestOutcome = {
    target: { repositoryFullName: repository.fullName, branchName: 'develop' },
    ok: false,
    error: { code: 'REPO-404-1', message: '저장소를 찾을 수 없습니다.' },
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
      [ANALYSIS_SELECTION_HISTORY_KEY]: { version: 9, repositories: [], branches: [], accepted: [] },
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

/*
 * v1 draft 는 배포 직전까지 브라우저가 들고 있던 값이다. 거절하면 배포 직후 뒤로 가기로
 * 돌아온 사용자의 선택이 통째로 사라진다.
 */
test('v1 draft도 읽고 늘어난 필드는 기본값으로 채운다', () => {
  const restored = readAnalysisSelectionDraft({
    [ANALYSIS_SELECTION_HISTORY_KEY]: {
      version: 1,
      repositories: [repository],
      branches: [[repository.fullName, 'develop']],
      accepted: [],
    },
  })

  assert.notEqual(restored, null)
  assert.equal(dismissedBatchFromDraft(restored), null)
  assert.deepEqual([...selectedFromDraft(restored).values()], [repository])
})

test('완료 안내를 닫은 묶음 ID는 history state로 왕복한다', () => {
  const draft = createAnalysisSelectionDraft([], new Map(), new Map(), 'ab_7')

  const restored = readAnalysisSelectionDraft({ [ANALYSIS_SELECTION_HISTORY_KEY]: draft })

  assert.equal(dismissedBatchFromDraft(restored), 'ab_7')
})
