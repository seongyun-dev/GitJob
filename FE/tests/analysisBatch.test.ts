import assert from 'node:assert/strict'
import test from 'node:test'

import type {
  AnalysisBatchAccepted,
  LatestBatch,
  LatestBatchItem,
  LatestBatchView,
} from '../src/features/analysis/api/types.ts'
import {
  batchMarks,
  batchPhase,
  batchPollInterval,
  batchProgressLabel,
  itemByRepository,
  outcomesFromBatchResponse,
  canSelectMore,
  selectionLimitNotice,
  showResetPrompt,
  submitBlockedReason,
  submitFailureMessage,
} from '../src/features/analysis/model/analysisBatch.ts'

function item(overrides: Partial<LatestBatchItem> = {}): LatestBatchItem {
  return {
    analysisId: 'an_1',
    repositoryId: '555',
    repositoryFullName: 'team/service',
    branchName: 'main',
    commitSha: '0123456789abcdef',
    analysisStatus: 'QUEUED',
    currentStage: 'WAITING_FOR_WORKER',
    requestedAt: '2026-09-20T00:00:00Z',
    errorCode: null,
    ...overrides,
  }
}

function batch(overrides: Partial<LatestBatch> = {}): LatestBatch {
  return {
    batchId: 'ab_1',
    requestedAt: '2026-09-20T00:00:00Z',
    totalCount: 4,
    completedCount: 2,
    failedCount: 0,
    pollAfterSeconds: 5,
    items: [item()],
    ...overrides,
  }
}

test('묶음이 없으면 국면은 NONE이다', () => {
  assert.equal(batchPhase(null), 'NONE')
  assert.equal(batchPhase(undefined), 'NONE')
  assert.equal(batchPhase(batch({ totalCount: 0, completedCount: 0 })), 'NONE')
})

test('끝난 수가 전체에 못 미치면 진행 중이다', () => {
  assert.equal(batchPhase(batch({ totalCount: 4, completedCount: 2 })), 'IN_PROGRESS')
  assert.equal(batchPhase(batch({ totalCount: 4, completedCount: 0 })), 'IN_PROGRESS')
})

test('전부 끝나면 완료다', () => {
  assert.equal(batchPhase(batch({ totalCount: 4, completedCount: 4 })), 'COMPLETE')
})

/*
 * 폴링이 멎는 것과 분석이 끝난 것은 다른 사실이다. pollAfterSeconds 로 국면을 판정하면
 * 서버가 폴링만 멈춘 경우에도 화면이 "완료"라고 말한다.
 */
test('국면은 폴링 여부와 무관하게 개수로만 정한다', () => {
  assert.equal(
    batchPhase(batch({ totalCount: 4, completedCount: 2, pollAfterSeconds: null })),
    'IN_PROGRESS',
  )
})

test('진행률은 분모를 함께 말한다', () => {
  assert.equal(batchProgressLabel(batch({ totalCount: 4, completedCount: 2 })), '2/4 완료')
  assert.equal(batchProgressLabel(null), null)
  assert.equal(batchProgressLabel(batch({ totalCount: 0 })), null)
})

test('저장소마다 칸 하나이고 실패는 미시작과 다른 색이다', () => {
  const marks = batchMarks(
    batch({
      items: [
        item({ analysisStatus: 'SUCCEEDED' }),
        item({ analysisStatus: 'PARTIAL_SUCCEEDED' }),
        item({ analysisStatus: 'FAILED' }),
        item({ analysisStatus: 'RUNNING' }),
      ],
    }),
  )

  assert.deepEqual(marks, ['HAVE', 'HAVE', 'WEAK', 'NONE'])
})

test('폴링 간격은 서버가 준 값만 따르고 null이면 멈춘다', () => {
  assert.equal(batchPollInterval({ canSubmit: false, maxBatchSize: 10, batch: batch() }), 5000)
  assert.equal(
    batchPollInterval({ canSubmit: true, maxBatchSize: 10, batch: batch({ pollAfterSeconds: null }) }),
    false,
  )
  assert.equal(batchPollInterval({ canSubmit: true, maxBatchSize: 10, batch: null }), false)
  assert.equal(batchPollInterval(undefined), false)
})

