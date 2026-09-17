import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatThroughput,
  throughput,
  totalThroughput,
} from '../src/features/admin/monitoring/ui/formatMetric.ts'

/**
 * 처리량 표기 · 티켓 S15P21E102-292.
 *
 * 실측 관리망 트래픽(IN 약 2 KB/s · OUT 약 3 KB/s)이 MB/s 고정 표기에서 전부 `0.0`으로
 * 보였다. 경계값을 고정해 두는 이유는, 이 화면에서 가장 위험한 버그가 예외가 아니라
 * 조용한 0이기 때문이다 — 0.0은 "측정했더니 트래픽이 없다"로 읽힌다.
 */

test('값이 없으면 null을 준다', () => {
  assert.equal(throughput(null), null)
  assert.equal(formatThroughput(null), null)
})

test('진짜 0만 0.0 KB/s다', () => {
  assert.deepEqual(throughput(0), { value: '0.0', unit: 'KB/s' })
})

test('1 MB/s 미만은 KB/s로 내린다', () => {
  assert.deepEqual(throughput(500), { value: '0.5', unit: 'KB/s' })
  assert.deepEqual(throughput(2_000), { value: '2.0', unit: 'KB/s' })
  assert.deepEqual(throughput(999_000), { value: '999.0', unit: 'KB/s' })
  assert.deepEqual(throughput(999_949), { value: '999.9', unit: 'KB/s' })
})

test('KB/s로도 0.0이 되는 0이 아닌 값은 0과 구분한다', () => {
  assert.deepEqual(throughput(1), { value: '<0.1', unit: 'KB/s' })
  assert.deepEqual(throughput(49), { value: '<0.1', unit: 'KB/s' })
  assert.deepEqual(throughput(50), { value: '0.1', unit: 'KB/s' })
})

test('1 MB/s부터 MB/s를 쓴다', () => {
  assert.deepEqual(throughput(1_000_000), { value: '1.0', unit: 'MB/s' })
  assert.deepEqual(throughput(6_200_000), { value: '6.2', unit: 'MB/s' })
})

test('한 줄 표기는 숫자와 단위를 붙여 준다', () => {
  assert.equal(formatThroughput(2_000), '2.0 KB/s')
  assert.equal(formatThroughput(6_200_000), '6.2 MB/s')
})

test('실측 관리망 값이 0.0으로 보이지 않는다', () => {
  // ens5 기준 IN 약 2 KB/s · OUT 약 3 KB/s (S15P21E102-292 Production 측정).
  assert.equal(formatThroughput(2_048), '2.0 KB/s')
  assert.equal(formatThroughput(3_072), '3.1 KB/s')
  assert.equal(formatThroughput(totalThroughput(2_048, 3_072)), '5.1 KB/s')
})

test('합계는 한쪽이 없으면 만들지 않는다', () => {
  assert.equal(totalThroughput(2_048, null), null)
  assert.equal(totalThroughput(null, 3_072), null)
  assert.equal(totalThroughput(2_048, 3_072), 5_120)
})
