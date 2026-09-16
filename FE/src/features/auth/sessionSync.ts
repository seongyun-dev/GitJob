import type { Me } from '@/features/auth/api/me'

/** 다른 탭까지 공유하는 현재 세션 소유자 표식. 토큰이나 프로필 정보는 저장하지 않는다. */
export const AUTH_SESSION_STORAGE_KEY = 'gitjob.auth.session-identity.v1'
export const ME_QUERY_KEY = ['auth', 'me'] as const

interface IdentityStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

interface SessionStorageEvent {
  storageArea: IdentityStorage | null
  key: string | null
  oldValue: string | null
  newValue: string | null
}

interface SessionQueryClient {
  cancelQueries(): Promise<void>
  clear(): void
  setQueryData(queryKey: readonly string[], value: Me | null): unknown
}

/** 각 탭의 메모리 캐시가 실제로 어느 세션을 담는지 추적한다. */
const queryClientIdentities = new WeakMap<object, string>()

/** 이름·아바타가 같아도 계정을 구분할 수 있는 서버 발급 식별자를 쓴다. */
export function sessionIdentity(me: Pick<Me, 'userId'> | null): string {
  return me === null ? 'anonymous' : `user:${me.userId}`
}

/** 값이 실제로 바뀔 때만 저장해 다른 탭에 storage 이벤트를 전파한다. */
export function storeSessionIdentity(
  storage: IdentityStorage,
  me: Pick<Me, 'userId'> | null,
): boolean {
  const next = sessionIdentity(me)
  if (storage.getItem(AUTH_SESSION_STORAGE_KEY) === next) {
    return false
  }
  storage.setItem(AUTH_SESSION_STORAGE_KEY, next)
  return true
}

/** 이 앱의 실제 세션 소유자가 바뀐 storage 이벤트만 받는다. */
export function isSessionChangeEvent(
  event: SessionStorageEvent,
  storage: IdentityStorage,
): boolean {
  return (
    event.storageArea === storage &&
    event.key === AUTH_SESSION_STORAGE_KEY &&
    event.newValue !== event.oldValue
  )
}

/**
 * 현재 탭이 이미 확인한 세션으로 캐시를 교체한다.
 * 이전 계정 요청을 먼저 취소해야 늦은 응답이 clear 뒤에 다시 들어오지 않는다.
 */
export async function replaceSessionCache(
  queryClient: SessionQueryClient,
  me: Me | null,
): Promise<void> {
  queryClientIdentities.set(queryClient, sessionIdentity(me))
  await queryClient.cancelQueries()
  queryClient.clear()
  queryClient.setQueryData(ME_QUERY_KEY, me)
}

/**
 * 현재 탭의 /me 결과와 메모리 캐시 소유자를 맞추고, 변경을 다른 탭에 알린다.
 * 공유 storage 값이 이미 새 사용자여도 이 탭의 메모리 캐시가 이전 사용자라면 교체한다.
 */
export async function synchronizeSessionCache(
  queryClient: SessionQueryClient,
  storage: IdentityStorage,
  me: Me | null,
): Promise<boolean> {
  const next = sessionIdentity(me)
  const cacheChanged = queryClientIdentities.get(queryClient) !== next
  if (cacheChanged) {
    await replaceSessionCache(queryClient, me)
  }
  storeSessionIdentity(storage, me)
  return cacheChanged
}

/** 다른 탭의 세션 변경을 받으면 쿠키의 현재 소유자를 다시 읽는다. */
export async function refreshSessionCache(
  queryClient: SessionQueryClient,
  loadMe: () => Promise<Me | null>,
): Promise<void> {
  await queryClient.cancelQueries()
  queryClient.clear()
  // 재조회 중에는 이전 사용자의 헤더도 남기지 않는다.
  queryClient.setQueryData(ME_QUERY_KEY, null)
  queryClientIdentities.set(queryClient, sessionIdentity(null))
  try {
    const me = await loadMe()
    queryClient.setQueryData(ME_QUERY_KEY, me)
    queryClientIdentities.set(queryClient, sessionIdentity(me))
  } catch {
    // 사용자 범위 캐시는 이미 제거됐다. 다음 /me refetch가 세션을 다시 확정한다.
  }
}
