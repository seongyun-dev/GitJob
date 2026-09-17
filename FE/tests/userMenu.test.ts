import assert from 'node:assert/strict'
import test from 'node:test'

import { userMenuLinks } from '../src/features/auth/model/userMenu.ts'
import { MAIN_PATH } from '../src/features/landing/model/landingEntry.ts'

const USER = { role: 'USER' } as const
const ADMIN = { role: 'ADMIN' } as const

test('일반 사용자는 마이페이지만 본다', () => {
  assert.deepEqual(
    userMenuLinks(USER).map((link) => link.label),
    ['마이페이지'],
  )
})

/*
  관리자에게만 콘솔로 돌아가는 길을 준다. 지금까지는 로그인 직후 자동 이동이 유일한
  진입로여서, 서비스 화면으로 한 번 나오면 주소를 직접 쳐야 돌아갈 수 있었다.
*/
test('관리자는 모니터링이 함께 보인다', () => {
  assert.deepEqual(
    userMenuLinks(ADMIN).map((link) => link.label),
    ['마이페이지', '모니터링'],
  )
})

test('모니터링은 관리자 콘솔로 간다', () => {
  const monitoring = userMenuLinks(ADMIN).find((link) => link.label === '모니터링')

  assert.equal(monitoring?.to, '/admin')
})

test('마이페이지 목적지는 그대로다', () => {
  for (const me of [USER, ADMIN]) {
    const mypage = userMenuLinks(me).find((link) => link.label === '마이페이지')

    assert.equal(mypage?.to, '/mypage', `role ${me.role}`)
  }
})

/*
  역할은 `/auth/me` 가 주는 값 하나만 본다. 이름·계정으로 관리자를 알아내려 하지 않는다 —
  `AdminLayout` 의 role guard 와 같은 출처를 써야 화면과 가드가 어긋나지 않는다.
*/
test('ADMIN 이 아닌 역할에는 모니터링을 주지 않는다', () => {
  for (const role of ['USER', 'admin', 'Admin', '']) {
    const labels = userMenuLinks({ role } as { role: 'USER' | 'ADMIN' }).map((link) => link.label)

    assert.deepEqual(labels, ['마이페이지'], `role ${JSON.stringify(role)}`)
  }
})

test('사용자가 없으면 메뉴도 없다', () => {
  assert.deepEqual(userMenuLinks(null), [])
  assert.deepEqual(userMenuLinks(undefined), [])
})

test('링크 id 는 서로 다르다', () => {
  const ids = userMenuLinks(ADMIN).map((link) => link.id)

  assert.equal(new Set(ids).size, ids.length)
})

/*
  관리자 화면의 로고가 가는 곳. 콘솔 밖으로 나가는 유일한 길이라 `/`(진입 갈림길)나
  `/intro`(소개)가 아니라 서비스 메인이어야 한다.
*/
test('관리자 로고는 서비스 메인으로 간다', () => {
  assert.equal(MAIN_PATH, '/main')
})
