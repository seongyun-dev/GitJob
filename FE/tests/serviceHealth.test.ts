import assert from 'node:assert/strict'
import test from 'node:test'

import { serviceUpState } from '../src/features/admin/monitoring/model/serviceHealth.ts'
import type { ServiceHealthEvidence } from '../src/features/admin/monitoring/model/serviceHealth.ts'

const connected: ServiceHealthEvidence = {
  prometheusState: 'CONNECTED',
  kafkaUp: true,
  hdfsUp: true,
  sparkUp: true,
  liveDataNodes: 4,
  aliveWorkers: 2,
}

test('uses real per-service sources instead of host UP', () => {
  assert.equal(serviceUpState('prometheus', connected), true)
  assert.equal(serviceUpState('kafka', connected), true)
  assert.equal(serviceUpState('hdfs-namenode', connected), true)
  assert.equal(serviceUpState('spark-master', connected), true)
})

/*
  NameNode /jmx 와 Spark Master /json/ 이 이미 살아 있는 수를 준다(티켓 261 Phase 2·3).
  그 값이 있는데도 UNKNOWN 으로 두면 운영 화면이 아는 것을 모른다고 말하게 된다.
*/
test('derives DataNode and Worker from the counts already collected', () => {
  assert.equal(serviceUpState('hdfs-datanode', connected), true)
  assert.equal(serviceUpState('spark-worker', connected), true)
})

/*
  `0` 은 "모른다"가 아니라 "없다"이다. exporter 가 붙어 있는데 살아 있는 수가 0이면
  그것이 운영 화면이 가장 먼저 말해야 하는 사실이다.
*/
test('reports zero live nodes as down, not unknown', () => {
  assert.equal(serviceUpState('hdfs-datanode', { ...connected, liveDataNodes: 0 }), false)
  assert.equal(serviceUpState('spark-worker', { ...connected, aliveWorkers: 0 }), false)
})

test('keeps the counts unknown when the exporter has not answered', () => {
  assert.equal(serviceUpState('hdfs-datanode', { ...connected, liveDataNodes: null }), null)
  assert.equal(serviceUpState('spark-worker', { ...connected, aliveWorkers: null }), null)
})

/*
  dead 가 있어도 live 가 있으면 DataNode 계층은 동작 중이다. 부분 장애는 Data Platform
  카드의 `DataNode N개 · M down` 이 이미 말한다.
*/
test('one live DataNode is enough for the chip', () => {
  assert.equal(serviceUpState('hdfs-datanode', { ...connected, liveDataNodes: 1 }), true)
})

/*
  근거가 없는 서비스는 그대로 둔다. 호스트 node-exporter 가 UP 이라는 이유로 그 안의
  프로세스를 정상으로 칠하지 않는다.
*/
test('keeps services without an individual source unknown', () => {
  assert.equal(serviceUpState('backend', connected), null)
  assert.equal(serviceUpState('redis', connected), null)
  assert.equal(serviceUpState('grafana', connected), null)
  assert.equal(serviceUpState('collector', connected), null)
  assert.equal(serviceUpState('spark-c1-archiver', connected), null)
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
