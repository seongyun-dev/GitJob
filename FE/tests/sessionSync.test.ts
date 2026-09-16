import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient, QueryObserver } from '@tanstack/react-query'

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

class DeferredCancelQueryClient extends FakeQueryClient {
  readonly cancelResolvers: Array<() => void> = []

  override cancelQueries(): Promise<void> {
    this.calls.push('cancel')
    return new Promise((resolve) => this.cancelResolvers.push(resolve))
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
const userC = { ...userA, userId: '99', displayName: 'C' }

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

test('first observed session seeds identity without clearing a fresh query client', async () => {
  const storage = new MemoryStorage()
  const client = new FakeQueryClient()
  client.data.set(ME_QUERY_KEY.join('/'), userA)
  client.data.set('trends/public', { technologies: ['java'] })

  const changed = await synchronizeSessionCache(client, storage, userA)

  assert.equal(changed, false)
  assert.deepEqual(client.calls, [])
  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userA)
  assert.deepEqual(client.data.get('trends/public'), { technologies: ['java'] })
  assert.equal(storage.getItem(AUTH_SESSION_STORAGE_KEY), sessionIdentity(userA))
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

test('session replacement clears data held by an already subscribed screen', async () => {
  const client = new QueryClient()
  const queryKey = ['me', 'technologies'] as const
  client.setQueryData(queryKey, { privateRepository: 'A/private' })
  const observer = new QueryObserver(client, { queryKey, enabled: false })
  const notifications: unknown[] = []
  const unsubscribe = observer.subscribe((result) => notifications.push(result.data))

  await replaceSessionCache(client, userB)

  assert.equal(observer.getCurrentResult().data, undefined)
  assert.ok(notifications.includes(undefined))
  unsubscribe()
})

test('older direct me response cannot overwrite a newer session refresh', async () => {
  const client = new QueryClient()
  let resolveOlder!: (value: typeof userA) => void
  let resolveNewer!: (value: typeof userB) => void

  const olderRefresh = refreshSessionCache(
    client,
    () => new Promise((resolve) => (resolveOlder = resolve)),
  )
  await new Promise<void>((resolve) => setImmediate(resolve))
  const newerRefresh = refreshSessionCache(
    client,
    () => new Promise((resolve) => (resolveNewer = resolve)),
  )
  await new Promise<void>((resolve) => setImmediate(resolve))

  resolveNewer(userB)
  await newerRefresh
  resolveOlder(userA)
  await olderRefresh

  assert.equal(client.getQueryData(ME_QUERY_KEY), userB)
})

test('older known session replacement cannot overwrite a newer replacement', async () => {
  const client = new DeferredCancelQueryClient()

  const olderReplacement = replaceSessionCache(client, userA)
  const newerReplacement = replaceSessionCache(client, userB)
  client.cancelResolvers[1]()
  await newerReplacement
  client.cancelResolvers[0]()
  await olderReplacement

  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userB)
})

test('older synchronization cannot rewrite the shared identity after a newer user wins', async () => {
  const client = new DeferredCancelQueryClient()
  const storage = new MemoryStorage()
  await synchronizeSessionCache(client, storage, userA)

  const olderSynchronization = synchronizeSessionCache(client, storage, userB)
  const newerSynchronization = synchronizeSessionCache(client, storage, userC)
  client.cancelResolvers[1]()
  await newerSynchronization
  client.cancelResolvers[0]()
  await olderSynchronization

  assert.equal(storage.getItem(AUTH_SESSION_STORAGE_KEY), sessionIdentity(userC))
  assert.equal(client.data.get(ME_QUERY_KEY.join('/')), userC)
})
