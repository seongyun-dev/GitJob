import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useTarget } from '@/features/matching/hooks/useMatching'
import { toTrendSeries } from '@/features/trend/api/adapter'
import { TrendBarChart } from '@/features/trend/components/TrendBarChart'
import { useTechnologyTrends } from '@/features/trend/hooks/useTrends'
import { ApiError } from '@/shared/api/client'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 트렌드 상세 · 확정 디자인 `Final v2`의 `13 Trend Detail` (S15P21E102-279).
 *
 * 각 출처의 Y축 · 단위 · 기간은 각각 독립이다. 한 화면에 겹쳐 그리거나 합산하지
 * 않는다. 출처마다 상태가 다를 수 있어(READY · NO_DATA · NOT_SUPPORTED) 계열별로
 * 따로 렌더한다.
 *
 * <h2>기간을 화면이 고르지 않는다</h2>
 *
 * 월별 Archive는 조회할 기간을 명시해야 한다. 서버가 임의로 최근 몇 달을 고르면
 * 표시한 기간과 실제 계산 기간이 달라지므로, 사용자가 고른 범위를 그대로 보낸다.
 * 기본값은 최근 완료된 달들이며 미완료 달은 빠진다 — 이번 달을 넣으면 집계가 덜 된
 * 값을 마지막 점으로 그리게 된다.
 *
 * <h2>성장 단계 카드를 그리지 않는다</h2>
 *
 * S6 초안에 있던 "이 기술은 성장기입니다" 카드는 판정 규칙이 아직 어디에도 없다. 세
 * 축을 묶어 단계를 정하는 것은 "출처를 합쳐 종합 점수를 만들지 않는다"는 규칙과
 * 부딪히기도 한다. 없는 판정을 화면이 만들지 않는다.
 */

/** 기본 조회 범위. 이번 달은 뺀다 — 집계가 끝나지 않은 달이다. */
function recentMonths(count: number): string[] {
  const now = new Date()
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - (count - index), 1))
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
  })
}

const RANGES = [
  { label: '최근 3개월', months: 3 },
  { label: '최근 6개월', months: 6 },
  { label: '최근 12개월', months: 12 },
] as const

export function TrendDetailPage() {
  const { techId } = useParams()
  const [range, setRange] = useState<number>(6)
  const periods = useMemo(() => recentMonths(range), [range])
  const target = useTarget()

  const trends = useTechnologyTrends(
    techId,
    periods,
    {
      targetKey: target.data?.targetKey,
      targetRole: target.data?.targetRole,
      regions: target.data?.regions,
      careerLevels: target.data?.careerLevels,
    },
    target.isFetched,
  )
  const series = trends.data === undefined ? [] : toTrendSeries(trends.data)
  const charted = series.filter((item) => item.points.length > 0)
  const stateOnly = series.filter((item) => item.points.length === 0)

  return (
    <div>
      <Link
        to="/trends"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 트렌드 개요
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TREND DETAIL"
          title={techId ?? '이 기술의 출처별 추이'}
          description="출처별 Y축 · 단위 · 기간은 각각 독립적입니다. 서로 비교하거나 합산하지 마세요."
        />
        {/* 조회 범위. 화면이 고른 기간이 그대로 요청에 실린다 */}
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {RANGES.map((option) => (
            <button
              key={option.months}
              type="button"
              aria-pressed={range === option.months}
              onClick={() => setRange(option.months)}
              className={`rounded-[10px] px-3.5 py-2 text-[12.5px] font-bold transition-colors ${
                range === option.months
                  ? 'bg-tone-accent-bg text-brand-ink'
                  : 'border border-brand-line bg-white text-brand-faint hover:text-brand-ink'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {trends.isLoading && (
          <StateCard kind="LOADING" title="추이를 불러오는 중입니다." description="" />
        )}

        {trends.error !== null && (
          <StateCard
            kind="ERROR"
            title={
              trends.error instanceof ApiError
                ? trends.error.message
                : '추이를 불러오지 못했습니다.'
            }
            description={
              trends.error instanceof ApiError ? `오류 코드 ${trends.error.code}` : ''
            }
          />
        )}

        {trends.data !== undefined && (
          /* v2의 `737.8 / 590.2`. 왼쪽이 시계열, 오른쪽이 나머지 출처의 상태다. */
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,737fr)_minmax(0,590fr)]">
            <div className="grid gap-4">
              {charted.length === 0 ? (
                <DataRegion
                  eyebrow="TREND"
                  title="기간별 추이"
                  hint="누락된 기간을 보간하지 않습니다. 값이 없는 달은 0이 아니라 없는 것입니다."
                >
                  <StateCard
                    kind="NO_DATA"
                    title="이 기간에는 표시할 추이가 없어요"
                    description="선택한 범위에 완료된 집계가 없습니다. 범위를 넓히면 달라질 수 있습니다. 화면에서 추세를 만들어내지 않습니다."
                  />
                </DataRegion>
              ) : (
                charted.map((item) => (
                  <DataRegion
                    key={item.sourceId}
                    eyebrow={item.label}
                    title="기간별 추이"
                    hint="누락된 기간을 보간하지 않습니다. 값이 없는 기간은 0이 아니라 없는 것입니다."
                  >
                    <TrendBarChart series={item} />
                  </DataRegion>
                ))
              )}
            </div>

            <DataRegion
              eyebrow="OTHER SOURCES"
              title="다른 출처의 상태"
              hint="출처마다 지원 범위와 기간이 달라 따로 표시합니다."
            >
              {stateOnly.length === 0 ? (
                <p className="text-[12.5px] leading-[1.7] text-brand-muted">
                  이 기술은 준비된 모든 출처에 값이 있어 왼쪽에 계열별로 표시했습니다. 출처마다
                  기간과 단위가 다르므로 서로 비교하거나 합산하지 마세요.
                </p>
              ) : (
                <div className="grid gap-3">
                  {stateOnly.map((item) => (
                    <div
                      key={item.sourceId}
                      className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-600">
                          {item.label}
                        </p>
                        <span className="rounded-full border border-brand-line bg-white px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] text-brand-faint">
                          {item.status}
                        </span>
                      </div>
                      <p className="mt-2 text-[12.5px] font-semibold text-brand-ink-soft">
                        {item.axisLabel}
                      </p>
                      <p className="mt-1.5 text-[11.5px] leading-[1.6] text-brand-muted">
                        {item.note}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </DataRegion>
          </div>
        )}

        {/* 단위 범례. 계열마다 무엇을 세는지 한 줄로 남긴다. */}
        {series.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {series.map((item) => (
              <li
                key={item.sourceId}
                className="rounded-full border border-brand-line bg-white/70 px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
              >
                {item.axisLabel}
              </li>
            ))}
          </ul>
        )}
      </div>

      <PageFootnote>
        출처마다 세는 대상과 분모가 다릅니다. 한 축에 겹쳐 그리거나 합산하지 않으며, 집계가 끝나지
        않은 기간은 0이 아니라 비워 둡니다.
        {techId !== undefined && (
          <>
            {' · '}
            기술 <span className="font-evidence text-brand-muted">{techId}</span>
          </>
        )}
      </PageFootnote>
    </div>
  )
}
