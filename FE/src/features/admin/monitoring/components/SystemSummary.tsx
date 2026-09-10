import type { ReactNode } from 'react'
import { serverUpState } from '@/features/admin/monitoring/adapter/toMonitoringView'
import type { MonitoringView } from '@/features/admin/monitoring/adapter/toMonitoringView'
import { cpuMemoryLevel } from '@/features/admin/monitoring/model/thresholds'
import { formatPercent, formatSeconds } from '@/features/admin/monitoring/ui/formatMetric'
import { MetricValue } from '@/features/admin/monitoring/ui/MetricValue'
import {
  PrometheusStateBadge,
  UpBadge,
} from '@/features/admin/monitoring/ui/StatusBadge'
import { Pill } from '@/shared/ui/Pill'

/**
 * System Summary · 티켓 S15P21E102-210.
 *
 * 카드 수가 고정 4가 아니다. 서버 카드는 topology config가 정하고 거기에 Prometheus와
 * Grafana 카드가 붙는다. 현재 구성(서버 2대)에서 4장이 되어 확정 디자인의
 * `repeat(4,1fr)`과 같아지지만, 서버가 3대가 되면 5장이 되어 다음 줄로 넘어간다.
 * 카드를 늘리지 않고 서버 수를 고정하는 쪽이 더 위험하다.
 *
 * 배치는 `index.css`의 `.gj-stats`를 쓴다. 확정 디자인 v2의 지표 행과 같은 격자다.
 */

function SummaryCard({
  name,
  badge,
  metrics,
  description,
}: {
  name: string
  badge: ReactNode
  metrics: readonly { label: string; value: ReactNode }[]
  description: string
}) {
  return (
    <div className="flex flex-col rounded-[18px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex items-center justify-between gap-2.5">
        <span className="truncate text-[14px] font-[750] text-brand-ink">{name}</span>
        {badge}
      </div>
      <div className="mt-3.5 flex gap-5">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <p className="text-[11.5px] text-brand-faint">{metric.label}</p>
            <div className="mt-1">{metric.value}</div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[12px] leading-[1.5] text-brand-faint">{description}</p>
    </div>
  )
}

export function SystemSummary({ view }: { view: MonitoringView }) {
  return (
    <div className="gj-stats">
      {view.servers.map((server) => {
        const metrics = server.metrics
        const up = serverUpState(view, server)
        return (
          <SummaryCard
            key={server.node.id}
            name={server.node.name}
            badge={<UpBadge up={up} />}
            metrics={[
              {
                label: 'CPU',
                value: (
                  <MetricValue
                    text={formatPercent(metrics?.cpuPercent ?? null)}
                    level={cpuMemoryLevel(metrics?.cpuPercent ?? null)}
                  />
                ),
              },
              {
                label: 'Memory',
                value: (
                  <MetricValue
                    text={formatPercent(metrics?.memoryPercent ?? null)}
                    level={cpuMemoryLevel(metrics?.memoryPercent ?? null)}
                  />
                ),
              },
            ]}
            // 서비스 목록은 config가 준다. 여기서 이름을 적으면 Kafka가 옮겨갈 때
            // 이 파일을 고쳐야 한다.
            description={`${server.node.displayName} · ${server.node.services
              .map((service) => service.label)
              .join(' · ')}`}
          />
        )
      })}

      <SummaryCard
        name={view.monitoring.label}
        badge={<PrometheusStateBadge state={view.state} />}
        metrics={[
          {
            label: 'Targets',
            value: (
              <MetricValue
                text={view.targets === null ? null : `${view.targets.up}/${view.targets.total}`}
              />
            ),
          },
          {
            label: 'Scrape',
            value: <MetricValue text={formatSeconds(view.scrapeIntervalSeconds)} />,
          },
        ]}
        description={
          view.targets === null
            ? '수집 상태를 읽지 못했습니다.'
            : view.targets.up === view.targets.total
              ? '등록된 모든 target을 수집하고 있습니다.'
              : `${view.targets.total - view.targets.up}개 target이 응답하지 않습니다.`
        }
      />

      {/*
        Grafana 카드.

        확정 디자인은 "Dashboards 4 · Datasource OK"를 보여주지만 그 값은 Grafana API를
        호출해야 얻는다. 이번 범위(Prometheus proxy, 티켓 209)에 없으므로 숫자를 만들지
        않고 링크 설정 여부만 말한다.
      */}
      <SummaryCard
        name={view.monitoring.dashboardLabel ?? 'Grafana'}
        badge={
          view.links.grafanaUrl === null ? (
            <Pill tone="neutral">링크 없음</Pill>
          ) : (
            <Pill tone="accent">링크 설정됨</Pill>
          )
        }
        metrics={[
          { label: 'Dashboards', value: <MetricValue text={null} /> },
          { label: 'Datasource', value: <MetricValue text={null} /> },
        ]}
        description="대시보드 수와 데이터소스 상태는 Grafana API 연동 후 표시됩니다."
      />
    </div>
  )
}
