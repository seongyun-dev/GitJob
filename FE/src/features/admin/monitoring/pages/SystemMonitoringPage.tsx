import { useState } from 'react'
import { toMonitoringView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import { DataPlatformCards } from '@/features/admin/monitoring/components/DataPlatformCards'
import { DiskCapacity } from '@/features/admin/monitoring/components/DiskCapacity'
import { InfrastructureMap } from '@/features/admin/monitoring/components/InfrastructureMap'
import { QuickAccessPanel } from '@/features/admin/monitoring/components/QuickAccessPanel'
import { RecentEvents } from '@/features/admin/monitoring/components/RecentEvents'
import { ResourceOverview } from '@/features/admin/monitoring/components/ResourceOverview'
import { ServerDetailTable } from '@/features/admin/monitoring/components/ServerDetailTable'
import { SystemSummary } from '@/features/admin/monitoring/components/SystemSummary'
import { useSystemMonitoring } from '@/features/admin/monitoring/hooks/useSystemMonitoring'
import { PROMETHEUS_STATE_DISPLAY } from '@/features/admin/monitoring/model/monitoringState'
import { GITJOB_TOPOLOGY } from '@/features/admin/monitoring/model/topology.config'
import { formatTimestamp } from '@/features/admin/monitoring/ui/formatMetric'
import { ApiError } from '@/shared/api/client'
import { StateCard } from '@/shared/ui/StateCard'
import { PageHero } from '@/shared/ui/PageHero'

/**
 * Admin System Monitoring · 티켓 S15P21E102-210.
 *
 * Admin의 기본 진입 화면이다. 확정 디자인 `GitJob Admin Monitoring v2`의 여덟 섹션을
 * 그 순서로 배치한다.
 *
 * 지표는 전부 실제 값이다. BE가 Prometheus에서 읽어 준다(티켓 209). 아직 수집되지 않는
 * 범위(HDFS·Spark·Collector·Kafka topic 상세)만 상태로 표시하고, 그 자리에 그럴듯한
 * 숫자를 만들지 않는다.
 *
 * 화면이 인프라 구조를 알지 않는다. 서버 수와 서비스 배치는 `model/topology.config.ts`가
 * 정하고 이 파일은 순회만 한다.
 */

/** 확정 디자인의 `ON · 30s`. 실제 주기는 `useSystemMonitoring`이 갖는다. */
const REFRESH_LABEL = '30s'

function AutoRefreshToggle({
  enabled,
  onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={enabled}
      className={`inline-flex h-10 items-center gap-2 rounded-[11px] border px-3.5 text-[13px] font-bold transition-colors ${
        enabled
          ? 'border-brand-line-active bg-tone-accent-bg text-brand-600'
          : 'border-brand-line bg-white text-brand-muted'
      }`}
    >
      <span
        className={`size-2 rounded-full ${enabled ? 'bg-tone-success' : 'bg-brand-box'}`}
        aria-hidden
      />
      Auto refresh {enabled ? `ON · ${REFRESH_LABEL}` : 'OFF'}
    </button>
  )
}

/**
 * 조회 자체가 실패했을 때.
 *
 * Prometheus 미연결과 다른 상황이다. 이쪽은 BE에 닿지 못했거나 권한이 없는 것이고,
 * 그때는 화면에 그릴 값이 아무것도 없다. 권한 문제를 일반 오류와 같은 문구로 보여주면
 * 관리자 계정으로 다시 들어오라는 안내를 놓친다.
 */
function LoadFailure({ error }: { error: unknown }) {
  const forbidden =
    error instanceof ApiError && (error.status === 401 || error.status === 403)

  return (
    <StateCard
      kind="ERROR"
      title={forbidden ? '관리자 권한이 필요합니다' : '모니터링 정보를 불러오지 못했습니다'}
      description={
        forbidden
          ? '이 화면은 관리자 계정만 볼 수 있습니다. 관리자로 로그인한 뒤 다시 열어 주세요.'
          : error instanceof ApiError
            ? error.message
            : '잠시 후 다시 시도해 주세요.'
      }
      meta={error instanceof ApiError ? error.code : undefined}
    />
  )
}

export function SystemMonitoringPage() {
  const [autoRefresh, setAutoRefresh] = useState(true)
  const { overview, cpu, memory, network } = useSystemMonitoring(autoRefresh)

  const view =
    overview.data === undefined ? null : toMonitoringView(GITJOB_TOPOLOGY, overview.data)
  const lastRefresh = view === null ? null : formatTimestamp(view.updatedAt)

  /*
   * 실패가 대기보다 우선한다.
   *
   * `isPending`만 보고 로딩을 그리면 화면이 영원히 "불러오는 중"에 머무를 수 있다.
   * 재조회가 걸린 쿼리는 데이터가 없는 동안 다시 pending이 되므로, 직전 시도가 실패한
   * 사실이 로딩 문구에 가려진다. 운영 화면에서 무한 로딩은 실패를 감추는 것과 같다 —
   * 운영자는 기다리면 되는 상황인지, 지금 손을 써야 하는 상황인지 알아야 한다.
   *
   * 그래서 값이 없고 오류가 남아 있으면 오류를 보여준다. `error`는 다음 재조회가
   * 성공할 때까지 남아 있으므로, 재시도 중에도 마지막 결과가 정직하게 보인다.
   */
  const failure = overview.data === undefined ? overview.error : null

  /*
   * 브라우저가 오프라인으로 판정되면 react-query는 요청을 보내지 않고 쿼리를 멈춘다
   * (`fetchStatus === 'paused'`, `failureCount === 0`). 기본 `networkMode: 'online'`의
   * 동작이며 연결이 돌아오면 자동으로 재개된다.
   *
   * 이때 "Prometheus에서 읽고 있습니다"를 계속 띄우면 거짓이다. 요청은 나가지도 않았고,
   * 고쳐야 할 것은 서버가 아니라 이 브라우저의 연결이다. 운영 화면에서 원인을 잘못
   * 가리키는 로딩 문구는 없는 장애를 찾게 만든다.
   */
  const waitingForNetwork = overview.fetchStatus === 'paused'

  return (
    // 섹션 간격은 확정 디자인의 리듬을 따른다. hero→카드 28 · 카드→지도 28 · 지도→차트 16 ·
    // 차트→디테일 12 · 디테일→Server Detail 28 · →Data Platform 28. 균일한 gap 하나로 두면
    // 디자인이 묶어 둔 것(차트·디테일)과 떼어 둔 것(섹션)이 같은 거리로 보인다.
    <section>
      <PageHero
        eyebrow="SYSTEM MONITORING"
        title="시스템 운영 상태"
        description="서비스와 데이터 인프라 상태를 한눈에 확인합니다."
        aside={
          <div className="flex items-center gap-3.5">
            <p className="text-right text-[12.5px] leading-[1.6] text-brand-faint">
              마지막 갱신
              <br />
              <b className="font-[750] text-brand-ink-soft tabular-nums">
                {lastRefresh ?? '—'}
              </b>
            </p>
            <AutoRefreshToggle
              enabled={autoRefresh}
              onToggle={() => setAutoRefresh((previous) => !previous)}
            />
          </div>
        }
      />

      {failure !== null && (
        <div className="mt-7">
          <LoadFailure error={failure} />
        </div>
      )}

      {view === null && failure === null && (
        <div className="mt-7">
          <StateCard
            kind="LOADING"
            title={
              waitingForNetwork
                ? '네트워크 연결을 기다리는 중입니다'
                : '운영 상태를 불러오는 중입니다'
            }
            description={
              waitingForNetwork
                ? '이 브라우저가 오프라인으로 판정되어 요청을 보내지 못했습니다. 연결이 돌아오면 자동으로 다시 조회합니다.'
                : 'Prometheus에서 서버 지표와 수집 상태를 읽고 있습니다.'
            }
          />
        </div>
      )}

      {view !== null && (
        <>
          {/*
            Prometheus가 연결되지 않았으면 그 사실을 화면 맨 위에서 말한다. 아래 섹션들이
            비어 있는 이유가 여기 있고, 이것을 각 섹션의 빈 카드로만 알리면 운영자는
            섹션마다 원인을 짐작해야 한다.

            도메인 상태를 그대로 보여준다 — 미설정(배포 담당자)과 연결 실패(운영자)는
            고칠 사람이 다르다.
          */}
          {!view.reachable && (
            <div
              className="mt-7 rounded-[18px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
              role="alert"
            >
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-[15px] font-[750] text-brand-ink">
                  {PROMETHEUS_STATE_DISPLAY[view.state].label}
                </span>
                <code className="font-evidence rounded-[5px] bg-tone-neutral-bg px-1.5 py-0.5 text-[11px] font-bold text-tone-neutral">
                  {view.state}
                </code>
              </div>
              <p className="mt-1.5 text-[13px] leading-[1.6] text-brand-muted">
                {PROMETHEUS_STATE_DISPLAY[view.state].description}
              </p>
            </div>
          )}

          {/* hero → 요약 카드 28 */}
          <div className="mt-7">
            <SystemSummary view={view} />
          </div>
          {/* 요약 카드 → 지도 28 */}
          <div className="mt-7">
            <InfrastructureMap view={view} />
          </div>
          {/* 지도 → 차트 16 · 차트 → 디테일 12. 디자인이 이 둘을 한 묶음으로 가깝게 둔다. */}
          <div className="mt-4">
            <ResourceOverview cpu={cpu.data} memory={memory.data} network={network.data} />
          </div>
          <div className="gj-mon-detail mt-3">
            <DiskCapacity view={view} />
            <RecentEvents />
          </div>

          {/* → Server Detail 28 (디자인 `margin:28px 4px 12px`의 28) */}
          <div className="mt-7">
            <ServerDetailTable view={view} />
          </div>

          {/* → Data Platform · Quick Access 28 */}
          <div className="gj-split mt-7">
            <DataPlatformCards
              coverage={view.coverage}
              kafka={view.kafka}
              hdfs={view.hdfs}
              spark={view.spark}
              dataStore={view.dataStore}
            />
            <QuickAccessPanel links={view.links} />
          </div>
        </>
      )}
    </section>
  )
}
