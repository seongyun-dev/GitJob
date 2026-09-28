import assert from 'node:assert/strict'
import test from 'node:test'

import { createAppQueryClient } from '../src/app/queryClient.ts'

test('mutation failures use the same global error boundary as query failures', async () => {
  const expected = new Error('session expired')
  const observed: unknown[] = []
  const client = createAppQueryClient((error) => observed.push(error))
  const mutation = client.getMutationCache().build(client, {
    mutationFn: async () => {
      throw expected
    },
  })

  await assert.rejects(mutation.execute(undefined), expected)

  assert.deepEqual(observed, [expected])
})
