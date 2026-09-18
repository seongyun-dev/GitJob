import assert from 'node:assert/strict'
import test from 'node:test'

import {
  analysisPhase,
  failureKind,
  hasResult,
  isPending,
  phaseCopy,
  phaseHeadline,
  waitedMinutes,
} from '../src/features/analysis/model/analysisProgress.ts'

/*
 * 이 티켓(S15P21E102-326)이 고친 것이 바로 이 구분이다. 대기와 진행이 한 값으로
 * 접히면 아직 시작되지 않은 분석에도 "분석하고 있어요"가 붙는다.
 */
test('대기와 진행은 서로 다른 국면이다', () => {
  assert.equal(analysisPhase('QUEUED'), 'QUEUED')
  assert.equal(analysisPhase('RUNNING'), 'RUNNING')
  assert.notEqual(analysisPhase('QUEUED'), analysisPhase('RUNNING'))
})

test('대기 중에는 진행 중이라고 말하지 않는다', () => {
  assert.equal(phaseCopy('QUEUED').title, '분석 차례를 기다리고 있어요')
  assert.equal(phaseHeadline('QUEUED'), '분석 차례를 기다리고 있어요')
  assert.notEqual(phaseCopy('QUEUED').title, phaseCopy('RUNNING').title)
})

test('계약이 정한 다섯 값을 그대로 옮긴다', () => {
  assert.equal(analysisPhase('SUCCEEDED'), 'SUCCEEDED')
  assert.equal(analysisPhase('PARTIAL_SUCCEEDED'), 'PARTIAL')
  assert.equal(analysisPhase('FAILED'), 'FAILED')
})

/*
 * BE가 응답 경계에서 다섯 값으로 좁히므로 여기 오는 미지의 값은 계약이 어긋났다는
 * 뜻이다. 그때 진행 중으로 남으면 화면이 무한 폴링에 갇힌다.
 */
test('모르는 상태는 진행 중으로 두지 않는다', () => {
  assert.equal(analysisPhase('RATE_LIMITED'), 'FAILED')
  assert.equal(analysisPhase(''), 'FAILED')
  assert.equal(isPending(analysisPhase('무엇인가')), false)
})

test('결과를 보러 갈 수 있는 국면은 성공과 부분 성공뿐이다', () => {
  assert.equal(hasResult('SUCCEEDED'), true)
  assert.equal(hasResult('PARTIAL'), true)
  assert.equal(hasResult('QUEUED'), false)
  assert.equal(hasResult('RUNNING'), false)
  assert.equal(hasResult('FAILED'), false)
})

test('실패 사유는 복구 경로가 다른 것끼리만 갈린다', () => {
  assert.equal(failureKind('GITHUB_RECONNECT_REQUIRED'), 'GITHUB_RECONNECT')
  assert.equal(failureKind('REPOSITORY_NOT_ACCESSIBLE'), 'REPOSITORY')
  assert.equal(failureKind('REPOSITORY_CREDENTIAL_NOT_FOUND'), 'REPOSITORY')
  assert.equal(failureKind('CREDENTIAL_BROKER_UNAVAILABLE'), 'CREDENTIAL_BROKER')
  assert.equal(failureKind(null), 'GENERIC')
  assert.equal(failureKind('알 수 없는 코드'), 'GENERIC')
})

/*
 * 경과 시간은 사실이라 적고, 모르는 것은 적지 않는다. 갓 누른 버튼 옆의 "0분 경과"와
 * 파싱 실패로 지어낸 시각이 둘 다 없어야 한다.
 */
test('경과 시간은 1분부터 세고 파싱에 실패하면 말하지 않는다', () => {
  const requestedAt = '2026-09-18T00:00:00Z'
  const base = Date.parse(requestedAt)

  assert.equal(waitedMinutes(requestedAt, base), null)
  assert.equal(waitedMinutes(requestedAt, base + 59_000), null)
  assert.equal(waitedMinutes(requestedAt, base + 60_000), 1)
  assert.equal(waitedMinutes(requestedAt, base + 185_000), 3)
  assert.equal(waitedMinutes('어제', base), null)
})
