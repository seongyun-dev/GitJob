/**
 * 자원 사용률 임계치 · 티켓 S15P21E102-210.
 *
 * 확정 디자인 `GitJob Admin Monitoring v2`의 Server Detail 각주가 정한 값이다 —
 * "CPU/Memory 80% 주의 · 90% 경고 · Disk 85% 주의 · 90% 경고". 컴포넌트마다 숫자를
 * 박으면 화면 안에서 기준이 갈라지므로 한곳에 둔다.
 *
 * 서버가 판정해 주지 않는다. Prometheus alert rule은 아직 없고(Alertmanager 미도입)
 * BE 응답도 임계치를 싣지 않는다. 그래서 지금은 화면의 표시 규칙이며, alert rule이
 * 생기면 그쪽이 진실이 되고 이 파일은 그 값을 따라야 한다.
 */

/** 사용률 구간. 색과 문구를 고르는 데만 쓴다. */
export type UsageLevel = 'NORMAL' | 'WARNING' | 'CRITICAL'

interface Threshold {
  warning: number
  critical: number
}

export const CPU_MEMORY_THRESHOLD: Threshold = { warning: 80, critical: 90 }
export const DISK_THRESHOLD: Threshold = { warning: 85, critical: 90 }

function level(percent: number | null, threshold: Threshold): UsageLevel {
  if (percent === null) {
    return 'NORMAL'
  }
  if (percent >= threshold.critical) {
    return 'CRITICAL'
  }
  if (percent >= threshold.warning) {
    return 'WARNING'
  }
  return 'NORMAL'
}

export function cpuMemoryLevel(percent: number | null): UsageLevel {
  return level(percent, CPU_MEMORY_THRESHOLD)
}

export function diskLevel(percent: number | null): UsageLevel {
  return level(percent, DISK_THRESHOLD)
}

/**
 * 값이 없을 때 `NORMAL`을 주는 것은 "정상이다"라는 뜻이 아니라 "경고 색을 쓰지 말라"는
 * 뜻이다. 값 자체를 숫자로 그릴지 값 없음으로 그릴지는 `MetricValue`가 정한다.
 */
