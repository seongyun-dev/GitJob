import assert from 'node:assert/strict'
import test from 'node:test'

import { authGate } from '../src/features/auth/authGate.ts'

const USER = { userId: 'u-1' }

test('로그인한 사용자는 통과한다', () => {
  assert.equal(authGate({ me: USER, settled: true }), 'ALLOW')
})

/*
  창 포커스마다 `/me` 를 다시 확인한다(`useMe` 의 refetchOnWindowFocus). 이미 확인된
  사용자를 붙잡고 있지 않으면 탭을 옮길 때마다 보호 화면이 깜빡인다. 확정을 기다리게
  해도 같은 일이 생긴다 — 보호 화면 사이를 오갈 때마다 로딩이 끼어든다.
*/
test('확인이 끝나기 전이어도 이미 아는 사용자는 통과한다', () => {
  assert.equal(authGate({ me: USER, settled: false }), 'ALLOW')
})

test('아직 확인 중이면 기다린다', () => {
  assert.equal(authGate({ me: undefined, settled: false }), 'LOADING')
})

/*
  `fetchMe` 가 401 을 `null` 로 접기 때문에 `null` 은 로그아웃이기도 하고 아직 확인되지
  않은 이전 값이기도 하다. 브라우저 QA 에서 실제로 걸렸다 — 공개 화면에서 캐시된 `null`
  을 안고 보호 화면으로 넘어가면 다시 확인해 보지도 않고 로그인 화면으로 보냈다.
*/
test('확인 전의 null 은 로그아웃으로 읽지 않는다', () => {
  assert.equal(authGate({ me: null, settled: false }), 'LOADING')
})

test('확인이 끝나 확정된 null 만 로그인 화면으로 보낸다', () => {
  assert.equal(authGate({ me: null, settled: true }), 'REDIRECT')
})

/*
  네트워크 실패로 `/me` 를 읽지 못하면 로그아웃인지 알 수 없다. 기다리게 두면 화면이
  영영 비어 있으므로 로그인 화면으로 접는다 — 그쪽에는 되돌아올 길이 있다.
*/
test('확인에 실패하면 로그인 화면으로 보낸다', () => {
  assert.equal(authGate({ me: undefined, settled: true, failed: true }), 'REDIRECT')
})

test('실패해도 아직 확인 중이면 기다린다', () => {
  assert.equal(authGate({ me: undefined, settled: false, failed: true }), 'LOADING')
})

test('실패 플래그가 켜져 있어도 사용자가 있으면 통과한다', () => {
  assert.equal(authGate({ me: USER, settled: true, failed: true }), 'ALLOW')
})

/*
  확인이 끝났는데 값도 없고 실패도 아닌 조합은 실제로는 나오지 않는다. 그래도 그 자리를
  로그인 화면으로 열어 두지 않는다 — 판정할 근거가 없을 때 사용자를 쫓아낼 이유는 없다.
*/
test('근거가 없으면 쫓아내지 않는다', () => {
  assert.equal(authGate({ me: undefined, settled: true }), 'LOADING')
})
