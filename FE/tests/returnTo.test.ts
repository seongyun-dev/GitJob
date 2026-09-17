import assert from 'node:assert/strict'
import test from 'node:test'

import {
  RETURN_TO_STORAGE_KEY,
  consumeReturnTo,
  rememberReturnTo,
  safeReturnTo,
} from '../src/features/auth/returnTo.ts'

class MemoryStorage {
  readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }
}

/** private mode 처럼 접근 자체가 던지는 브라우저. */
class ThrowingStorage {
  getItem(): string | null {
    throw new Error('storage is blocked')
  }

  setItem(): void {
    throw new Error('storage is blocked')
  }

  removeItem(): void {
    throw new Error('storage is blocked')
  }
}

test('pathname · search · hash 를 그대로 보존한다', () => {
  const storage = new MemoryStorage()

  rememberReturnTo(storage, {
    pathname: '/jobs/123',
    search: '?tab=requirements',
    hash: '#skills',
  })

  assert.equal(storage.values.get(RETURN_TO_STORAGE_KEY), '/jobs/123?tab=requirements#skills')
})

test('search 와 hash 가 없으면 pathname 만 담는다', () => {
  const storage = new MemoryStorage()

  rememberReturnTo(storage, { pathname: '/evidence', search: '', hash: '' })

  assert.equal(storage.values.get(RETURN_TO_STORAGE_KEY), '/evidence')
})

test('내부 절대경로는 통과한다', () => {
  for (const value of [
    '/jobs',
    '/jobs/123?tab=requirements',
    '/evidence/kafka',
    '/trends/rust#adoption',
    '/mypage',
  ]) {
    assert.equal(safeReturnTo(value), value, `값 ${value}`)
  }
})

/*
  주소창과 sessionStorage 는 사용자가 고칠 수 있다. 여기서 막지 않으면 로그인 직후
  임의의 바깥 주소로 나가는 열린 리다이렉트가 된다.
*/
test('외부 주소는 거부한다', () => {
  for (const value of [
    'https://evil.com',
    'http://evil.com/jobs',
    '//evil.com',
    '/\\evil.com',
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'jobs',
    '',
    ' /jobs',
  ]) {
    assert.equal(safeReturnTo(value), null, `값 ${JSON.stringify(value)}`)
  }
})

test('없는 값은 거부한다', () => {
  assert.equal(safeReturnTo(null), null)
  assert.equal(safeReturnTo(undefined), null)
})

/*
  인증 왕복 경로를 목적지로 삼으면 로그인 직후 다시 로그인 화면이 열린다. 왕복이
  끝난 자리로 돌아가는 것이 returnTo 의 의미다.
*/
test('인증 왕복 경로는 목적지가 될 수 없다', () => {
  for (const value of [
    '/login',
    '/login?redirectTo=/jobs',
    '/auth/callback',
    '/auth/callback?status=success',
    '/admin/login',
    '/onboarding/github',
  ]) {
    assert.equal(safeReturnTo(value), null, `값 ${value}`)
  }
})

test('인증 경로로 시작하는 다른 경로는 막지 않는다', () => {
  assert.equal(safeReturnTo('/logins'), '/logins')
  assert.equal(safeReturnTo('/onboarding/repositories'), '/onboarding/repositories')
})

test('안전하지 않은 값은 저장하지 않는다', () => {
  const storage = new MemoryStorage()

  rememberReturnTo(storage, { pathname: '//evil.com', search: '', hash: '' })
  rememberReturnTo(storage, { pathname: '/login', search: '', hash: '' })

  assert.equal(storage.values.has(RETURN_TO_STORAGE_KEY), false)
})

test('한 번 쓰면 즉시 지운다', () => {
  const storage = new MemoryStorage()
  rememberReturnTo(storage, { pathname: '/jobs/123', search: '', hash: '' })

  assert.equal(consumeReturnTo(storage), '/jobs/123')
  assert.equal(storage.values.has(RETURN_TO_STORAGE_KEY), false)
  assert.equal(consumeReturnTo(storage), null)
})

/*
  저장해 둔 값이 그 사이에 손상됐을 수 있다. 읽을 때도 같은 판정을 걸고, 쓸 수 없는
  값이면 남겨 두지 않는다 — 다음 로그인이 그 값을 다시 만나면 안 된다.
*/
test('손상된 값은 돌려주지 않고 지운다', () => {
  const storage = new MemoryStorage()
  storage.setItem(RETURN_TO_STORAGE_KEY, 'https://evil.com')

  assert.equal(consumeReturnTo(storage), null)
  assert.equal(storage.values.has(RETURN_TO_STORAGE_KEY), false)
})

test('저장된 값이 없으면 null 이다', () => {
  assert.equal(consumeReturnTo(new MemoryStorage()), null)
})

test('Storage 가 없어도 던지지 않는다', () => {
  assert.doesNotThrow(() => rememberReturnTo(null, { pathname: '/jobs', search: '', hash: '' }))
  assert.equal(consumeReturnTo(null), null)
  assert.equal(consumeReturnTo(undefined), null)
})

test('Storage 접근이 막혀 있어도 던지지 않는다', () => {
  const storage = new ThrowingStorage()

  assert.doesNotThrow(() => rememberReturnTo(storage, { pathname: '/jobs', search: '', hash: '' }))
  assert.equal(consumeReturnTo(storage), null)
})
