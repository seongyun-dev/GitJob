import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient } from '@tanstack/react-query'

import {
  AUTH_SESSION_STORAGE_KEY,
  ME_QUERY_KEY,
  isSessionChangeEvent,
  sessionIdentity,
  storeSessionIdentity,
  replaceSessionCache,
  refreshSessionCache,
  synchronizeSessionCache,
} from '../src/features/auth/sessionSync.ts'

class MemoryStorage {
  private values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

class FakeQueryClient {
  readonly calls: string[] = []
  readonly data = new Map<string, unknown>()

  async cancelQueries(): Promise<void> {
    this.calls.push('cancel')
  }

  clear(): void {
    this.calls.push('clear')
    this.data.clear()
  }

  setQueryData(key: readonly string[], value: unknown): void {
    this.calls.push(`set:${key.join('/')}`)
    this.data.set(key.join('/'), value)
  }
}

const userA = {
  userId: '42',
  displayName: 'A',
  avatarUrl: null,
  githubConnected: true,
  role: 'USER' as const,
}

const userB = { ...userA, userId: '77', displayName: 'B' }

test('stable user id distinguishes sessions even when display data is unchanged', () => {
  assert.equal(sessionIdentity(userA), 'user:42')
  assert.equal(sessionIdentity({ ...userA, userId: '77' }), 'user:77')
  assert.equal(sessionIdentity(null), 'anonymous')
})

test('identity storage changes only when the authenticated user changes', () => {
  const storage = new MemoryStorage()

  assert.equal(storeSessionIdentity(storage, userA), true)
  assert.equal(storeSessionIdentity(storage, { ...userA, displayName: 'renamed' }), false)
  assert.equal(storeSessionIdentity(storage, userB), true)
})

test('only a changed identity event from the shared storage triggers cross-tab reset', () => {
  const storage = new MemoryStorage()
  const event = {
    storageArea: storage,
    key: AUTH_SESSION_STORAGE_KEY,
    oldValue: 'user:42',
    newValue: 'user:77',
  }

  assert.equal(isSessionChangeEvent(event, storage), true)
  assert.equal(isSessionChangeEvent({ ...event, key: 'unrelated' }, storage), false)
  assert.equal(isSessionChangeEvent({ ...event, newValue: event.oldValue }, storage), false)
  assert.equal(isSessionChangeEvent({ ...event, storageArea: new MemoryStorage() }, storage), false)
})

test('known session replacement cancels pending requests before removing prior-user data', async () => {
  const client = new FakeQueryClient()
  client.data.set('me/technologies', { privateRepository: 'A/private' })

  await replaceSessionCache(client, userB)

  assert.deepEqual(client.calls, ['cancel', 'clear', `set:${ME_QUERY_KEY.join('/')}`])
  assert.equal(client.data.has('me/technologies'), false)
  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userB)
})

test('missed storage event still clears stale cache when me changes to another user', async () => {
  const storage = new MemoryStorage()
  const client = new FakeQueryClient()
  await synchronizeSessionCache(client, storage, userA)
  client.calls.length = 0
  client.data.set('me/technologies', { privateRepository: 'A/private' })

  // 다른 탭이 이미 B를 기록했지만 이 탭은 storage 이벤트를 놓친 상황이다.
  storage.setItem(AUTH_SESSION_STORAGE_KEY, sessionIdentity(userB))
  const changed = await synchronizeSessionCache(client, storage, userB)

  assert.equal(changed, true)
  assert.deepEqual(client.calls, ['cancel', 'clear', `set:${ME_QUERY_KEY.join('/')}`])
  assert.equal(client.data.has('me/technologies'), false)
  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userB)
})

test('external tab session event clears prior data and reloads the current cookie owner', async () => {
  const client = new FakeQueryClient()
  client.data.set('me/technologies', { privateRepository: 'A/private' })

  await refreshSessionCache(client, async () => userB)

  assert.deepEqual(client.calls, [
    'cancel',
    'clear',
    `set:${ME_QUERY_KEY.join('/')}`,
    `set:${ME_QUERY_KEY.join('/')}`,
  ])
  assert.equal(client.data.has('me/technologies'), false)
  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userB)
})

test('real query client ignores a prior-user response that completes after session replacement', async () => {
  const client = new QueryClient()
  let resolveOldRequest!: (value: unknown) => void
  const oldRequest = client.fetchQuery({
    queryKey: ['me', 'technologies'],
    queryFn: () =>
      new Promise((resolve) => {
        resolveOldRequest = resolve
      }),
  })

  await replaceSessionCache(client, userB)
  resolveOldRequest({ privateRepository: 'A/private' })
  await oldRequest.catch(() => undefined)

  assert.equal(client.getQueryData(['me', 'technologies']), undefined)
  assert.equal(client.getQueryData(ME_QUERY_KEY), userB)
})
