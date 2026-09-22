import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  defaultWhatIfImpactKind,
  whatIfHref,
} from '../src/features/matching/model/whatIfNavigation.ts'
import { matchingResultStaleTime } from '../src/features/matching/model/polling.ts'

function source(path: string): string {
  return readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
}

test('What-if default prefers required jobs, then preferred jobs, without summing overlap', () => {
  assert.equal(defaultWhatIfImpactKind({ requiredImpactCount: 3, preferredImpactCount: 7 }), 'REQUIRED')
  assert.equal(defaultWhatIfImpactKind({ requiredImpactCount: 0, preferredImpactCount: 7 }), 'PREFERRED')
  assert.equal(defaultWhatIfImpactKind({ requiredImpactCount: 0, preferredImpactCount: 0 }), 'ALL')
})

test('recommendation link carries the same non-empty default tab as What-if', () => {
  assert.equal(
    whatIfHref({ techId: 'spring-framework', requiredImpactCount: 0, preferredImpactCount: 2 }),
    '/what-if?tech=spring-framework&kind=PREFERRED',
  )
})

test('terminal recommendation results are cached, while preparing results still refetch', () => {
  assert.equal(matchingResultStaleTime({ dataStatus: 'READY' }), 60_000)
  assert.equal(matchingResultStaleTime({ dataStatus: 'PARTIAL' }), 60_000)
  assert.equal(matchingResultStaleTime({ dataStatus: 'PREPARING' }), 0)
})

test('matching cache identity is target-scoped, stays fresh on return, and is invalidated for a new analysis', () => {
  const keys = source('shared/api/queryKeys.ts')
  const hooks = source('features/matching/hooks/useMatching.ts')
  const selection = source('features/analysis/pages/RepositorySelectionPage.tsx')
  const progress = source('features/analysis/pages/AnalysisProgressPage.tsx')
  const session = source('features/auth/sessionSync.ts')

  assert.match(keys, /matchingRecommendations: \(targetKey: string\)[\s\S]*\['matching', targetKey, 'recommendations'\]/)
  assert.match(hooks, /queryKey: queryKeys\.matchingRecommendations\(targetKey \?\? ''\),[\s\S]*staleTime: \(query\) => matchingResultStaleTime\(query\.state\.data\)/)
  assert.match(selection, /invalidateQueries\(\{ queryKey: \['matching'\] \}\)/)
  assert.match(progress, /invalidateQueries\(\{ queryKey: \['matching'\] \}\)/)
  assert.match(session, /clearSessionQueries\(queryClient\)/)
})
