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
  backendUp: true,
  grafanaUp: true,
}

/** source 가 아직 운영에 붙지 않은 상태. BE 가 두 자리를 모두 `null` 로 준다. */
const withoutServiceSources: ServiceHealthEvidence = {
  ...connected,
  backendUp: null,
  grafanaUp: null,
}

/** 아직 개별 source 가 없어 후속 작업으로 분리한 칩들. */
const STILL_UNKNOWN = ['redis', 'collector', 'spark-c1-archiver'] as const

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
  for (const id of STILL_UNKNOWN) {
    assert.equal(serviceUpState(id, connected), null, id)
  }
})

/*
  티켓 -321. Backend 와 Grafana 는 근거가 서로 다르지만 화면에서는 같은 점 하나다.
  값이 오면 그대로 옮기고, 여기서 다시 판정하지 않는다.
*/
test('paints Backend and Grafana from their own sources', () => {
  assert.equal(serviceUpState('backend', connected), true)
  assert.equal(serviceUpState('grafana', connected), true)
})

test('reports a failing Backend or Grafana as down', () => {
  assert.equal(serviceUpState('backend', { ...connected, backendUp: false }), false)
  assert.equal(serviceUpState('grafana', { ...connected, grafanaUp: false }), false)
})

/*
  Grafana 의 scrape config 가 아직 운영에 반영되지 않았으면 BE 가 `null` 을 준다. 그것은
  "Grafana 가 죽었다"가 아니라 "아직 재본 적이 없다"이므로 회색이어야 한다. 반영 전 상태를
  DOWN 으로 그리면 운영자를 헛되이 부른다.
*/
test('a Grafana source that does not exist yet is unknown, not down', () => {
  assert.equal(serviceUpState('grafana', { ...connected, grafanaUp: null }), null)
})

test('an Actuator that cannot tell leaves Backend unknown', () => {
  assert.equal(serviceUpState('backend', { ...connected, backendUp: null }), null)
})

/*
  한 칩의 source 가 비어도 다른 칩은 영향을 받지 않는다. 같은 묶음으로 오지만 근거는
  서로 다르다.
*/
test('one missing source does not grey out the other', () => {
  const onlyGrafanaMissing = { ...connected, grafanaUp: null }

  assert.equal(serviceUpState('grafana', onlyGrafanaMissing), null)
  assert.equal(serviceUpState('backend', onlyGrafanaMissing), true)
})

/*
  -319 가 붙인 여섯 칩은 -321 의 값과 무관해야 한다. services 가 통째로 비어도
  Prometheus·Kafka·HDFS·Spark 칩은 그대로다.
*/
test('does not regress the six chips connected earlier', () => {
  for (const id of [
    'prometheus',
    'kafka',
    'hdfs-namenode',
    'hdfs-datanode',
    'spark-master',
    'spark-worker',
  ]) {
    assert.equal(serviceUpState(id, withoutServiceSources), true, id)
  }
})

/*
  후속 작업으로 분리한 셋은 services 값과 무관하게 계속 회색이다. 이번 티켓이 그 셋을
  실수로 칠하지 않는지 고정한다.
*/
test('the deferred three stay unknown whatever the rest says', () => {
  for (const id of STILL_UNKNOWN) {
    assert.equal(serviceUpState(id, withoutServiceSources), null, `${id} without sources`)
    assert.equal(serviceUpState(id, connected), null, `${id} with sources`)
  }
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

test('an unknown chip id is never painted', () => {
  assert.equal(serviceUpState('mystery-service', connected), null)
})
