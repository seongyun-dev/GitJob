import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient, QueryObserver } from '@tanstack/react-query'

import {
  jobDemandStaleTime,
  marketPollInterval,
  MATCHING_PAGE_STALE_MS,
  matchingPageStaleTime,
  pollInterval,
} from '../src/features/matching/model/polling.ts'

const preparing = {
  dataStatus: 'PREPARING' as const,
  statusReason: 'COMPUTE_PENDING',
  retryAfterSec: 5,
}

test('matching polling stops when the latest request failed despite cached preparing data', () => {
  assert.equal(pollInterval(preparing, true), false)
})

test('matching polling follows the server delay only while preparing without an error', () => {
  assert.equal(pollInterval(preparing, false), 5_000)
  assert.equal(
    pollInterval({ ...preparing, retryAfterSec: null, statusReason: 'COHORT_NOT_PREPARED' }, false),
    30_000,
  )
  assert.equal(pollInterval({ ...preparing, dataStatus: 'READY' }, false), false)
})

/*
 * 시장 분포만 READY 에서도 다시 묻는다 · 티켓 S15P21E102-343.
 *
 * BE 는 `as_of` 를 보내지 않아 요청할 때마다 최신 canonical cutoff 를 고른다. 그래서
 * 다시 묻기만 하면 새 입력이 반영되는데, `pollInterval` 은 READY 가 되는 순간 멈춘다.
 * 화면을 열어 둔 사용자는 재진입 전까지 옛 숫자를 본다.
 *
 * 직무별 조회는 그대로 둔다. 개인 조건 결과는 사용자가 조건을 바꿀 때 바뀌지, 스스로
 * 바뀌지 않는다.
 */

test('market polling keeps asking after READY so a new cutoff is picked up', () => {
  assert.equal(marketPollInterval({ ...preparing, dataStatus: 'READY' }, false), 600_000)
})

test('market polling keeps the preparing cadence unchanged', () => {
  assert.equal(marketPollInterval(preparing, false), 5_000)
  assert.equal(
    marketPollInterval(
      { ...preparing, retryAfterSec: null, statusReason: 'COHORT_NOT_PREPARED' },
      false,
    ),
    30_000,
  )
})

test('market polling stops when the request itself failed', () => {
  // 세션 만료 같은 영구 4xx 에서 10분마다 계속 때리지 않는다.
  assert.equal(marketPollInterval({ ...preparing, dataStatus: 'READY' }, true), false)
  assert.equal(marketPollInterval(preparing, true), false)
})

test('market polling waits for the first response before scheduling', () => {
  assert.equal(marketPollInterval(undefined, false), false)
})

test('market polling retries the other terminal states slowly too', () => {
  // 새 cutoff 가 오면 FAILED·빈 결과도 값이 생긴다. 느리게 다시 묻는다.
  for (const dataStatus of ['FAILED', 'NO_DATA', 'PARTIAL', 'INSUFFICIENT_DATA'] as const) {
    assert.equal(marketPollInterval({ ...preparing, dataStatus }, false), 600_000)
  }
})

test('a prefetched READY matching page stays fresh when its observer mounts', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const queryKey = ['matching', 'postings', 'target', 2]
  let calls = 0
  const queryFn = async () => {
    calls += 1
    return { dataStatus: 'READY' as const }
  }

  await client.prefetchQuery({ queryKey, queryFn, staleTime: MATCHING_PAGE_STALE_MS })
  const observer = new QueryObserver(client, {
    queryKey,
    queryFn,
    staleTime: (query) => matchingPageStaleTime(query.state.data),
  })
  const unsubscribe = observer.subscribe(() => undefined)
  await new Promise<void>((resolve) => setImmediate(resolve))

  assert.equal(calls, 1)
  unsubscribe()
  client.clear()
})

test('a cached PREPARING demand refetches as soon as its observer remounts', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const queryKey = ['matching', 'demands', 'BACKEND']
  let calls = 0
  const queryFn = async () => {
    calls += 1
    return { dataStatus: 'PREPARING' as const }
  }

  await client.prefetchQuery({ queryKey, queryFn, staleTime: 60_000 })
  const observer = new QueryObserver(client, {
    queryKey,
    queryFn,
    staleTime: (query) => jobDemandStaleTime(query.state.data),
  })
  const unsubscribe = observer.subscribe(() => undefined)
  await new Promise<void>((resolve) => setImmediate(resolve))

  assert.equal(calls, 2)
  unsubscribe()
  client.clear()
})
