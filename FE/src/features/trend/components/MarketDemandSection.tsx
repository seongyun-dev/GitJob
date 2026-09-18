import { useCurrentMarketDemands } from '@/features/matching/hooks/useMatching'
import { formatCollectedAt } from '@/features/matching/model/presentation'
import { marketDemandView } from '@/features/trend/model/marketDemand'
import { hasComputedValue } from '@/shared/api/computeState'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { MeterBar } from '@/shared/ui/MeterBar'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 현재 채용시장 전체 기술 수요 · 티켓 S15P21E102-339.
 *
 * <h2>왜 이 화면에 있나</h2>
 *
 * `/trends`는 목표 직무를 고르기 전에는 "먼저 목표 직무를 선택해 주세요" 한 줄 말고
 * 보여 줄 것이 없었다. 직무를 고르려면 시장이 무엇을 요구하는지 알아야 하는데, 그것을
 * 보려면 직무를 먼저 골라야 하는 순환이었다. 이 영역이 그 고리를 끊는다 — 직무와 무관한
 * 모집단이므로 로그인만으로 볼 수 있다.
 *
 * <h2>숫자의 출처</h2>
 *
 * 순위·건수·비율은 전부 서버 값이다. 비율을 건수/분모로 다시 만들지 않는데, C가 중복
 * 제거와 품질 제외를 거쳐 만든 분모를 우리가 모르기 때문이다. 막대의 기준도 고정값이
 * 아니라 1위 건수다.
 *
 * <h2>값이 아직 없을 때</h2>
 *
 * 시장 Snapshot이 아직 만들어지지 않았으면 서버가 200 + `PREPARING`을 준다. 오류가
 * 아니므로 `ComputeStatePanel`이 준비 중 카드를 그리고 폴링이 이어진다. 여기서 0을
 * 그리면 "요구가 없다"는 다른 말이 된다.
 */
export function MarketDemandSection({ limit }: { limit: number }) {
  const demands = useCurrentMarketDemands({ regions: [], careerLevels: [] })
  const view = marketDemandView(demands.data, hasComputedValue(demands.data))
  const rows = view.rows.slice(0, limit)

  return (
    <DataRegion
      eyebrow="지금 채용시장"
      title="전체 공고가 요구하는 기술"
      hint="목표 직무와 무관하게, 현재 수집된 공고 전체를 기준으로 셉니다."
    >
      <div className="mt-4 grid gap-3">
        <ComputeStatePanel
          isLoading={demands.isLoading}
          error={demands.error}
          state={demands.data}
          loadingLabel="현재 시장의 기술 수요를 불러오는 중입니다."
          onRetry={() => void demands.refetch()}
        />
        <PartialNotice state={demands.data} />

        {view.kind === 'EMPTY' && (
          <StateCard
            kind="NO_DATA"
            title="아직 집계된 기술이 없어요"
            description="수집된 공고에서 요구 기술이 확인되면 표시됩니다."
          />
        )}

        {view.kind === 'ROWS' && (
          <>
            <p className="text-[12px] text-brand-faint">
              {view.jobCount === null
                ? '공고 수 미집계'
                : `공고 ${view.jobCount.toLocaleString('ko-KR')}건 기준`}
              {view.matchingJobCount !== null &&
                ` · 기술이 확인된 공고 ${view.matchingJobCount.toLocaleString('ko-KR')}건`}
              {' · '}
              {formatCollectedAt(view.asOf)}
            </p>
            <ol className="grid gap-3">
              {rows.map((row, index) => (
                <li key={row.techId} className="flex items-start gap-3">
                  <span className="mt-0.5 text-[11px] font-extrabold tabular-nums text-brand-faint">
                    {String(row.rank).padStart(2, '0')}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="truncate text-[13.5px] font-[750] text-brand-ink">
                        {technologyDisplayName(row.techId)}
                      </p>
                      <span className="shrink-0 text-[12px] tabular-nums text-brand-muted">
                        {row.totalCount.toLocaleString('ko-KR')}건 ·{' '}
                        {(row.totalRatio * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="mt-1.5">
                      <MeterBar
                        value={row.totalCount}
                        total={view.topCount}
                        tone={index === 0 ? 'accent' : 'muted'}
                        height={5}
                      />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </DataRegion>
  )
}
