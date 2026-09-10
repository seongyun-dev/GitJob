import type { MonitoringTimeseries } from '@/features/admin/monitoring/api/monitoringApi'

/**
 * 시계열 응답을 그래프 한 줄로 접는다 · 티켓 S15P21E102-210.
 *
 * BE는 서버별로 시계열을 준다. 확정 디자인의 그래프는 "전체 서버 평균"과 "두 서버 합산"
 * 한 줄씩이므로 접는 일이 필요하고, 그 규칙을 컴포넌트가 아니라 여기 둔다. 평균과 합계는
 * 데이터 가공이지 그리기가 아니다.
 *
 * 시각으로 맞춘다. 서버마다 점 개수가 다를 수 있어(한 서버가 늦게 올라온 경우) 배열
 * 순서로 짝지으면 다른 시각의 값이 더해진다.
 *
 * 값이 없는 시각은 만들지 않는다. 어떤 시각에 서버 하나만 값이 있으면 그 하나로 평균을
 * 낸다 — 없는 서버를 0으로 세면 평균이 실제보다 낮아진다.
 */

export interface ChartData {
  /** 그래프에 그릴 값. 시각 순서. */
  values: readonly number[]
  /** 같은 순서의 시각(ISO). 축 라벨을 만드는 데 쓴다. */
  times: readonly string[]
  /** 마지막 값. 없으면 `null`. */
  latest: number | null
}

const EMPTY: ChartData = { values: [], times: [], latest: null }

type Fold = 'AVERAGE' | 'SUM'

function fold(
  timeseries: MonitoringTimeseries | undefined,
  direction: string | null,
  mode: Fold,
): ChartData {
  if (timeseries === undefined || !timeseries.reachable) {
    return EMPTY
  }

  const selected = timeseries.series.filter((series) => series.direction === direction)
  if (selected.length === 0) {
    return EMPTY
  }

  const byTime = new Map<string, number[]>()
  for (const series of selected) {
    for (const point of series.points) {
      const bucket = byTime.get(point.at)
      if (bucket === undefined) {
        byTime.set(point.at, [point.value])
      } else {
        bucket.push(point.value)
      }
    }
  }

  const times = [...byTime.keys()].sort()
  const values = times.map((time) => {
    const bucket = byTime.get(time) ?? []
    const total = bucket.reduce((sum, value) => sum + value, 0)
    return mode === 'SUM' ? total : total / bucket.length
  })

  return {
    values,
    times,
    latest: values.at(-1) ?? null,
  }
}

/** 전체 서버 평균. 백분율 지표(cpu·memory)가 쓴다. */
export function averageAcrossServers(
  timeseries: MonitoringTimeseries | undefined,
): ChartData {
  return fold(timeseries, null, 'AVERAGE')
}

/** 전체 서버 합계. 처리량 지표(network)가 쓴다. */
export function sumAcrossServers(
  timeseries: MonitoringTimeseries | undefined,
  direction: 'receive' | 'transmit',
): ChartData {
  return fold(timeseries, direction, 'SUM')
}

/**
 * 축 라벨. 처음·중간·끝 몇 개만 남긴다.
 *
 * 12개 점의 시각을 다 적으면 좁은 화면에서 글자가 겹친다. 확정 디자인도 5개(CPU·Memory)와
 * 3개(Network)만 적는다.
 */
export function axisLabels(
  times: readonly string[],
  count: number,
  format: (iso: string) => string | null,
): readonly string[] {
  if (times.length === 0) {
    return []
  }
  if (times.length <= count) {
    return times.map((time) => format(time) ?? '')
  }
  const step = (times.length - 1) / (count - 1)
  return Array.from({ length: count }, (_, index) => {
    const time = times[Math.round(index * step)]
    return time === undefined ? '' : format(time) ?? ''
  })
}

/**
 * 처리량 그래프의 y축 상한.
 *
 * 데이터 최대값에 맞춰 눈금을 고른다. 상한을 고정하면 트래픽이 커질 때 선이 천장에
 * 붙어 변화가 보이지 않고, 데이터에 딱 맞추면 눈금이 매 갱신마다 흔들린다.
 *
 * 그리기가 아니라 데이터에서 나오는 값이라 `LineChart`가 아니라 여기 있다. 컴포넌트
 * 파일이 함수를 함께 내보내면 Fast Refresh도 동작하지 않는다.
 */
export function niceMax(values: readonly number[]): number {
  const peak = values.reduce((max, value) => (value > max ? value : max), 0)
  if (peak <= 0) {
    return 1
  }
  const magnitude = 10 ** Math.floor(Math.log10(peak))
  const normalized = peak / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return step * magnitude
}
