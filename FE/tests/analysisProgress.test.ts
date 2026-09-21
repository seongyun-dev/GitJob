import assert from 'node:assert/strict'
import test from 'node:test'

import {
  analysisPhase,
  analysisSteps,
  currentStepLabel,
  failureCopy,
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

/*
 * 단계 표시 · S15P21E102-136.
 *
 * 워커가 단계 전환을 발행하기 시작해서 생긴 값이다. 여기서 지키는 것은 "잘 그린다"가
 * 아니라 **모르는 것을 아는 척하지 않는다**로, 이 화면이 진행률과 남은 시간을 거절해 온
 * 이유와 같다.
 */
test('대기 중에는 어떤 단계도 진행 중이 아니다', () => {
  const steps = analysisSteps('QUEUED', 'WAITING_FOR_WORKER')

  assert.equal(steps.length, 3)
  assert.deepEqual(
    steps.map((step) => step.state),
    ['WAITING', 'WAITING', 'WAITING'],
  )
})

test('서버가 알려 준 단계에 불을 켜고 그 앞은 끝난 것으로 둔다', () => {
  assert.deepEqual(
    analysisSteps('RUNNING', 'ANALYZING_REPOSITORY').map((step) => step.state),
    ['RUNNING', 'WAITING', 'WAITING'],
  )
  assert.deepEqual(
    analysisSteps('RUNNING', 'ATTRIBUTING_CONTRIBUTION').map((step) => step.state),
    ['DONE', 'RUNNING', 'WAITING'],
  )
})

/*
 * 워커와 화면은 따로 배포된다. 새 단계가 먼저 도착했을 때 아무 칸도 켜지 않으면
 * 분석이 돌고 있는데도 화면은 멈춰 보인다.
 */
test('모르는 단계여도 진행 중이면 멈춰 보이지 않는다', () => {
  const states = analysisSteps('RUNNING', 'SUMMARIZING').map((step) => step.state)

  assert.equal(states[0], 'RUNNING')
  assert.ok(states.includes('RUNNING'))
})

/*
 * 기여도 판정을 끄고 돌리는 배포에서는 두 번째 전환이 아예 오지 않고, 켜져 있어도
 * 5초 폴링이 그 사이를 놓칠 수 있다. 화면은 둘을 구분할 수 없다.
 */
test('끝난 분석은 지나친 단계까지 완료로 그린다', () => {
  assert.deepEqual(
    analysisSteps('SUCCEEDED', 'COMPLETED').map((step) => step.state),
    ['DONE', 'DONE', 'DONE'],
  )
  assert.deepEqual(
    analysisSteps('PARTIAL', 'ANALYZING_REPOSITORY').map((step) => step.state),
    ['DONE', 'DONE', 'DONE'],
  )
})

/*
 * BE가 실패 시 current_stage를 FAILED로 덮어써서 어디까지 갔는지 남지 않는다.
 * 남지 않은 것을 그리면 지어낸 값이 된다 — 사유는 실패 카드가 말한다.
 */
test('실패한 분석은 어디까지 갔는지 말하지 않는다', () => {
  assert.deepEqual(
    analysisSteps('FAILED', 'FAILED').map((step) => step.state),
    ['WAITING', 'WAITING', 'WAITING'],
  )
})

test('좁은 패널의 한 줄은 진행 중일 때만 나온다', () => {
  assert.equal(currentStepLabel('RUNNING', 'ATTRIBUTING_CONTRIBUTION'), '2/3 · 개인 기여도 판정')
  assert.equal(currentStepLabel('QUEUED', 'WAITING_FOR_WORKER'), null)
  assert.equal(currentStepLabel('SUCCEEDED', 'COMPLETED'), null)
  assert.equal(currentStepLabel('FAILED', 'FAILED'), null)
})

/*
 * 서버가 응답 없는 분석을 정리하며 붙이는 코드다. GENERIC 으로 접히면 "분석에
 * 실패했어요"만 나와 사용자가 자기 저장소에 문제가 있는 줄 읽는다.
 */
test('응답이 없어 정리된 분석은 전용 문구로 말한다', () => {
  assert.equal(failureKind('ANALYSIS_TIMED_OUT'), 'TIMED_OUT')

  const copy = failureCopy('TIMED_OUT')
  assert.equal(copy.title, '응답이 없어 중단했어요')
  assert.match(copy.description, /다시 요청/)
})
