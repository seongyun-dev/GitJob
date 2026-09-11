/**
 * 지표 표기 · 티켓 S15P21E102-210.
 *
 * 모든 함수가 값이 없으면 `null`을 준다. 문자열 `'0'`이나 `'-'`를 여기서 만들지 않는
 * 이유는, 그러면 호출부가 "값이 없다"는 사실을 잃고 그대로 화면에 그리기 때문이다.
 * 없는 값을 어떻게 보일지는 `MetricValue`가 한곳에서 정한다.
 *
 * 단위 환산 기준은 1024가 아니라 1000이다. 확정 디자인의 "216 / 400 GB"가
 * `node_filesystem_size_bytes` 400GB 디스크를 그렇게 적고 있고, node-exporter가 주는
 * 값도 10진수 용량 표기와 맞물린다. 두 기준을 섞으면 같은 디스크가 화면과 콘솔에서
 * 다른 숫자로 보인다.
 */

const GIGA = 1_000_000_000
const MEGA = 1_000_000

/** `23.4` → `23%`. 소수점을 버리는 것은 디자인의 표기(`23%`)에 맞춘 것이다. */
export function formatPercent(value: number | null): string | null {
  if (value === null) {
    return null
  }
  return `${Math.round(value)}%`
}

/**
 * `23.4` → `23`. 단위 없이 숫자만. 디자인의 Server Detail이 `23` 크게 · `%` 작게 나눠
 * 그리므로, 그 자리에서는 `MetricValue`의 `unit`으로 `%`를 따로 붙인다.
 */
export function percentNumber(value: number | null): string | null {
  if (value === null) {
    return null
  }
  return String(Math.round(value))
}

/** `216000000000, 400000000000` → `216 / 400 GB`. 한쪽이라도 없으면 `null`. */
export function formatCapacity(
  usedBytes: number | null,
  totalBytes: number | null,
): string | null {
  if (usedBytes === null || totalBytes === null) {
    return null
  }
  return `${gigabytes(usedBytes)} / ${gigabytes(totalBytes)} GB`
}

/**
 * 100GB 미만은 소수 한 자리까지 보여준다. 메모리가 `6.6 / 16 GB`처럼 작은 값이라
 * 정수로 자르면 `7 / 16`이 되어 사용량이 실제보다 커 보인다.
 */
function gigabytes(bytes: number): string {
  const value = bytes / GIGA
  return value < 100 ? trimZero(value.toFixed(1)) : String(Math.round(value))
}

function trimZero(text: string): string {
  return text.endsWith('.0') ? text.slice(0, -2) : text
}

/** `6200000` → `6.2`. 단위(`MB/s`)는 호출부가 붙인다. */
export function megabytesPerSecond(bytesPerSecond: number | null): string | null {
  if (bytesPerSecond === null) {
    return null
  }
  return (bytesPerSecond / MEGA).toFixed(1)
}

/**
 * 네트워크 합계. IN·OUT 중 하나만 있으면 합계를 만들지 않는다 — 반쪽 합계는 실제보다
 * 작은 처리량을 주장한다.
 */
export function totalThroughput(
  receive: number | null,
  transmit: number | null,
): number | null {
  if (receive === null || transmit === null) {
    return null
  }
  return receive + transmit
}

/**
 * `2026-09-10T05:32:05Z` → `2026-09-10 14:32:05` (보는 사람의 시간대).
 *
 * 초까지 보여준다. 30초마다 갱신되는 값이라 분 단위로 끊으면 방금 갱신됐는지 아니면
 * 화면이 멈췄는지 구분되지 않는다.
 */
export function formatTimestamp(iso: string): string | null {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) {
    return null
  }
  const date = [at.getFullYear(), pad(at.getMonth() + 1), pad(at.getDate())].join('-')
  const time = [pad(at.getHours()), pad(at.getMinutes()), pad(at.getSeconds())].join(':')
  return `${date} ${time}`
}

/** `2026-09-10T05:32:05Z` → `14:32`. 그래프 축과 이벤트 목록이 쓴다. */
export function formatClock(iso: string): string | null {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) {
    return null
  }
  return `${pad(at.getHours())}:${pad(at.getMinutes())}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 초를 `15s` 같은 짧은 표기로. 값이 없으면 `null`. */
export function formatSeconds(seconds: number | null): string | null {
  if (seconds === null) {
    return null
  }
  return seconds % 60 === 0 && seconds >= 60 ? `${seconds / 60}m` : `${seconds}s`
}
