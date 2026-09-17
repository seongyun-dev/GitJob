import assert from 'node:assert/strict'
import test from 'node:test'

import { serviceUpState } from '../src/features/admin/monitoring/model/serviceHealth.ts'
import type { ServiceHealthEvidence } from '../src/features/admin/monitoring/model/serviceHealth.ts'

const connected: ServiceHealthEvidence = {
  prometheusState: 'CONNECTED',
  kafkaUp: true,
  hdfsUp: true,
  sparkUp: true,
}

test('uses real per-service sources instead of host UP', () => {
  assert.equal(serviceUpState('prometheus', connected), true)
  assert.equal(serviceUpState('kafka', connected), true)
  assert.equal(serviceUpState('hdfs-namenode', connected), true)
  assert.equal(serviceUpState('spark-master', connected), true)
})

test('keeps services without an individual source unknown', () => {
  assert.equal(serviceUpState('backend', connected), null)
  assert.equal(serviceUpState('redis', connected), null)
  assert.equal(serviceUpState('grafana', connected), null)
  assert.equal(serviceUpState('hdfs-datanode', connected), null)
  assert.equal(serviceUpState('spark-worker', connected), null)
  assert.equal(serviceUpState('collector', connected), null)
})

test('preserves unavailable and not-configured Prometheus states', () => {
  assert.equal(
    serviceUpState('prometheus', { ...connected, prometheusState: 'UNREACHABLE' }),
    false,
  )
  assert.equal(
    serviceUpState('prometheus', { ...connected, prometheusState: 'NOT_CONFIGURED' }),
    null,
  )
  assert.equal(serviceUpState('kafka', { ...connected, kafkaUp: null }), null)
})
