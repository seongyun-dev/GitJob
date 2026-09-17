import assert from 'node:assert/strict'
import test from 'node:test'

import type { Me } from '../src/features/auth/api/me.ts'
import { analysisStartMode } from '../src/features/landing/model/analysisStart.ts'

const user: Me = {
  userId: '42',
  displayName: '륜영',
  avatarUrl: null,
  githubConnected: true,
  role: 'USER',
}

test('landing analysis CTA waits until session lookup is settled', () => {
  assert.equal(analysisStartMode(undefined), 'CHECKING')
})

test('landing analysis CTA starts OAuth only for anonymous users', () => {
  assert.equal(analysisStartMode(null), 'GITHUB_LOGIN')
})

test('landing analysis CTA sends authenticated users to repository selection', () => {
  assert.equal(analysisStartMode(user), 'REPOSITORY_SELECTION')
})

test('landing analysis CTA sends a signed-in user without GitHub credentials to reconnect', () => {
  assert.equal(analysisStartMode({ ...user, githubConnected: false }), 'GITHUB_CONNECT')
})