test('완료한 묶음에만 초기화 안내를 띄운다', () => {
  assert.equal(showResetPrompt(batch({ totalCount: 4, completedCount: 4 }), null), true)
  assert.equal(showResetPrompt(batch({ totalCount: 4, completedCount: 2 }), null), false)
  assert.equal(showResetPrompt(null, null), false)
})

test('닫은 묶음은 다시 뜨지 않는다', () => {
  const done = batch({ batchId: 'ab_1', totalCount: 2, completedCount: 2 })

  assert.equal(showResetPrompt(done, 'ab_1'), false)
})

/*
 * 닫힘을 boolean 으로 두면 새 묶음이 시작된 순간 낡은 값이 되어, 방금 등록한 분석의
 * 완료 안내가 뜨지 않는다. ID 로 두면 저절로 회복된다.
 */
test('다른 묶음이 시작되면 안내가 저절로 다시 열린다', () => {
  const next = batch({ batchId: 'ab_2', totalCount: 2, completedCount: 2 })

  assert.equal(showResetPrompt(next, 'ab_1'), true)
})

test('저장소 이름으로 구성원을 찾는다', () => {
  const table = itemByRepository(
    batch({
      items: [
        item({ repositoryFullName: 'team/a', analysisId: 'an_a' }),
        item({ repositoryFullName: 'team/b', analysisId: 'an_b' }),
        item({ repositoryFullName: null, analysisId: 'an_c' }),
      ],
    }),
  )

  assert.equal(table.get('team/a')?.analysisId, 'an_a')
  assert.equal(table.get('team/b')?.analysisId, 'an_b')
  assert.equal(table.size, 2)
  assert.equal(itemByRepository(null).size, 0)
})

test('제출할 수 있으면 막는 이유가 없다', () => {
  const view: LatestBatchView = { canSubmit: true, maxBatchSize: 10, batch: batch() }

  assert.equal(submitBlockedReason(view), null)
  assert.equal(submitBlockedReason(undefined), null)
})

test('막혔으면 이유를 문장으로 말한다', () => {
  const view: LatestBatchView = { canSubmit: false, maxBatchSize: 10, batch: null }

  assert.equal(submitBlockedReason(view), '진행 중인 분석이 끝나면 새로 요청할 수 있어요.')
})

function response(overrides: Partial<AnalysisBatchAccepted> = {}): AnalysisBatchAccepted {
  return {
    batchId: 'ab_1',
    totalCount: 1,
    acceptedCount: 1,
    reusedCount: 0,
    failedCount: 0,
    pollAfterSeconds: 2,
    statusUrl: '/api/v1/me/analyses/latest-batch',
    items: [],
    ...overrides,
  }
}

/*
 * 서버는 저장소 이름을 GitHub 정규 표기로 바꾼다. 화면은 목록에서 받은 이름으로 선택을
 * 키잉하므로, 정규 표기로 키를 잡으면 대소문자가 다른 저장소의 결과가 어느 카드에도
 * 붙지 않는다.
 */
test('결과는 서버가 고친 이름이 아니라 보낸 이름으로 키잉한다', () => {
  const outcomes = outcomesFromBatchResponse(
    response({
      items: [
        {
          requestedRepositoryFullName: 'team/Service',
          outcome: 'ACCEPTED',
          analysisId: 'an_1',
          status: 'QUEUED',
          repositoryFullName: 'Team/service',
          branchName: 'main',
          commitSha: '0123456789abcdef',
          statusUrl: '/api/v1/analyses/an_1',
          errorCode: null,
          message: null,
        },
      ],
    }),
    new Map(),
  )

  assert.equal(outcomes.size, 1)
  assert.equal(outcomes.has('team/Service'), true)
})

test('재사용은 실패가 아니라 성공 쪽에 담기되 구분은 남는다', () => {
  const outcomes = outcomesFromBatchResponse(
    response({
      items: [
        {
          requestedRepositoryFullName: 'team/service',
          outcome: 'REUSED',
          analysisId: 'an_existing',
          status: 'ANALYZING',
          repositoryFullName: 'team/service',
          branchName: 'develop',
          commitSha: '0123456789abcdef',
          statusUrl: '/api/v1/analyses/an_existing',
          errorCode: null,
          message: null,
        },
      ],
    }),
    new Map(),
  )

  const outcome = outcomes.get('team/service')
  assert.equal(outcome?.ok, true)
  assert.equal(outcome?.ok === true && outcome.reused, true)
})

