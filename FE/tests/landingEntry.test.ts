import assert from 'node:assert/strict'
import test from 'node:test'

import {
  INTRO_PATH,
  LANDING_SEEN_STORAGE_KEY,
  MAIN_PATH,
  landingEntryPath,
  markLandingSeen,
  readLandingSeen,
} from '../src/features/landing/model/landingEntry.ts'

class MemoryStorage {
  readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
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
}

test('저장된 값이 없으면 랜딩을 아직 보지 않은 것으로 읽는다', () => {
  assert.equal(readLandingSeen(new MemoryStorage()), false)
})

test('markLandingSeen 이 약속된 키에 true 를 남긴다', () => {
  const storage = new MemoryStorage()

  markLandingSeen(storage)

  assert.equal(storage.values.get(LANDING_SEEN_STORAGE_KEY), 'true')
  assert.equal(readLandingSeen(storage), true)
})

test("'true' 가 아닌 값은 보지 않은 것으로 읽는다", () => {
  for (const value of ['false', 'TRUE', '1', '', 'null', '{"seen":true}']) {
    const storage = new MemoryStorage()
    storage.setItem(LANDING_SEEN_STORAGE_KEY, value)

    assert.equal(readLandingSeen(storage), false, `값 ${JSON.stringify(value)}`)
  }
})

/*
  Storage 가 없거나 막힌 환경에서 예외를 밖으로 내보내면 진입 라우트가 통째로 죽는다.
  둘 다 "아직 보지 않음"으로 접어 랜딩을 보여주는 쪽으로 넘어진다 — 소개를 한 번 더
  보는 것은 손해가 아니지만 첫 화면이 비는 것은 손해다.
*/
test('Storage 가 없어도 보지 않은 것으로 읽는다', () => {
  assert.equal(readLandingSeen(null), false)
  assert.equal(readLandingSeen(undefined), false)
})

test('Storage 접근이 막혀 있어도 던지지 않는다', () => {
  const storage = new ThrowingStorage()

  assert.equal(readLandingSeen(storage), false)
  assert.doesNotThrow(() => markLandingSeen(storage))
})

test('랜딩을 본 적 없는 방문자는 소개 화면으로 간다', () => {
  assert.equal(landingEntryPath(new MemoryStorage()), INTRO_PATH)
})

test('랜딩을 본 방문자는 메인으로 간다', () => {
  const storage = new MemoryStorage()
  markLandingSeen(storage)

  assert.equal(landingEntryPath(storage), MAIN_PATH)
})

test('Storage 를 쓸 수 없으면 소개 화면으로 간다', () => {
  assert.equal(landingEntryPath(null), INTRO_PATH)
  assert.equal(landingEntryPath(new ThrowingStorage()), INTRO_PATH)
})

/*
  표식을 남기는 일과 로그인은 서로를 모른다. 세션 키를 지워도 랜딩을 다시 보여주지
  않는다 — 로그아웃했다고 소개를 다시 봐야 할 이유가 없다.
*/
test('세션 표식을 지워도 랜딩을 본 사실은 남는다', () => {
  const storage = new MemoryStorage()
  storage.setItem('gitjob.auth.session-identity.v1', 'user:42')
  markLandingSeen(storage)

  storage.values.delete('gitjob.auth.session-identity.v1')

  assert.equal(readLandingSeen(storage), true)
  assert.equal(landingEntryPath(storage), MAIN_PATH)
})

test('진입 판정의 두 결과는 서로 다른 경로다', () => {
  assert.notEqual(INTRO_PATH, MAIN_PATH)
})
