import { useQuery } from '@tanstack/react-query'
import {
  fetchMonitoringOverview,
  fetchMonitoringTimeseries,
} from '@/features/admin/monitoring/api/monitoringApi'
import type { TimeseriesMetric } from '@/features/admin/monitoring/api/monitoringApi'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 모니터링 화면의 조회 · 티켓 S15P21E102-210.
 *
 * 갱신 주기가 두 가지인 이유가 이 파일의 요점이다.
 *
 * 현재값(`overview`)은 30초마다 다시 읽는다. 확정 디자인의 Auto refresh 표기가 `ON · 30s`다.
 *
 * 시계열은 5분마다 읽는다. BE가 주는 범위가 60분·5분 step이므로 30초마다 다시 불러도
 * 같은 점이 돌아온다. 같은 답을 받으려고 관리자망 Prometheus에 열 배로 질의하는 것은
 * 화면에 아무 차이를 만들지 않는다.
 *
 * 재시도 횟수를 전역 기본값에 맡기지 않고 여기서 못 박는다. 운영 화면은 실패를 빨리
 * 드러내야 한다 — 조회가 실패했는데 화면이 계속 "불러오는 중"이면 운영자는 기다리면
 * 되는 상황인지 지금 손을 써야 하는 상황인지 알 수 없고, 그것은 장애를 감추는 것과
 * 같다. 어차피 주기 갱신이 있으므로 한 번 실패해도 다음 주기에 다시 시도한다.
 */

const OVERVIEW_REFRESH_MS = 30_000

/** BE `TimeRange.LAST_60M`의 step(5분)과 같다. 그보다 자주 읽으면 같은 점이 온다. */
const TIMESERIES_REFRESH_MS = 300_000

/** 한 번만 다시 시도하고 결과를 화면에 알린다. 지연도 짧게 둔다. */
const RETRY = { retry: 1, retryDelay: 800 } as const

function useTimeseries(metric: TimeseriesMetric, autoRefresh: boolean) {
  return useQuery({
    queryKey: queryKeys.monitoringTimeseries(metric),
    queryFn: () => fetchMonitoringTimeseries(metric),
    refetchInterval: autoRefresh ? TIMESERIES_REFRESH_MS : false,
    ...RETRY,
  })
}

/**
 * `autoRefresh`가 꺼지면 주기 갱신만 멈춘다. 이미 받은 값은 그대로 남는다 — 화면을
 * 비우면 운영자가 방금 보던 숫자를 잃는다.
 */
export function useSystemMonitoring(autoRefresh: boolean) {
  const overview = useQuery({
    queryKey: queryKeys.monitoringOverview(),
    queryFn: fetchMonitoringOverview,
    refetchInterval: autoRefresh ? OVERVIEW_REFRESH_MS : false,
    ...RETRY,
  })

  return {
    overview,
    cpu: useTimeseries('cpu', autoRefresh),
    memory: useTimeseries('memory', autoRefresh),
    network: useTimeseries('network', autoRefresh),
  }
}