test('실패 항목은 코드와 문장을 함께 들고 온다', () => {
  const outcomes = outcomesFromBatchResponse(
    response({
      items: [
        {
          requestedRepositoryFullName: 'team/missing',
          outcome: 'FAILED',
          analysisId: null,
          status: null,
          repositoryFullName: null,
          branchName: null,
          commitSha: null,
          statusUrl: null,
          errorCode: 'REPO-404-1',
          message: '저장소를 찾을 수 없습니다.',
        },
      ],
    }),
    new Map([['team/missing', 'main']]),
  )

  const outcome = outcomes.get('team/missing')
  assert.equal(outcome?.ok, false)
  assert.equal(outcome?.ok === false && outcome.error.code, 'REPO-404-1')
  assert.equal(outcome?.ok === false && outcome.error.message, '저장소를 찾을 수 없습니다.')
  // 브랜치는 서버가 확정하지 못했으므로 화면이 고른 값으로 되돌린다.
  assert.equal(outcome?.target.branchName, 'main')
})

test('사유 문장이 없는 실패도 빈 화면으로 두지 않는다', () => {
  const outcomes = outcomesFromBatchResponse(
    response({
      items: [
        {
          requestedRepositoryFullName: 'team/missing',
          outcome: 'FAILED',
          analysisId: null,
          status: null,
          repositoryFullName: null,
          branchName: null,
          commitSha: null,
          statusUrl: null,
          errorCode: null,
          message: null,
        },
      ],
    }),
    new Map(),
  )

  const outcome = outcomes.get('team/missing')
  assert.equal(outcome?.ok === false && outcome.error.message, '요청을 처리할 수 없습니다.')
})

function view(overrides: Partial<LatestBatchView> = {}): LatestBatchView {
  return { canSubmit: true, maxBatchSize: 10, batch: null, ...overrides }
}

test('상한까지는 더 고를 수 있다', () => {
  assert.equal(canSelectMore(9, view({ maxBatchSize: 10 })), true)
  assert.equal(canSelectMore(10, view({ maxBatchSize: 10 })), false)
  assert.equal(canSelectMore(11, view({ maxBatchSize: 10 })), false)
})

/*
 * 상한을 모르는 동안 막으면, 조회가 늦은 사용자는 고를 수 있는 것을 못 고른다.
 * 서버가 말해 주기 전에는 막지 않는다.
 */
test('상한을 모르면 막지 않는다', () => {
  assert.equal(canSelectMore(99, undefined), true)
  assert.equal(canSelectMore(99, view({ maxBatchSize: 0 })), true)
})

test('상한에 닿으면 몇 개까지인지 말한다', () => {
  assert.equal(selectionLimitNotice(9, view({ maxBatchSize: 10 })), null)

  const notice = selectionLimitNotice(10, view({ maxBatchSize: 10 }))
  assert.notEqual(notice, null)
  assert.match(notice as string, /10개/)
})

/*
 * 항목별 실패는 응답 본문으로 오지만 요청 전체의 거절은 예외로만 온다. 여기서 문장을
 * 만들지 않으면 버튼을 눌러도 아무 일도 일어나지 않는 화면이 된다(AN-400-1 이 그랬다).
 */
test('요청 전체가 거절되면 코드와 함께 사유를 말한다', () => {
  // ApiError 의 모양만 갖추면 된다. 클래스를 쓰면 이 파일이 `@/` 별칭에 묶인다.
  const error = Object.assign(new Error('한 번에 요청할 수 있는 저장소 수를 넘었습니다.'), {
    status: 400,
    code: 'AN-400-1',
  })

  assert.equal(
    submitFailureMessage(error),
    '한 번에 요청할 수 있는 저장소 수를 넘었습니다. (코드 AN-400-1)',
  )
})

test('ApiError가 아닌 실패도 말없이 넘기지 않는다', () => {
  const message = submitFailureMessage(new Error('network down'))

  assert.notEqual(message, null)
  assert.match(message as string, /다시 시도/)
})

test('실패가 없으면 표시할 것도 없다', () => {
  assert.equal(submitFailureMessage(null), null)
  assert.equal(submitFailureMessage(undefined), null)
})
